"""$rerank nos precedentes (rag._executar via vector_search/hybrid_search), sem Atlas.

O estágio é medido no eval (eval/run_quality.py). Aqui fica o contrato: o pipeline
é o que roda e o que a UI mostra; falha do $rerank degrada para a mesma busca sem
rerank (funnel explica) só em erro `operacao`; timeout/search/indice/conexão sobem
sem repetir a consulta; a busca híbrida que cai
para vetorial continua reranqueando.
"""

import asyncio

import pytest

import config
import rag
from db import SafeQueryError


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length):
        return self.docs[:length]


class _Chamados:
    """chamados() simulada: `falhas` decide, por pipeline, se levanta SafeQueryError."""

    def __init__(self, falhas=None):
        self.pipelines = []
        self.falhas = falhas or (lambda pipeline: None)

    def aggregate(self, pipeline, maxTimeMS=None):
        self.pipelines.append(pipeline)
        erro = self.falhas(pipeline)
        if erro:
            async def _falha(length):
                raise erro
            cur = _Cursor([])
            cur.to_list = _falha
            return cur
        return _Cursor([{"_id": "x", "numero_chamado": "CHM-2026-0001", "score": 0.9}])


def _stages(pipeline):
    return [next(iter(st)) for st in pipeline]


def _tem_rerank(pipeline):
    return any("$rerank" in st for st in pipeline)


@pytest.fixture
def col(monkeypatch):
    async def passa(aw):
        return await aw

    c = _Chamados()
    monkeypatch.setattr(rag, "chamados", lambda: c)
    monkeypatch.setattr(rag, "safe_query", passa)
    monkeypatch.setattr(config, "RERANK_MODEL", "rerank-2.5-lite")
    return c


def test_vector_com_texto_aplica_rerank_e_preserva_score_anterior(col):
    docs, funnel = asyncio.run(rag.vector_search([0.1] * 4, "cadeira", texto_rerank="Relato: perna quebrou"))
    p = col.pipelines[0]
    assert _stages(p) == ["$vectorSearch", "$addFields", "$set", "$rerank", "$addFields", "$project"]
    assert p[1] == {"$addFields": {"score_recuperacao": {"$meta": "vectorSearchScore"}}}
    rr = p[3]["$rerank"]
    assert rr == {"query": {"text": "Relato: perna quebrou"}, "path": "frase_analise",
                  "numDocsToRerank": rag.LIMIT, "model": "rerank-2.5-lite"}
    assert funnel["rerank"] == {"aplicado": True, "modelo": "rerank-2.5-lite"}
    # o pipeline mostrado na UI é o que rodou, com o $rerank e sem os floats
    mostrado = funnel["query_details"]["pipeline"]
    assert _tem_rerank(mostrado) and "<4 floats omitidos>" in str(mostrado)


def test_sem_texto_ou_modelo_vazio_nao_reranqueia(col, monkeypatch):
    _, funnel = asyncio.run(rag.vector_search([0.1] * 4, "cadeira"))
    assert not _tem_rerank(col.pipelines[-1]) and funnel["rerank"]["aplicado"] is False
    monkeypatch.setattr(config, "RERANK_MODEL", "")
    _, funnel = asyncio.run(rag.vector_search([0.1] * 4, "cadeira", texto_rerank="x"))
    assert not _tem_rerank(col.pipelines[-1]) and funnel["rerank"] == {"aplicado": False, "motivo": "desligado"}


def test_falha_do_rerank_degrada_para_busca_sem_rerank(col):
    col.falhas = lambda p: SafeQueryError("operacao", "Unrecognized pipeline stage name: '$rerank'") if _tem_rerank(p) else None
    docs, funnel = asyncio.run(rag.vector_search([0.1] * 4, "cadeira", texto_rerank="x"))
    assert len(docs) == 1
    assert [_tem_rerank(p) for p in col.pipelines] == [True, False]
    assert funnel["rerank"]["aplicado"] is False and "$rerank" in funnel["rerank"]["motivo"]
    assert not _tem_rerank(funnel["query_details"]["pipeline"])  # UI mostra o que de fato rodou


@pytest.mark.parametrize("kind", ["conexao", "timeout", "search", "indice"])
def test_erro_de_infra_ou_indice_sobe_sem_repetir_a_consulta(col, kind):
    col.falhas = lambda p: SafeQueryError(kind, "falha")
    with pytest.raises(SafeQueryError) as e:
        asyncio.run(rag.vector_search([0.1] * 4, "cadeira", texto_rerank="x"))
    assert e.value.kind == kind and len(col.pipelines) == 1


def test_hybrid_sem_indice_de_texto_cai_para_vetorial_sem_repetir_o_hibrido(col):
    col.falhas = lambda p: SafeQueryError("search", "index not found") if "$rankFusion" in p[0] else None
    _, funnel = asyncio.run(rag.hybrid_search([0.1] * 4, "frase", "cadeira", texto_rerank="x"))
    assert funnel["modo"] == "vector_fallback" and funnel["rerank"]["aplicado"] is True
    assert ["$rankFusion" in p[0] for p in col.pipelines] == [True, False]


def test_hybrid_reranqueia_depois_do_rankfusion(col):
    _, funnel = asyncio.run(rag.hybrid_search([0.1] * 4, "frase", "cadeira", texto_rerank="frase mascarada"))
    p = col.pipelines[0]
    assert _stages(p)[:2] == ["$rankFusion", "$limit"]
    assert p[2] == {"$addFields": {"score_recuperacao": {"$meta": "score"}}}
    assert p[4]["$rerank"]["query"]["text"] == "frase mascarada"
    assert funnel["modo"] == "hybrid" and funnel["rerank"]["aplicado"] is True


def test_hybrid_sem_rankfusion_cai_para_vetorial_e_mantem_rerank(col):
    col.falhas = lambda p: SafeQueryError("operacao", "Unrecognized pipeline stage name: '$rankFusion'") \
        if "$rankFusion" in p[0] else None
    _, funnel = asyncio.run(rag.hybrid_search([0.1] * 4, "frase", "cadeira", texto_rerank="x"))
    assert funnel["modo"] == "vector_fallback"
    assert funnel["rerank"]["aplicado"] is True
    assert _tem_rerank(col.pipelines[-1]) and "$vectorSearch" in col.pipelines[-1][0]


def test_motivo_do_fallback_nao_expoe_namespace(col):
    msg = ("Operação rejeitada pelo MongoDB: Executor error during aggregate command on namespace: "
           "banco_cliente.chamados :: caused by :: Voyage API error: HttpError")
    col.falhas = lambda p: SafeQueryError("operacao", msg) if _tem_rerank(p) else None
    _, funnel = asyncio.run(rag.vector_search([0.1] * 4, "cadeira", texto_rerank="x"))
    assert funnel["rerank"]["motivo"] == "Voyage API error: HttpError"
    assert rag._motivo_curto("Erro sem causa encadeada") == "Erro sem causa encadeada"
    assert "banco_cliente" not in rag._motivo_curto("Operação rejeitada: falha on namespace: banco_cliente.chamados")

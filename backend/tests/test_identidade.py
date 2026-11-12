"""Regra de identidade do produto (rag.decidir_identidade / verificar_identidade), sem Atlas nem Voyage.

Os números dos casos vêm da medição só-imagem de 2026-11-12 (eval/run_quality.py, fotos de demo).
"""

import asyncio

import pytest

import rag

CATEGORIA = {
    "CAD-OFF-PRO": "cadeira", "CAD-GAMER-X": "cadeira", "COL-MOLAS-Q": "colchao",
    "GR-6PORTAS": "guarda_roupa", "GR-3PORTAS": "guarda_roupa",
}
# foto do 3 portas (só imagem): o certo ganha por +0,035, a menor margem legítima medida
FOTO_3P = {"GR-3PORTAS": 0.8580, "GR-6PORTAS": 0.8232, "COL-MOLAS-Q": 0.5952, "CAD-OFF-PRO": 0.5949, "CAD-GAMER-X": 0.5771}
FOTO_GAMER = {"CAD-GAMER-X": 0.9119, "CAD-OFF-PRO": 0.7298, "COL-MOLAS-Q": 0.6290, "GR-6PORTAS": 0.5721, "GR-3PORTAS": 0.5690}


def test_produto_certo_aprovado():
    d = rag.decidir_identidade(FOTO_GAMER, "CAD-GAMER-X", CATEGORIA)
    assert d["status"] == "aprovado"
    assert d["concorrente_sku"] == "CAD-OFF-PRO"
    assert d["margem"] == pytest.approx(0.9119 - 0.7298)


def test_variante_proxima_legitima_ainda_aprova_com_margem_suficiente():
    assert rag.decidir_identidade(FOTO_3P, "GR-3PORTAS", CATEGORIA)["status"] == "aprovado"


def test_variante_errada_com_margem_clara_e_divergente():
    d = rag.decidir_identidade(FOTO_3P, "GR-6PORTAS", CATEGORIA)
    assert d["status"] == "divergente"
    assert d["concorrente_sku"] == "GR-3PORTAS"


@pytest.mark.parametrize("pedido,outro", [("GR-3PORTAS", "GR-6PORTAS"), ("GR-6PORTAS", "GR-3PORTAS")])
def test_empate_entre_variantes_nunca_aprova(pedido, outro):
    # o caso do I08 na regra antiga: 0,8601 x 0,8597 (diferença 0,0004 < margem) era aprovado
    scores = {pedido: 0.8597, outro: 0.8601, "CAD-OFF-PRO": 0.68}
    d = rag.decidir_identidade(scores, pedido, CATEGORIA)
    assert d["status"] == "inconclusivo"
    assert "variante da mesma categoria" in d["motivo"]
    # pedido ligeiramente na frente também não basta
    d2 = rag.decidir_identidade({pedido: 0.8610, outro: 0.8600}, pedido, CATEGORIA)
    assert d2["status"] == "inconclusivo"


def test_borda_da_margem():
    m = rag.IDENTIDADE_MARGEM
    assert rag.decidir_identidade({"A": 0.90, "B": 0.90 - m}, "A")["status"] == "aprovado"
    assert rag.decidir_identidade({"A": 0.90 - m, "B": 0.90}, "A")["status"] == "divergente"
    assert rag.decidir_identidade({"A": 0.90, "B": 0.90 - m / 2}, "A")["status"] == "inconclusivo"


def test_outro_produto_e_divergente():
    d = rag.decidir_identidade(FOTO_GAMER, "COL-MOLAS-Q", CATEGORIA)
    assert d["status"] == "divergente"
    assert d["top_sku"] == "CAD-GAMER-X"
    assert "CAD-GAMER-X" in d["motivo"]


def test_melhor_do_catalogo_mas_abaixo_do_piso_e_inconclusivo():
    d = rag.decidir_identidade({"A": 0.70, "B": 0.55}, "A")
    assert d["status"] == "inconclusivo"
    assert "similaridade é baixa" in d["motivo"]


def test_sku_sem_foto_de_referencia():
    d = rag.decidir_identidade(FOTO_GAMER, "COL-ESPUMA-S", CATEGORIA)
    assert d["status"] == "sem_referencia"
    assert d["score"] is None
    assert "sem foto de referência" in d["motivo"]
    assert d["top_sku"] == "CAD-GAMER-X"  # informativo, não decide


def test_combinar_identidades_pior_vence():
    ok = {"status": "aprovado", "motivo": "a"}
    inc = {"status": "inconclusivo", "motivo": "b"}
    div = {"status": "divergente", "motivo": "c"}
    assert rag.combinar_identidades([ok, inc])["status"] == "inconclusivo"
    assert rag.combinar_identidades([inc, div, ok]) == {"status": "divergente", "motivo": "c"}
    assert rag.combinar_identidades([ok])["status"] == "aprovado"


# --- verificar_identidade com o Atlas simulado -------------------------------------------------


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length):
        return self.docs[:length]


class _ColFake:
    """catalogo_fotos simulada: devolve `top` sem filtro e `por_sku[sku]` com filtro de sku."""

    def __init__(self, top, por_sku):
        self.top, self.por_sku, self.pipelines = top, por_sku, []

    def aggregate(self, pipeline, maxTimeMS=None):
        self.pipelines.append(pipeline)
        filtro = pipeline[0]["$vectorSearch"].get("filter")
        return _Cursor(self.por_sku.get(filtro["sku"], []) if filtro else self.top)


def _verificar(monkeypatch, col, sku, categoria):
    async def passa(aw):
        return await aw

    monkeypatch.setattr(rag, "catalogo_fotos", lambda: col)
    monkeypatch.setattr(rag, "safe_query", passa)
    return asyncio.run(rag.verificar_identidade([0.0] * 4, sku, categoria))


def _docs(scores):
    return [{"sku": s, "categoria": CATEGORIA.get(s), "score": v} for s, v in scores.items()]


def test_verificar_sem_referencia_consulta_filtrada_e_marca_revisao(monkeypatch):
    col = _ColFake(_docs(FOTO_GAMER), por_sku={})
    r = _verificar(monkeypatch, col, "COL-ESPUMA-S", "colchao")
    assert r["status"] == "sem_referencia"
    assert r["abaixo_threshold"] is True  # compatibilidade: não aprovado
    assert len(col.pipelines) == 2 and col.pipelines[1][0]["$vectorSearch"]["filter"] == {"sku": "COL-ESPUMA-S"}
    assert "<4 floats omitidos>" in str(r["query_details"])


def test_verificar_sku_fora_do_top30_usa_score_filtrado(monkeypatch):
    col = _ColFake(_docs(FOTO_GAMER), por_sku={"COL-ESPUMA-S": [{"sku": "COL-ESPUMA-S", "categoria": "colchao", "score": 0.61}]})
    r = _verificar(monkeypatch, col, "COL-ESPUMA-S", "colchao")
    assert r["status"] == "divergente"
    assert r["score"] == pytest.approx(0.61)


def test_verificar_produto_certo_uma_consulta_so(monkeypatch):
    col = _ColFake(_docs(FOTO_GAMER), por_sku={})
    r = _verificar(monkeypatch, col, "CAD-GAMER-X", "cadeira")
    assert r["status"] == "aprovado" and r["abaixo_threshold"] is False
    assert r["fotos_comparadas"] == 5 and len(col.pipelines) == 1


def test_verificar_catalogo_vazio(monkeypatch):
    r = _verificar(monkeypatch, _ColFake([], por_sku={}), "CAD-GAMER-X", "cadeira")
    assert r["status"] == "sem_referencia" and r["score"] is None
    assert "Catálogo sem fotos" in r["motivo"]

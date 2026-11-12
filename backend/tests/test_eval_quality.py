"""Testes do eval de qualidade (eval/run_quality.py): métricas puras e gabarito, sem Atlas/Voyage/LLM."""

import importlib.util
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "eval" / "run_quality.py"
_spec = importlib.util.spec_from_file_location("run_quality", _PATH)
rq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rq)


def test_rank_of():
    assert rq.rank_of(["a", "b", "c"], ["b"]) == 2
    assert rq.rank_of(["a", "b"], ["z"]) is None
    assert rq.rank_of(["a", "b"], ["b", "a"]) == 1


def test_retrieval_metrics():
    m = rq.retrieval_metrics([1, 2, None, 4])
    assert m == {"n": 4, "recall_at_1": 0.25, "recall_at_3": 0.5, "mrr": round((1 + 0.5 + 0.25) / 4, 4)}
    assert rq.retrieval_metrics([])["recall_at_1"] == 0.0


def test_identity_metrics():
    m = rq.identity_metrics([("aprovado", "aprovado"), ("aprovado", "divergente"),
                             ("divergente", "divergente"), ("divergente", "aprovado"), ("divergente", "erro")])
    assert m["accuracy"] == 0.4
    assert m["falsa_rejeicao"] == 0.5
    assert m["falsa_aceitacao"] == round(1 / 3, 4)


def test_identity_metrics_aceitaveis_e_estados():
    m = rq.identity_metrics([
        ("divergente", "inconclusivo", ["divergente", "inconclusivo"]),  # variante: revisar é aceitável
        ("divergente", "aprovado", ["divergente", "inconclusivo"]),      # falsa aceitação
        ("sem_referencia", "sem_referencia", None),
        ("aprovado", "inconclusivo", None),                               # falsa rejeição
    ])
    assert m["accuracy"] == 0.5
    assert m["falsa_aceitacao"] == round(1 / 3, 4)
    assert m["falsa_rejeicao"] == 1.0
    assert m["inconclusivo"] == 2 and m["sem_referencia"] == 1


def test_validar_gabarito_recusa_aprovado_em_caso_nao_legitimo():
    produtos, catalogo, seed_ids = rq._carregar_backend()
    gab = {"busca": [], "identidade": [{"id": "X", "sku_pedido": "GR-3PORTAS", "imagem": "frontend/public/demo/GR-6PORTAS.jpg",
                                         "esperado": "divergente", "aceitaveis": ["divergente", "aprovado"]}]}
    assert any("nao pode aceitar" in e for e in rq.validar_gabarito(gab, produtos, catalogo, seed_ids))


def test_veredito_ok():
    base = {"classificacao": "inconclusivo", "revisao_humana": True, "racional": "x", "_meta": {"mode": "claude_tool_use"}}
    assert rq.veredito_ok(base, ["inconclusivo"]) == (True, True)
    assert rq.veredito_ok(base, ["mau_uso"]) == (True, False)
    assert rq.veredito_ok({**base, "_meta": {"mode": "manual_review_fallback"}}, ["inconclusivo"]) == (False, False)
    assert rq.veredito_ok({**base, "revisao_humana": False}, ["inconclusivo"])[0] is False


def test_gabarito_versionado_e_valido():
    gab = json.loads(rq.GABARITO.read_text(encoding="utf-8"))
    assert gab["_status"].lower().startswith(("rascunho", "validado"))
    produtos, catalogo, seed_ids = rq._carregar_backend()
    assert rq.validar_gabarito(gab, produtos, catalogo, seed_ids) == []
    assert 15 <= len(gab["busca"]) + len(gab["identidade"]) <= 60
    assert {c["esperado"] for c in gab["identidade"]} == {"aprovado", "divergente", "sem_referencia"}
    # nenhum caso não legítimo aceita "aprovado" (falsa aceitação nunca vira acerto)
    assert all("aprovado" not in c.get("aceitaveis", [c["esperado"]])
               for c in gab["identidade"] if c["esperado"] != "aprovado")
    assert 1 <= sum(1 for c in gab["busca"] if c.get("llm")) <= 6  # tier llm barato


def test_validar_gabarito_aponta_erros():
    produtos, catalogo, seed_ids = rq._carregar_backend()
    gab = {"busca": [{"id": "X", "sku": "CAD-OFF-PRO", "imagem": "nao/existe.jpg", "checklist": ["odor_forte"],
                      "descricao": "", "relevantes": ["CHM-9999"]}],
           "identidade": [{"id": "X", "sku_pedido": "NAO-EXISTE", "imagem": "x", "checklist": [], "esperado": "ok"}]}
    erros = rq.validar_gabarito(gab, produtos, catalogo, seed_ids)
    assert any("duplicados" in e for e in erros)
    assert any("odor_forte" in e for e in erros)
    assert any("CHM-9999" in e for e in erros)
    assert any("imagem ausente" in e for e in erros)
    assert any("NAO-EXISTE" in e for e in erros)


def test_summarize_achata_metricas():
    res = {"erros": 0, "erros_gabarito": [],
           "busca": {"vector": {"n": 2, "recall_at_1": 1.0, "recall_at_3": 1.0, "mrr": 1.0},
                     "hybrid": {"n": 2, "recall_at_1": 0.5, "recall_at_3": 1.0, "mrr": 0.75}, "hybrid_fallback": 0},
           "identidade": {"n": 3, "accuracy": 1.0, "falsa_rejeicao": 0.0, "falsa_aceitacao": 0.0},
           "corpus": {"fora_do_seed": 0, "seed_ausente": 0}}
    s = rq.summarize(res)
    assert s["hybrid_recall_at_1"] == 0.5 and s["identidade_accuracy"] == 1.0 and s["busca_n"] == 2


def test_main_sempre_exit_0_mesmo_com_falha(tmp_path, monkeypatch):
    async def boom(secoes, gab):
        raise RuntimeError("atlas fora")

    monkeypatch.setattr(rq, "_run", boom)
    out = tmp_path / "r.json"
    assert rq.main(["--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["summary"]["errors"] == 1 and "atlas fora" in data["falha"]


@pytest.mark.parametrize("secoes", ["nada", "busca,xyz"])
def test_secoes_invalidas_nao_quebram(secoes, tmp_path):
    assert rq.main(["--secoes", secoes, "--out", str(tmp_path / "r.json")]) == 0

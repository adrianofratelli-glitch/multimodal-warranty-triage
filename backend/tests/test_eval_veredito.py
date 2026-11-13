"""Testes dos evals da Fase 3 (veredito do LLM e busca ampliada): funções puras e gabaritos, sem rede."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))


def _load(nome: str):
    spec = importlib.util.spec_from_file_location(nome, EVAL / f"{nome}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vc = _load("veredito_checks")
rba = _load("run_busca_ampliada")

PRECS = [
    {"resolucao_final": "defeito_fabrica", "score": 0.925, "categoria": "cadeira"},
    {"resolucao_final": "mau_uso", "score": 0.612, "categoria": "cadeira"},
]


def _v(classe="defeito_fabrica", racional="Defeito de fabricação no pistão.", conf=0.7, **kw):
    return {"classificacao": classe, "confianca": conf, "racional": racional, "sinais_observados": [],
            "revisao_humana": True, "alerta_manipulacao": False, "_meta": {"mode": "claude_tool_use"}, **kw}


def test_politica_bate_com_sugestoes_da_fila_de_revisao():
    # A política do eval é a mesma das sugestões que o revisor vê (Revisao.jsx).
    src = (ROOT / "frontend" / "src" / "tabs" / "Revisao.jsx").read_text(encoding="utf-8")
    palavra = {"aprovado": "aprovad", "negado": "negad", "revisao_humana": "mais fotos"}
    for classe, decisao in vc.POLITICA.items():
        linha = next(ln for ln in src.splitlines() if ln.strip().startswith(f"{classe}:"))
        assert palavra[decisao] in linha.lower(), (classe, linha)


def test_decisao_de_fallback_vira_revisao_humana():
    assert vc.decisao_de(_v("mau_uso")) == "negado"
    assert vc.decisao_de(_v("defeito_transporte")) == "aprovado"
    assert vc.decisao_de(_v("mau_uso", _meta={"mode": "manual_review_fallback"})) == "revisao_humana"
    assert vc.decisao_de({"classificacao": "outra"}) == "revisao_humana"


def test_lastro_aceita_precedente_e_score_recuperados():
    v = _v(racional="O precedente de maior score (0.925) foi resolvido como defeito_fabrica, mesmo sintoma.")
    assert vc.checar_lastro(v, PRECS, "cadeira") == []
    # percentagem também confere (92,5% ~ 0.925)
    assert vc.checar_lastro(_v(racional="Similaridade de 92,5% com o caso anterior."), PRECS, "cadeira") == []


@pytest.mark.parametrize("racional,tipo", [
    ("Igual ao chamado CHM-2026-0003, defeito de fábrica.", "id_inventado"),
    ("Os precedentes apontam defeito de transporte.", "causa_de_precedente_inexistente"),
    ("Cinco precedentes confirmam defeito de fábrica.", "contagem_de_precedentes"),
    ("O score 0.88 do histórico indica fábrica.", "score_inexistente"),
    ("Como no colchão do outro caso, é defeito de fábrica.", "outra_categoria"),
])
def test_lastro_pega_afirmacao_sem_suporte(racional, tipo):
    tipos = {a["tipo"] for a in vc.checar_lastro(_v(racional=racional), PRECS, "cadeira")}
    assert tipo in tipos


def test_lastro_base_fria():
    assert vc.checar_lastro(_v(racional="Sem precedentes recuperados; o relato sugere pistão."), [], "cadeira") == []
    achados = vc.checar_lastro(_v(racional="Os precedentes indicam defeito de fábrica."), [], "cadeira")
    assert [a["tipo"] for a in achados] == ["precedente_sem_recuperacao"]


def test_coerencia():
    assert vc.checar_coerencia(_v())["racional_sustenta"]
    assert not vc.checar_coerencia(_v("mau_uso", racional="Defeito de fábrica evidente."))["racional_sustenta"]
    assert vc.checar_coerencia(_v("inconclusivo", racional="A imagem não mostra o defeito."))["racional_sustenta"]
    assert not vc.checar_coerencia(_v("inconclusivo", racional="Claramente o pistão quebrou."))["racional_sustenta"]
    assert vc.checar_coerencia(_v(conf=0.3))["confianca_baixa_decisiva"]


def test_avaliar_e_agregar_decisao_oposta_e_alerta():
    caso = {"decisao_esperada": "negado", "decisao_aceitaveis": ["negado", "revisao_humana"], "espera_alerta": True}
    linha = vc.avaliar(_v("defeito_fabrica"), caso, PRECS, "cadeira")
    assert linha["decisao"] == "aprovado" and linha["decisao_oposta"] and not linha["decisao_ok"]
    assert linha["alerta_ok"] is False
    ok = vc.avaliar(_v("inconclusivo", racional="Inconclusivo.", alerta_manipulacao=True), caso, PRECS, "cadeira")
    assert ok["decisao_ok"] and not ok["decisao_estrita"] and ok["alerta_ok"]
    agg = vc.agregar([{**linha, "id": "a"}, {**ok, "id": "b"}])
    assert agg["decisao_oposta"] == 1 and agg["decisao_ok_rate"] == 0.5 and agg["alerta_ok_rate"] == 0.5


def test_variancia_entre_rodadas():
    r1 = [{"id": "a", "classificacao": "mau_uso", "decisao": "negado", "confianca": 0.6, "valido": True},
          {"id": "b", "classificacao": "inconclusivo", "decisao": "revisao_humana", "confianca": 0.4, "valido": True}]
    r2 = [{"id": "a", "classificacao": "mau_uso", "decisao": "negado", "confianca": 0.7, "valido": True},
          {"id": "b", "classificacao": "defeito_fabrica", "decisao": "aprovado", "confianca": 0.6, "valido": True}]
    var = vc.variancia([r1, r2])
    assert var["mesma_causa_rate"] == 0.5 and var["instaveis"] == ["b"]
    assert var["delta_confianca_max"] == pytest.approx(0.2)
    assert vc.variancia([r1]) == {}


def test_concordancia_juiz():
    linhas = [{"lastro_ok": True, "racional_sustenta": True, "juiz": {"suportado": True, "coerente": True}},
              {"lastro_ok": True, "racional_sustenta": True, "juiz": {"suportado": False, "coerente": True}},
              {"lastro_ok": True, "juiz": {"erro": "sem_tool_use"}}]
    c = vc.concordancia_juiz(linhas)
    assert c["n"] == 2 and c["lastro_concorda_rate"] == 0.5 and c["juiz_sem_suporte"] == 1


def _backend():
    from defeitos_catalog import CATALOGO_DEFEITOS
    from pedidos_data import PEDIDOS_SEED
    from seed_data import CHAMADOS_SEED

    produtos = {it["sku"]: it for itens in PEDIDOS_SEED.values() for it in itens}
    return produtos, CATALOGO_DEFEITOS, {c["numero_chamado"]: c for c in CHAMADOS_SEED}


def test_gabarito_veredito_rascunho_coerente_com_seed():
    gab = json.loads((EVAL / "gabarito_veredito.draft.json").read_text(encoding="utf-8"))
    assert gab["_status"].startswith("RASCUNHO")
    produtos, catalogo, seed = _backend()
    validado = {c["id"]: c for c in json.loads((EVAL / "gabarito_qualidade.json").read_text(encoding="utf-8"))["busca"]}
    ids = [c["id"] for c in gab["casos"]]
    assert len(ids) == len(set(ids)) == 24
    for c in gab["casos"]:
        assert c["sku"] in produtos and (ROOT / c["imagem"]).exists()
        assert set(c["checklist"]) <= set(catalogo[produtos[c["sku"]]["categoria"]])
        assert c["decisao_esperada"] in c["decisao_aceitaveis"] and set(c["decisao_aceitaveis"]) <= set(vc.DECISOES)
        if c.get("origem"):  # V01-V20 repetem a consulta validada; causa = resolução do precedente do seed
            ref = validado[c["origem"]]
            assert (c["sku"], c["checklist"], c["descricao"]) == (ref["sku"], ref["checklist"], ref["descricao"])
            assert c["causa_seed"] == seed[ref["relevantes"][0]]["resolucao_final"]
            assert c["decisao_esperada"] == vc.POLITICA[c["causa_seed"]]
        if c.get("causa_seed") == "mau_uso":
            assert "aprovado" not in c["decisao_aceitaveis"]


def test_gabarito_busca_ampliada_rascunho_valido():
    gab = json.loads((EVAL / "gabarito_busca_ampliada.draft.json").read_text(encoding="utf-8"))
    assert gab["_status"].startswith("RASCUNHO")
    produtos, catalogo, seed = _backend()
    assert rba.validar(gab, produtos, catalogo, set(seed)) == []
    tipos = {c["tipo"] for c in gab["casos"]}
    assert {"so_foto", "foto_de_variante", "vaga", "fora_do_catalogo"} <= tipos


def test_gabarito_validado_intocado():
    # O gabarito validado pelo usuário não muda na Fase 3 (20 consultas + 30 casos de identidade).
    gab = json.loads((EVAL / "gabarito_qualidade.json").read_text(encoding="utf-8"))
    assert gab["_status"].startswith("VALIDADO")
    assert len(gab["busca"]) == 20 and len(gab["identidade"]) == 30


def test_validar_busca_ampliada_pega_erros():
    produtos, catalogo, seed = _backend()
    gab = {"casos": [
        {"id": "X1", "sku": "CAD-OFF-PRO", "imagem": "frontend/public/demo/CAD-OFF-PRO.jpg", "checklist": ["inexistente"],
         "descricao": "", "relevantes": ["CHM-9999"]},
        {"id": "X2", "tipo": "fora", "sku": "NOVO", "categoria": "cadeira", "imagem": "nao/existe.jpg", "checklist": [],
         "descricao": "", "relevantes": [], "esperado_vazio": True},
    ]}
    erros = " | ".join(rba.validar(gab, produtos, catalogo, set(seed)))
    for trecho in ("item inexistente", "fora do seed", "esperado_vazio exige", "imagem ausente"):
        assert trecho in erros


def test_agregar_busca_ampliada():
    linhas = [
        {"tipo": "vaga", "relevantes": ["a"], "vector": {"rank": 1, "gap_top1_top2": 0.02}, "hybrid": {"rank": 2, "gap_top1_top2": 0.05}},
        {"tipo": "fora", "relevantes": [], "esperado_vazio": True, "vector": {"retrieved": 0}, "hybrid": {"retrieved": 1},
         "identidade_esperada": "sem_referencia", "identidade": "sem_referencia"},
    ]
    m = rba.agregar(linhas)
    assert m["vector"]["recall_at_1"] == 1.0 and m["hybrid"]["mrr"] == 0.5
    assert m["vector"]["vazio_ok_rate"] == 1.0 and m["hybrid"]["vazio_ok_rate"] == 0.0
    assert m["vector"]["ambiguas"] == 1 and m["identidade_ok_rate"] == 1.0


def test_classe_da_resolucao_texto_livre_do_revisor():
    assert vc.classe_da_resolucao("mau_uso") == "mau_uso"
    assert vc.classe_da_resolucao("Troca aprovada — defeito de fábrica confirmado.") == "defeito_fabrica"
    assert vc.classe_da_resolucao("Garantia negada — caracterizado mau uso pelo cliente.") == "mau_uso"
    assert vc.classe_da_resolucao("revisor 0") is None
    precs = [{"resolucao_final": "Reenvio aprovado — avaria de transporte confirmada.", "score": 0.8}]
    assert vc.checar_lastro(_v(racional="O precedente foi resolvido como transporte."), precs, "cadeira") == []


def test_reavaliar_relatorio_gravado_sem_llm():
    rv = _load("run_veredito")
    gab = {"casos": [{"id": "V1", "decisao_esperada": "negado", "decisao_aceitaveis": ["negado", "revisao_humana"]}]}
    rel = {"recuperacao": {"V1": {"categoria": "cadeira", "precedentes": PRECS}}, "casos": [
        {"id": "V1", "rodada": r, "tipo": "seed", "classificacao": "mau_uso", "confianca": 0.6, "valido": True,
         "racional": "Classificado como mau_uso: o cliente derramou bebida.", "sinais": [], "modo_llm": "claude_tool_use",
         "juiz": {"suportado": True, "coerente": True}} for r in (1, 2)]}
    res = rv.reavaliar(rel, gab)
    assert [r["decisao_ok_rate"] for r in res["rodadas"]] == [1.0, 1.0]
    assert res["rodadas"][0]["racional_sustenta_rate"] == 1.0  # "mau_uso" com sublinhado conta
    assert res["variancia"]["mesma_decisao_rate"] == 1.0 and res["rodadas"][0]["juiz"]["n"] == 1

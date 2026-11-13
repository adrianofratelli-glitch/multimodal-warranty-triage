"""Checagens determinísticas do veredito do LLM (sem rede, sem Atlas): política, lastro e coerência.

Usado por `eval/run_veredito.py` e testado em `backend/tests/test_eval_veredito.py`.

Política de garantia do seed (a mesma das sugestões da fila de revisão, `frontend/src/tabs/Revisao.jsx`):
causa `defeito_fabrica` -> troca aprovada; `defeito_transporte` -> reenvio aprovado; `mau_uso` -> garantia
negada; `inconclusivo` (ou fallback de revisão manual) -> revisão humana (pedir mais fotos). O veredito do
modelo é sempre revisado por uma pessoa (`revisao_humana=true`); aqui "decisão" é a recomendação que a
política deriva da causa.

Lastro: o modelo só recebe o relato do cliente (frase com PII mascarada), as fotos e os precedentes
recuperados (categoria/tipo, relato, score, `resolvido como`). Não há cláusula de política no contexto do
modelo (ver plano da Fase 3). Uma afirmação sobre precedente só tem lastro se bater com o que foi recuperado.
As checagens são léxicas e conservadoras: o juiz via Grove (`run_veredito.py --juiz`) é a segunda opinião.
"""

from __future__ import annotations

import re
import unicodedata

CLASSES = ("defeito_fabrica", "defeito_transporte", "mau_uso", "inconclusivo")
DECISOES = ("aprovado", "negado", "revisao_humana")

POLITICA = {
    "defeito_fabrica": "aprovado",     # troca
    "defeito_transporte": "aprovado",  # reenvio
    "mau_uso": "negado",
    "inconclusivo": "revisao_humana",  # pedir mais fotos
}
OPOSTAS = {("aprovado", "negado"), ("negado", "aprovado")}


def _norm(texto: str) -> str:
    """minúsculas sem acento (o modelo alterna 'fábrica'/'fabrica')."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return t.lower().replace("_", " ")  # "mau_uso" no racional conta como "mau uso"


# Termos (sem acento) que associam um trecho a uma causa decisiva.
TERMOS_CLASSE = {
    "defeito_fabrica": re.compile(r"fabrica|fabricacao|fabricante|manufatura|vicio (?:de|do) produto|montagem de fabrica"),
    "defeito_transporte": re.compile(r"transporte|entrega|transportadora|frete|logistic|manuseio no envio|avaria"),
    "mau_uso": re.compile(r"mau uso|mal uso|uso inadequado|uso indevido|uso incorreto|negligencia|causa externa|acidente|derram"),
}
INCERTEZA = re.compile(
    r"inconclusiv|nao (?:e|foi) possivel|insuficiente|nao (?:permite|mostra|evidencia|exibe|apresenta|revela|ha evid)"
    r"|sem evidencia|incert|indetermin|dificil (?:determinar|afirmar|concluir)|nao (?:se )?(?:pode|consegue) (?:afirmar|determinar|confirmar)"
    r"|nao visivel|nao e visivel|sem sinal|mais fotos|imagem (?:nao|sem)|impossibilit|impede|nao (?:sustenta|confirma)"
)
PRECEDENTE = re.compile(r"precedente|historic|casos? (?:semelhante|similar|anterior|parecido)|chamados? (?:semelhante|similar|anterior)")
NEGACAO_ANTES = re.compile(r"(?:sem|nenhum|nenhuma|nao ha|nao existem?|ausencia de|faltam|base(?: historica)? fria)\W+(?:\w+\W+){0,2}$")
IDS = re.compile(r"\b(?:chm-\d{4}-[0-9a-f]{4,6}|ped-\d{3,})\b")
NUM_PALAVRA = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7}
CONTAGEM = re.compile(r"\b(\d+|um|uma|dois|duas|tres|quatro|cinco|seis|sete)\s+(?:dos\s+|de\s+)?(?:\d+\s+)?precedentes")
SCORE = re.compile(r"(?:score|similaridade)\D{0,12}?(0[.,]\d{2,4}|1[.,]0+|\d{2}(?:[.,]\d)?\s?%)")
CATEGORIAS = {
    "cadeira": re.compile(r"\bcadeiras?\b"),
    "colchao": re.compile(r"\bcolch(?:ao|oes)\b"),
    "guarda_roupa": re.compile(r"\bguarda[- ]roupas?\b"),
}
JANELA = 90  # caracteres depois de "precedente" em que um termo de causa é lido como causa do precedente


def classe_da_resolucao(resolucao) -> str | None:
    """Causa de um precedente. O seed grava a classe; o revisor humano grava texto livre
    (ex.: "Troca aprovada — defeito de fabrica confirmado."), lido pelos mesmos termos."""
    if resolucao in CLASSES:
        return resolucao
    texto = _norm(resolucao)
    achadas = [c for c, rx in TERMOS_CLASSE.items() if rx.search(texto)]
    return achadas[0] if len(achadas) == 1 else None


def decisao_de(veredito: dict) -> str:
    """Decisão que a política deriva do veredito (fallback de revisão manual -> revisão humana)."""
    if veredito.get("_meta", {}).get("mode") == "manual_review_fallback":
        return "revisao_humana"
    return POLITICA.get(veredito.get("classificacao"), "revisao_humana")


def _texto(veredito: dict) -> str:
    partes = [str(veredito.get("racional", ""))] + [str(s) for s in veredito.get("sinais_observados") or []]
    return _norm(" \n ".join(partes))


def _frases(texto: str) -> list[str]:
    return [f for f in re.split(r"(?<=[.;!?])\s+|\n", texto) if f.strip()]


def checar_lastro(veredito: dict, precedentes: list[dict], categoria: str) -> list[dict]:
    """Afirmações sem lastro no contexto que o modelo recebeu. Cada item: {tipo, trecho}."""
    texto = _texto(veredito)
    achados: list[dict] = []
    resolucoes = {classe_da_resolucao(p.get("resolucao_final")) for p in precedentes}
    scores = [float(p.get("score") or 0.0) for p in precedentes]

    for m in IDS.finditer(texto):  # o contexto do modelo não traz número de chamado nem de pedido
        achados.append({"tipo": "id_inventado", "trecho": m.group(0)})

    for m in PRECEDENTE.finditer(texto):
        antes = texto[max(0, m.start() - 40):m.start()]
        if NEGACAO_ANTES.search(antes):
            continue
        if not precedentes:
            achados.append({"tipo": "precedente_sem_recuperacao", "trecho": texto[max(0, m.start() - 20):m.end() + 40]})
            continue
        janela = texto[m.start():m.end() + JANELA]
        fim = re.search(r"[.;!?]", janela[len(m.group(0)):])
        if fim:
            janela = janela[:len(m.group(0)) + fim.start()]
        for classe, rx in TERMOS_CLASSE.items():
            if rx.search(janela) and classe not in resolucoes:
                achados.append({"tipo": "causa_de_precedente_inexistente", "trecho": janela[:140], "classe": classe})

    for m in CONTAGEM.finditer(texto):
        bruto = m.group(1)
        n = int(bruto) if bruto.isdigit() else NUM_PALAVRA[bruto]
        if n > len(precedentes):
            achados.append({"tipo": "contagem_de_precedentes", "trecho": m.group(0), "recuperados": len(precedentes)})

    for m in SCORE.finditer(texto):
        bruto = m.group(1).replace(",", ".").replace(" ", "")
        v = float(bruto[:-1]) / 100 if bruto.endswith("%") else float(bruto)
        tol = 0.006 if bruto.endswith("%") else 0.0015
        if not any(abs(v - s) <= tol for s in scores):
            achados.append({"tipo": "score_inexistente", "trecho": m.group(0)})

    for cat, rx in CATEGORIAS.items():
        if cat != categoria and rx.search(texto):
            achados.append({"tipo": "outra_categoria", "trecho": cat})
    return achados


def checar_coerencia(veredito: dict) -> dict:
    """O racional sustenta a causa escolhida? (decisiva: cita a causa; inconclusivo: expressa incerteza)."""
    classe = veredito.get("classificacao")
    texto = _texto(veredito)
    if veredito.get("_meta", {}).get("mode") == "manual_review_fallback":
        return {"racional_sustenta": True, "confianca_baixa_decisiva": False}
    if classe == "inconclusivo":
        sustenta = bool(INCERTEZA.search(texto))
    else:
        sustenta = bool(TERMOS_CLASSE.get(classe, re.compile(r"$^")).search(texto))
    try:
        conf = float(veredito.get("confianca", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return {"racional_sustenta": sustenta, "confianca_baixa_decisiva": classe != "inconclusivo" and conf < 0.5}


def avaliar(veredito: dict, caso: dict, precedentes: list[dict], categoria: str) -> dict:
    """Linha do relatório para um veredito contra um caso do gabarito de veredito."""
    meta = veredito.get("_meta", {})
    valido = (
        meta.get("mode") != "manual_review_fallback"
        and veredito.get("classificacao") in CLASSES
        and veredito.get("revisao_humana") is True
        and bool(str(veredito.get("racional", "")).strip())
    )
    decisao = decisao_de(veredito)
    esperada = caso.get("decisao_esperada")
    aceitaveis = caso.get("decisao_aceitaveis") or ([esperada] if esperada else list(DECISOES))
    lastro = checar_lastro(veredito, precedentes, categoria)
    coer = checar_coerencia(veredito)
    linha = {
        "valido": valido,
        "classificacao": veredito.get("classificacao"),
        "confianca": veredito.get("confianca"),
        "decisao": decisao,
        "decisao_ok": decisao in aceitaveis,
        "decisao_estrita": esperada is not None and decisao == esperada,
        "decisao_oposta": (decisao, esperada) in OPOSTAS,
        "lastro_ok": not lastro,
        "sem_lastro": lastro,
        **coer,
        "alerta_manipulacao": bool(veredito.get("alerta_manipulacao")),
    }
    if "espera_alerta" in caso:
        linha["alerta_ok"] = linha["alerta_manipulacao"] == bool(caso["espera_alerta"])
    return linha


def agregar(linhas: list[dict]) -> dict:
    """Taxas de uma rodada (casos com erro de execução contam como falha)."""
    n = len(linhas)
    if not n:
        return {"n": 0}

    def taxa(chave: str, base: list[dict] | None = None) -> float:
        base = linhas if base is None else base
        return round(sum(1 for x in base if x.get(chave)) / len(base), 4) if base else 0.0

    com_alerta = [x for x in linhas if "alerta_ok" in x]
    decididos = [x for x in linhas if x.get("decisao_estrita") is not None and not x.get("erro")]
    dist: dict[str, int] = {}
    for x in linhas:
        dist[x.get("decisao") or "erro"] = dist.get(x.get("decisao") or "erro", 0) + 1
    return {
        "n": n,
        "valido_rate": taxa("valido"),
        "decisao_ok_rate": taxa("decisao_ok"),
        "decisao_estrita_rate": taxa("decisao_estrita", decididos),
        "decisao_oposta": sum(1 for x in linhas if x.get("decisao_oposta")),
        "lastro_ok_rate": taxa("lastro_ok"),
        "afirmacoes_sem_lastro": sum(len(x.get("sem_lastro") or []) for x in linhas),
        "racional_sustenta_rate": taxa("racional_sustenta"),
        "confianca_baixa_decisiva": sum(1 for x in linhas if x.get("confianca_baixa_decisiva")),
        "alerta_ok_rate": taxa("alerta_ok", com_alerta) if com_alerta else None,
        "decisoes": dict(sorted(dist.items())),
        "erros": sum(1 for x in linhas if x.get("erro")),
    }


def variancia(rodadas: list[list[dict]]) -> dict:
    """Estabilidade entre rodadas: mesma causa/decisão por caso e amplitude das taxas."""
    if len(rodadas) < 2:
        return {}
    por_caso: dict[str, list[dict]] = {}
    for r in rodadas:
        for x in r:
            por_caso.setdefault(x["id"], []).append(x)
    ids = [i for i, xs in por_caso.items() if len(xs) == len(rodadas)]
    mesma_causa = sum(1 for i in ids if len({x.get("classificacao") for x in por_caso[i]}) == 1)
    mesma_decisao = sum(1 for i in ids if len({x.get("decisao") for x in por_caso[i]}) == 1)
    deltas_conf = []
    for i in ids:
        cs = [x.get("confianca") for x in por_caso[i] if isinstance(x.get("confianca"), int | float)]
        if len(cs) == len(rodadas):
            deltas_conf.append(max(cs) - min(cs))
    aggs = [agregar(r) for r in rodadas]
    amplitude = {}
    for k in ("valido_rate", "decisao_ok_rate", "decisao_estrita_rate", "lastro_ok_rate", "racional_sustenta_rate"):
        vals = [a[k] for a in aggs if a.get(k) is not None]
        if vals:
            amplitude[k] = round(max(vals) - min(vals), 4)
    return {
        "casos": len(ids),
        "mesma_causa_rate": round(mesma_causa / len(ids), 4) if ids else 0.0,
        "mesma_decisao_rate": round(mesma_decisao / len(ids), 4) if ids else 0.0,
        "delta_confianca_medio": round(sum(deltas_conf) / len(deltas_conf), 4) if deltas_conf else None,
        "delta_confianca_max": round(max(deltas_conf), 4) if deltas_conf else None,
        "amplitude_taxas": amplitude,
        "instaveis": sorted(i for i in ids if len({x.get("decisao") for x in por_caso[i]}) > 1),
    }


def concordancia_juiz(linhas: list[dict]) -> dict:
    """Juiz x léxico: concordam em 'tem afirmação sem lastro?' e em 'racional sustenta a causa?'."""
    com = [x for x in linhas if isinstance(x.get("juiz"), dict) and "suportado" in x["juiz"]]
    if not com:
        return {"n": 0}
    lastro = sum(1 for x in com if bool(x["juiz"]["suportado"]) == bool(x.get("lastro_ok")))
    coer = sum(1 for x in com if bool(x["juiz"].get("coerente")) == bool(x.get("racional_sustenta")))
    return {
        "n": len(com),
        "lastro_concorda_rate": round(lastro / len(com), 4),
        "coerencia_concorda_rate": round(coer / len(com), 4),
        "juiz_sem_suporte": sum(1 for x in com if not x["juiz"]["suportado"]),
        "juiz_incoerente": sum(1 for x in com if not x["juiz"].get("coerente")),
    }

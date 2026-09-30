"""Recuperação de precedentes sobre a collection de chamados.

- vector_search: $vectorSearch puro (usado pelo /api/analisar). queryVector é
  PRÉ-COMPUTADO (Caminho B). Pré-filtro {categoria, status:"resolvido"}.
- hybrid_search: $rankFusion combinando vetorial + Atlas Search full-text (demo
  da força do Atlas). Degrada com graça se o cluster não suportar $rankFusion.

Nada aqui cria índice nem modifica documentos.
"""

import logging

import config
from db import SafeQueryError, catalogo_fotos, chamados, safe_query

logger = logging.getLogger("mm_garantia.rag")

NUM_CANDIDATES = 100
LIMIT = 5
_PROJECT = {"embedding": 0}


def _display_pipeline(pipeline: list[dict]) -> list[dict]:
    """Copy a pipeline for UI disclosure without shipping 1024-float vectors."""
    def compact(value):
        if isinstance(value, dict):
            return {
                key: (f"<{len(item)} floats omitidos>" if key == "queryVector" and isinstance(item, list) else compact(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value

    return compact(pipeline)

# Um threshold absoluto sozinho é frágil aqui: fotos de produto em estúdio
# (fundo branco, mesma iluminação) fazem QUALQUER par de móveis pontuar alto
# no embedding multimodal — a métrica captura "é foto de produto de mobília",
# não a identidade fina do item. Uma cadeira de plástico contra o SKU de uma
# cadeira gamer já pontuou 0.83, perigosamente perto do range "mesmo produto"
# (~0.92-0.94) medido antes. Por isso o sinal principal agora é RELATIVO: o
# SKU reivindicado precisa ser o melhor match entre TODOS os SKUs do catálogo
# (ou empatar dentro de uma margem pequena) — não basta "parecido o bastante"
# no vácuo. O piso absoluto abaixo é só um backstop pro caso raro de o produto
# não ter nenhum parente próximo no catálogo (nem o certo, nem nenhum outro).
IDENTIDADE_THRESHOLD = 0.80
IDENTIDADE_MARGEM_EMPATE = 0.01


async def vector_search(query_vector: list[float], categoria: str) -> tuple[list[dict], dict]:
    """Retorna (docs, funnel). funnel carrega os números de cada estágio para o
    PipelineSteps.jsx mostrar o afunilamento candidatos → contexto."""
    pipeline = [
        {
            "$vectorSearch": {
                "index": config.VECTOR_INDEX,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": NUM_CANDIDATES,
                "limit": LIMIT,
                "filter": {"categoria": categoria, "status": "resolvido"},
            }
        },
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$project": _PROJECT},
    ]
    cursor = chamados().aggregate(pipeline, maxTimeMS=config.MAX_TIME_MS)
    docs = await safe_query(cursor.to_list(length=LIMIT))
    for d in docs:
        d["_id"] = str(d["_id"])
    funnel = {
        "modo": "vector",
        "num_candidates": NUM_CANDIDATES,
        "limit": LIMIT,
        "filtro": {"categoria": categoria, "status": "resolvido"},
        "retrieved": len(docs),
        "query_details": {"operation": "aggregate", "pipeline": _display_pipeline(pipeline)},
    }
    return docs, funnel


async def verificar_identidade(query_vector: list[float], sku: str, categoria: str | None = None) -> dict:
    """$vectorSearch da foto do cliente contra TODAS as fotos de referência do
    catálogo (catalogo_fotos, sem filtro de sku) — responde "essa foto é do
    produto certo?", não "tem defeito?" (isso continua sendo papel do Claude
    com o precedente histórico).

    O sinal é RELATIVO: o SKU reivindicado precisa ser o melhor match entre
    todos os SKUs (ou empatar dentro de IDENTIDADE_MARGEM_EMPATE) — comparar
    só contra o próprio SKU não pega o caso de "parece com QUALQUER móvel
    fotografado em estúdio". Um piso absoluto (IDENTIDADE_THRESHOLD) cobre o
    caso do produto não ter parente nenhum no catálogo.

    Retorna {sku, score, top_sku, top_score, fotos_comparadas, abaixo_threshold}.
    Se o catálogo não tem fotos seedadas, retorna score=None (não bloqueia o fluxo).
    """
    pipeline = [
        {
            "$vectorSearch": {
                "index": config.CATALOGO_FOTOS_VECTOR_INDEX,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 150,
                "limit": 30,
            }
        },
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$project": {"embedding": 0}},
    ]
    cursor = catalogo_fotos().aggregate(pipeline, maxTimeMS=config.MAX_TIME_MS)
    docs = await safe_query(cursor.to_list(length=30))
    if not docs:
        return {"sku": sku, "score": None, "top_sku": None, "top_score": None, "fotos_comparadas": 0, "abaixo_threshold": False,
                "query_details": {"operation": "aggregate", "pipeline": _display_pipeline(pipeline)}}

    melhor_por_sku: dict[str, float] = {}
    for d in docs:
        melhor_por_sku[d["sku"]] = max(melhor_por_sku.get(d["sku"], 0.0), d["score"])

    score_sku = melhor_por_sku.get(sku, 0.0)
    top_sku, top_score = max(melhor_por_sku.items(), key=lambda kv: kv[1])

    eh_o_melhor_ou_empate = score_sku >= top_score - IDENTIDADE_MARGEM_EMPATE
    acima_do_piso = score_sku >= IDENTIDADE_THRESHOLD
    aprovado = eh_o_melhor_ou_empate and acima_do_piso
    dentro_da_margem_de_empate = not eh_o_melhor_ou_empate and score_sku >= top_score - (2 * IDENTIDADE_MARGEM_EMPATE)

    # Instrumentação mínima de deriva: IDENTIDADE_THRESHOLD/IDENTIDADE_MARGEM_EMPATE
    # foram calibrados com uma única amostra anedotica (ver comentário acima). Sem
    # isso não há visibilidade se o threshold está certo pra novas categorias/SKUs
    # ao longo do tempo — não é um pipeline de validação, só o sinal cru em log
    # para permitir análise offline futura (ex.: grep de "identidade_metrica" nos
    # logs, ou ingestão numa collection dedicada se o volume justificar).
    if not aprovado or dentro_da_margem_de_empate:
        logger.warning(
            "identidade_metrica abaixo_threshold=%s dentro_margem_empate=%s "
            "score_sku=%.4f top_score=%.4f sku=%s top_sku=%s categoria=%s",
            not aprovado,
            dentro_da_margem_de_empate,
            score_sku,
            top_score,
            sku,
            top_sku,
            categoria,
        )

    return {
        "sku": sku,
        "score": score_sku,
        "top_sku": top_sku,
        "top_score": top_score,
        "fotos_comparadas": len(docs),
        "abaixo_threshold": not aprovado,
        "query_details": {"operation": "aggregate", "pipeline": _display_pipeline(pipeline)},
    }


async def hybrid_search(query_vector: list[float], texto: str, categoria: str) -> tuple[list[dict], dict]:
    """Busca híbrida via $rankFusion (vetorial + full-text BM25), fundindo os dois
    rankings. Cai para vector_search se o cluster não tiver $rankFusion."""
    pipeline = [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "vetorial": [
                            {
                                "$vectorSearch": {
                                    "index": config.VECTOR_INDEX,
                                    "path": "embedding",
                                    "queryVector": query_vector,
                                    "numCandidates": NUM_CANDIDATES,
                                    "limit": LIMIT,
                                    "filter": {"categoria": categoria, "status": "resolvido"},
                                }
                            }
                        ],
                        "textual": [
                            {
                                "$search": {
                                    "index": config.TEXT_INDEX,
                                    "compound": {
                                        "must": [{"text": {"query": texto, "path": ["descricao_cliente", "frase_analise"]}}],
                                        # categoria/status são enums indexados como "token" (exact match),
                                        # não texto analisado — evita falso-positivo/negativo por stemming.
                                        "filter": [
                                            {"equals": {"path": "categoria", "value": categoria}},
                                            {"equals": {"path": "status", "value": "resolvido"}},
                                        ],
                                    },
                                }
                            },
                            {"$limit": LIMIT},
                        ],
                    }
                },
                "combination": {"weights": {"vetorial": 0.7, "textual": 0.3}},
            }
        },
        {"$limit": LIMIT},
        {"$addFields": {"score": {"$meta": "score"}}},
        {"$project": _PROJECT},
    ]
    cursor = chamados().aggregate(pipeline, maxTimeMS=config.MAX_TIME_MS)
    try:
        docs = await safe_query(cursor.to_list(length=LIMIT))
    except SafeQueryError as e:
        # Só degrada pra vetorial quando a causa é ausência de suporte/índice —
        # qualquer outro erro (conexão, timeout) sobe normal pro Banner de erro.
        msg = e.message.lower()
        if e.kind in ("search", "indice") or "rankfusion" in msg or "unrecognized pipeline stage" in msg:
            docs, funnel = await vector_search(query_vector, categoria)
            funnel["modo"] = "vector_fallback"
            funnel["fallback_motivo"] = e.message[:160]
            return docs, funnel
        raise
    for d in docs:
        d["_id"] = str(d["_id"])
    funnel = {
        "modo": "hybrid",
        "limit": LIMIT,
        "num_candidates": NUM_CANDIDATES,
        "retrieved": len(docs),
        "pesos": {"vetorial": 0.7, "textual": 0.3},
        "query_details": {"operation": "aggregate", "pipeline": _display_pipeline(pipeline)},
    }
    return docs, funnel

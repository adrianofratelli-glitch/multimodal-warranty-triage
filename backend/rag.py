"""Recuperação de precedentes sobre a collection de chamados.

- vector_search: $vectorSearch puro (usado pelo /api/analisar). queryVector é
  PRÉ-COMPUTADO (Caminho B). Pré-filtro {categoria, status:"resolvido"}.
- hybrid_search: $rankFusion combinando vetorial + Atlas Search full-text (demo
  da força do Atlas). Degrada com graça se o cluster não suportar $rankFusion.
- Ambos, quando recebem `texto_rerank`, terminam com `$rerank` (Voyage, nativo do
  Atlas) sobre `frase_analise` do top-k. Se o estágio falhar, a mesma consulta roda
  sem rerank e o funnel registra o motivo (ver docs/adr/0004-rerank-precedentes.md).

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

# Regra de identidade ("a foto confere com o produto do pedido?"), medida em
# 2026-11-12 com eval/run_quality.py (matriz 5 fotos de demo x 6 SKUs).
#
# 1. A consulta usa embedding SÓ DA IMAGEM (voyage.embed_imagem). O vetor da
#    busca de precedentes leva a frase do chamado, que inclui o nome do produto
#    reivindicado: medido, esse texto puxa o score para o SKU do pedido e chegou a
#    fazer a foto de uma cadeira "ganhar" como colchão (0,813 x 0,809) e a foto do
#    6 portas "ganhar" como 3 portas (0,8601 x 0,8597). A alegação não pode entrar
#    na evidência.
# 2. Sinal relativo: o SKU do pedido é comparado com o melhor OUTRO SKU do
#    catálogo inteiro (margem = score_pedido - score_concorrente). Fotos de estúdio
#    pontuam alto entre si, então "parecido o bastante" sozinho não serve.
# 3. Decisão (decidir_identidade):
#    - SKU sem foto de referência  -> "sem_referencia" (revisão humana);
#    - margem <= -MARGEM           -> "divergente" (outro SKU claramente melhor);
#    - |margem| < MARGEM           -> "inconclusivo" (empate técnico, tipicamente
#                                     variante da mesma categoria: nunca aprova);
#    - margem >= MARGEM e score < THRESHOLD -> "inconclusivo" (melhor do catálogo,
#                                     mas pouco parecido com tudo);
#    - senão                       -> "aprovado".
# Medido só-imagem: foto certa 0,839-0,912; menor margem legítima +0,035 (3 portas
# contra o 6 portas); maior score de SKU errado 0,823. MARGEM = 0,02 fica abaixo
# da menor margem legítima e o piso 0,80 fica entre o pior acerto e o pior erro
# entre categorias. Amostra pequena (5 fotos): a deriva segue no log
# `identidade_metrica` e no eval semanal.
IDENTIDADE_THRESHOLD = 0.80
IDENTIDADE_MARGEM = 0.02
STATUS_IDENTIDADE = ("aprovado", "inconclusivo", "divergente", "sem_referencia")
# Ordem de severidade para combinar foto principal + fotos extras (a pior vence).
_SEVERIDADE = {"aprovado": 0, "sem_referencia": 1, "inconclusivo": 2, "divergente": 3}


def decidir_identidade(melhor_por_sku: dict[str, float], sku: str, categoria_por_sku: dict[str, str] | None = None) -> dict:
    """Regra pura de identidade sobre o melhor score por SKU (sem Atlas, testável).

    Retorna {status, motivo, score, top_sku, top_score, concorrente_sku,
    concorrente_score, margem}. `score` é None quando o SKU do pedido não tem foto
    de referência no catálogo.
    """
    categoria_por_sku = categoria_por_sku or {}
    top_sku, top_score = (max(melhor_por_sku.items(), key=lambda kv: kv[1]) if melhor_por_sku else (None, None))
    base = {"score": None, "top_sku": top_sku, "top_score": top_score,
            "concorrente_sku": None, "concorrente_score": None, "margem": None}
    if sku not in melhor_por_sku:
        motivo = ("SKU do pedido sem foto de referência no catálogo: não dá para confirmar o produto pela foto. "
                  "Vai para revisão humana.")
        return {**base, "status": "sem_referencia", "motivo": motivo}

    score = melhor_por_sku[sku]
    outros = {k: v for k, v in melhor_por_sku.items() if k != sku}
    if outros:
        conc_sku, conc_score = max(outros.items(), key=lambda kv: kv[1])
        margem = score - conc_score
    else:
        conc_sku, conc_score, margem = None, None, None
    out = {**base, "score": score, "concorrente_sku": conc_sku, "concorrente_score": conc_score, "margem": margem}
    mesma_categoria = conc_sku is not None and categoria_por_sku.get(conc_sku) is not None \
        and categoria_por_sku.get(conc_sku) == categoria_por_sku.get(sku)

    if margem is not None and margem <= -IDENTIDADE_MARGEM:
        return {**out, "status": "divergente",
                "motivo": f"A foto parece mais com {conc_sku} do que com o produto do pedido."}
    if margem is not None and margem < IDENTIDADE_MARGEM:
        alvo = "uma variante da mesma categoria" if mesma_categoria else "outro produto do catálogo"
        return {**out, "status": "inconclusivo",
                "motivo": f"Empate técnico com {conc_sku} ({alvo}): a foto não separa os dois. Revisar."}
    if score < IDENTIDADE_THRESHOLD:
        return {**out, "status": "inconclusivo",
                "motivo": "É o produto mais parecido do catálogo, mas a similaridade é baixa. Revisar."}
    return {**out, "status": "aprovado", "motivo": "A foto confere com o produto do pedido."}


def combinar_identidades(identidades: list[dict]) -> dict:
    """Status mais severo entre foto principal e extras (qualquer foto divergente sinaliza o chamado)."""
    pior = max(identidades, key=lambda i: _SEVERIDADE.get(i.get("status"), 0))
    return {"status": pior.get("status"), "motivo": pior.get("motivo")}


def _estagios_rerank(texto: str, meta_anterior: str) -> list[dict]:
    """Estágios que guardam o score da recuperação e reordenam o top-k com $rerank.

    `$rerank` substitui `$meta: "score"`, então o score anterior vai antes para
    `score_recuperacao`. O estágio falha se `path` faltar em algum documento: o
    `$set` garante string vazia (precedente antigo sem frase_analise).
    """
    return [
        {"$addFields": {"score_recuperacao": {"$meta": meta_anterior}}},
        {"$set": {"frase_analise": {"$ifNull": ["$frase_analise", ""]}}},
        {"$rerank": {"query": {"text": texto}, "path": "frase_analise",
                     "numDocsToRerank": LIMIT, "model": config.RERANK_MODEL}},
        {"$addFields": {"score": {"$meta": "score"}}},
    ]


def _motivo_curto(mensagem: str) -> str:
    """Causa final do erro do servidor, para a UI: o prefixo traz o namespace
    (`<banco>.chamados`), e o nome do banco não deve aparecer na tela da demo."""
    causa = mensagem.rsplit(":: caused by ::", 1)[-1].strip()
    return (causa if causa != mensagem.strip() else mensagem.split(" on namespace")[0]).strip()[:160]


async def _executar(base: list[dict], meta_score: str, texto_rerank: str | None) -> tuple[list[dict], list[dict], dict]:
    """Roda `base` (+ $rerank quando há texto e modelo). Devolve (docs, pipeline, rerank_info).

    Só erro `operacao` (o MongoDB rejeitou a agregação: estágio $rerank desconhecido,
    Voyage fora, cota) degrada: a mesma consulta roda sem rerank e `rerank_info`
    explica. `timeout`, `search`, `indice` e `conexao` sobem sem repetir a consulta
    (infra ou índice ausente: repetir só dobraria a espera; o híbrido trata os dois
    últimos caindo para vetorial).
    """
    sem_rerank = [*base, {"$addFields": {"score": {"$meta": meta_score}}}, {"$project": _PROJECT}]
    if not (texto_rerank and config.RERANK_MODEL):
        docs = await safe_query(chamados().aggregate(sem_rerank, maxTimeMS=config.MAX_TIME_MS).to_list(length=LIMIT))
        return docs, sem_rerank, {"aplicado": False, "motivo": "desligado"}
    com_rerank = [*base, *_estagios_rerank(texto_rerank, meta_score), {"$project": _PROJECT}]
    try:
        docs = await safe_query(chamados().aggregate(com_rerank, maxTimeMS=config.MAX_TIME_MS).to_list(length=LIMIT))
        return docs, com_rerank, {"aplicado": True, "modelo": config.RERANK_MODEL}
    except SafeQueryError as e:
        if e.kind != "operacao":
            raise
        logger.warning("rerank_fallback kind=%s motivo=%s", e.kind, e.message[:300])
        docs = await safe_query(chamados().aggregate(sem_rerank, maxTimeMS=config.MAX_TIME_MS).to_list(length=LIMIT))
        return docs, sem_rerank, {"aplicado": False, "motivo": _motivo_curto(e.message)}


async def vector_search(query_vector: list[float], categoria: str, texto_rerank: str | None = None) -> tuple[list[dict], dict]:
    """Retorna (docs, funnel). funnel carrega os números de cada estágio para o
    PipelineSteps.jsx mostrar o afunilamento candidatos → contexto.

    `texto_rerank` (frase com PII mascarada) liga o $rerank do top-k."""
    base = [
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
    ]
    docs, pipeline, rerank = await _executar(base, "vectorSearchScore", texto_rerank)
    for d in docs:
        d["_id"] = str(d["_id"])
    funnel = {
        "modo": "vector",
        "num_candidates": NUM_CANDIDATES,
        "limit": LIMIT,
        "filtro": {"categoria": categoria, "status": "resolvido"},
        "retrieved": len(docs),
        "rerank": rerank,
        "query_details": {"operation": "aggregate", "pipeline": _display_pipeline(pipeline)},
    }
    return docs, funnel


async def verificar_identidade(query_vector: list[float], sku: str, categoria: str | None = None) -> dict:
    """"Essa foto é do produto do pedido?" ($vectorSearch em catalogo_fotos, sem
    filtro de sku). Não responde "tem defeito?" (papel do Claude com precedentes).

    `query_vector` deve ser o embedding SÓ DA IMAGEM (voyage.embed_imagem): o texto
    do chamado nomeia o produto reivindicado e enviesa o resultado (ver a regra
    acima). Se o SKU do pedido não aparece entre os 30 mais parecidos, uma segunda
    busca filtrada por sku traz o score dele ou confirma que não há referência.

    Retorna {sku, status, motivo, score, top_sku, top_score, concorrente_sku,
    concorrente_score, margem, fotos_comparadas, abaixo_threshold, query_details}.
    `abaixo_threshold` (compatibilidade) = status != "aprovado".
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

    melhor_por_sku: dict[str, float] = {}
    categoria_por_sku: dict[str, str] = {}
    for d in docs:
        melhor_por_sku[d["sku"]] = max(melhor_por_sku.get(d["sku"], 0.0), d["score"])
        if d.get("categoria"):
            categoria_por_sku[d["sku"]] = d["categoria"]

    if docs and sku not in melhor_por_sku:
        filtrado = [
            {**pipeline[0], "$vectorSearch": {**pipeline[0]["$vectorSearch"], "filter": {"sku": sku}, "limit": 1}},
            *pipeline[1:],
        ]
        cur = catalogo_fotos().aggregate(filtrado, maxTimeMS=config.MAX_TIME_MS)
        proprio = await safe_query(cur.to_list(length=1))
        if proprio:
            melhor_por_sku[sku] = proprio[0]["score"]
            if proprio[0].get("categoria"):
                categoria_por_sku[sku] = proprio[0]["categoria"]
    if categoria and sku not in categoria_por_sku:
        categoria_por_sku[sku] = categoria

    decisao = decidir_identidade(melhor_por_sku, sku, categoria_por_sku)
    if not docs:
        decisao["motivo"] = "Catálogo sem fotos de referência: identidade não verificada. Vai para revisão humana."

    # Deriva: todo resultado não aprovado vira WARNING `identidade_metrica`
    # (logger mm_garantia.rag; LOG_JSON=1 para agregar). O eval semanal mede a
    # regra contra o gabarito; o log mostra como ela se comporta em produção.
    if decisao["status"] != "aprovado":
        logger.warning(
            "identidade_metrica status=%s score_sku=%s concorrente_score=%s margem=%s sku=%s concorrente_sku=%s categoria=%s",
            decisao["status"],
            _fmt(decisao["score"]),
            _fmt(decisao["concorrente_score"]),
            _fmt(decisao["margem"]),
            sku,
            decisao["concorrente_sku"],
            categoria,
        )

    return {
        "sku": sku,
        **decisao,
        "fotos_comparadas": len(docs),
        "abaixo_threshold": decisao["status"] != "aprovado",
        "query_details": {"operation": "aggregate", "pipeline": _display_pipeline(pipeline)},
    }


def _fmt(v: float | None) -> str:
    return "None" if v is None else f"{v:.4f}"


async def hybrid_search(
    query_vector: list[float], texto: str, categoria: str, texto_rerank: str | None = None
) -> tuple[list[dict], dict]:
    """Busca híbrida via $rankFusion (vetorial + full-text BM25), fundindo os dois
    rankings. Cai para vector_search se o cluster não tiver $rankFusion.
    `texto_rerank` (frase com PII mascarada) liga o $rerank do top-k."""
    base = [
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
    ]
    try:
        docs, pipeline, rerank = await _executar(base, "score", texto_rerank)
    except SafeQueryError as e:
        # Só degrada pra vetorial quando a causa é ausência de suporte/índice —
        # qualquer outro erro (conexão, timeout) sobe normal pro Banner de erro.
        msg = e.message.lower()
        if e.kind in ("search", "indice") or "rankfusion" in msg or "unrecognized pipeline stage" in msg:
            docs, funnel = await vector_search(query_vector, categoria, texto_rerank)
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
        "rerank": rerank,
        "query_details": {"operation": "aggregate", "pipeline": _display_pipeline(pipeline)},
    }
    return docs, funnel

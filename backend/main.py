"""FastAPI — Análise de Garantia Multimodal.

Fluxo do portal: pedido -> produto -> checklist+descrição -> foto -> análise.
Caminho B: embedding multimodal MANUAL, imagem em storage local (file://),
$vectorSearch com queryVector pré-computado + filtro {categoria, status:resolvido},
veredito do Claude via tool use (sempre revisao_humana=true).

MongoDB como motor: pedidos, catálogo e chamados são collections; lookup e
checklist LEEM do banco (não mais de dicts hardcoded). Erros -> SafeQueryError -> Banner.
"""

import asyncio
import hashlib
import io
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import anthropic
import voyageai.error as voyageai_error
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

import config
import observability
import rag
from db import SafeQueryError, catalogo, chamados, get_client, pedidos, safe_query
from defeitos_catalog import compor_frase, derivar_tipo_defeito
from llm import MODEL, analisar_veredito
from storage import upload_imagem, url_for
from voyage import EMBED_DIM, embed_multimodal
from voyage import MODEL as VOYAGE_MODEL

# Falhas esperadas de rede/API dos provedores (timeout, rate limit, 5xx) — ver
# achado #5: tratadas separadamente de bugs de programação genéricos, pra não
# misturar "provedor lento" com "TypeError no nosso código" no mesmo log/nível.
PROVIDER_TRANSIENT_ERRORS = (
    anthropic.APIError,
    voyageai_error.VoyageError,
    TimeoutError,
    ConnectionError,
    OSError,
)

# Janela de idempotência (achado #1): retries/duplo-clique dentro desse período
# reaproveitam o chamado já criado em vez de reprocessar (LLM+embedding pagos
# de novo). Curta o suficiente para não confundir com uma nova triagem legítima
# do mesmo produto minutos depois.
IDEMPOTENCY_WINDOW_SECONDS = 60

observability.setup_logging()
logger = logging.getLogger("mm_garantia")

app = FastAPI(title="Análise de Garantia Multimodal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5190", "http://127.0.0.1:5190"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _request_observability(request: Request, call_next):
    """request_id on every response + per-route latency/error counters at /api/metrics."""
    request_id = request.headers.get("x-request-id") or uuid4().hex[:16]
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        observability.metrics.observe(request.url.path, 500, (time.perf_counter() - start) * 1000)
        logger.exception("unhandled error request_id=%s path=%s", request_id, request.url.path)
        raise
    elapsed_ms = (time.perf_counter() - start) * 1000
    observability.metrics.observe(request.url.path, response.status_code, elapsed_ms)
    response.headers["X-Request-Id"] = request_id
    return response


@app.get("/api/metrics")
async def api_metrics():
    """In-process counters: requests/errors/latency per route + business counters."""
    return observability.metrics.snapshot()


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    return Response(observability.metrics.prometheus(), media_type="text/plain; version=0.0.4")

# Imagens servidas localmente (PoV). Em prod, trocar storage.py por S3 + CDN.
config.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
app.mount(config.MEDIA_URL_PREFIX, StaticFiles(directory=str(config.MEDIA_ROOT)), name="media")

ALLOWED_MEDIA = {"image/jpeg", "image/jpg", "image/png"}


@app.exception_handler(SafeQueryError)
async def safe_query_handler(_: Request, exc: SafeQueryError):
    return JSONResponse(status_code=503, content={"error": {"kind": exc.kind, "message": exc.message}})


def clean(doc):
    if isinstance(doc, list):
        return [clean(d) for d in doc]
    if isinstance(doc, dict):
        return {k: clean(v) for k, v in doc.items()}
    if isinstance(doc, (ObjectId, datetime)):
        return str(doc)
    return doc


@app.get("/api/health")
async def health():
    await safe_query(get_client().admin.command("ping"))
    col = chamados()
    return {
        "ping": "ok",
        "model": MODEL,
        "embedding_model": VOYAGE_MODEL,
        "embedding_dim": EMBED_DIM,
        "db": config.DB_NAME,
        # Um único $group substitui três count_documents (3 scans → 1).
        "counts": await _counts_por_status(col),
    }


@app.get("/health/live")
async def liveness():
    return {"status": "alive"}


async def _counts_por_status(col) -> dict:
    rows = await safe_query(
        col.aggregate(
            [{"$group": {"_id": "$status", "n": {"$sum": 1}}}],
            maxTimeMS=config.MAX_TIME_MS,
        ).to_list(length=20)
    )
    por_status = {r["_id"]: r["n"] for r in rows}
    return {
        "total": sum(por_status.values()),
        "resolvido": por_status.get("resolvido", 0),
        "em_analise": por_status.get("em_analise", 0),
    }


@app.get("/api/pedidos")
async def listar_pedidos():
    cursor = pedidos().find({}, {"_id": 0}, max_time_ms=config.MAX_TIME_MS).sort("numero_pedido", 1)
    docs = await safe_query(cursor.to_list(length=200))
    return {"pedidos": docs}


class LookupBody(BaseModel):
    numero_pedido: str = Field(..., min_length=1, max_length=80)


@app.post("/api/lookup")
async def lookup(body: LookupBody):
    numero = body.numero_pedido.strip().upper()
    doc = await safe_query(pedidos().find_one({"numero_pedido": numero}, {"_id": 0}, max_time_ms=config.MAX_TIME_MS))
    if not doc:
        disponiveis = await safe_query(
            pedidos().distinct("numero_pedido", maxTimeMS=config.MAX_TIME_MS)
        )
        raise SafeQueryError(
            "config",
            f"Pedido {numero} não encontrado. Tente um de: {', '.join(sorted(disponiveis)) or '(seed pendente)'}.",
        )
    return {"numero_pedido": numero, "produtos": doc["produtos"]}


@app.get("/api/checklist/{categoria}")
async def checklist(categoria: str):
    doc = await safe_query(catalogo().find_one({"categoria": categoria}, {"_id": 0}, max_time_ms=config.MAX_TIME_MS))
    if not doc:
        raise SafeQueryError("config", f"Categoria '{categoria}' sem checklist no catálogo.")
    return {"categoria": categoria, "itens": doc["itens"]}


async def _resolver_produto(numero_pedido: str, sku: str) -> dict:
    doc = await safe_query(pedidos().find_one({"numero_pedido": numero_pedido.strip().upper()}, max_time_ms=config.MAX_TIME_MS))
    for p in (doc or {}).get("produtos", []):
        if p["sku"] == sku:
            return p
    raise SafeQueryError("config", f"SKU {sku} não pertence ao pedido {numero_pedido}.")


async def _tabela_catalogo(categoria: str) -> dict:
    doc = await safe_query(catalogo().find_one({"categoria": categoria}, {"_id": 0}, max_time_ms=config.MAX_TIME_MS))
    return {item["id"]: item["tipo"] for item in (doc or {}).get("itens", [])}


async def _ler_e_normalizar(upload: UploadFile) -> tuple[Image.Image, bytes]:
    """Valida, lê e normaliza um UploadFile para JPEG (mesmo contrato da foto principal)."""
    if upload.content_type not in ALLOWED_MEDIA:
        raise SafeQueryError("imagem", f"Formato '{upload.content_type}' não aceito. Envie JPEG ou PNG.")
    imagem_bytes = await upload.read(config.MAX_IMAGE_BYTES + 1)
    if not imagem_bytes:
        raise SafeQueryError("imagem", "Nenhuma imagem recebida.")
    if len(imagem_bytes) > config.MAX_IMAGE_BYTES:
        mb = config.MAX_IMAGE_BYTES // (1024 * 1024)
        raise SafeQueryError("imagem", f"Imagem maior que o limite de {mb} MB.")
    try:
        source = Image.open(io.BytesIO(imagem_bytes))
        if source.width * source.height > config.MAX_IMAGE_PIXELS:
            raise SafeQueryError(
                "imagem",
                f"Imagem excede o limite de {config.MAX_IMAGE_PIXELS:,} pixels.",
            )
        pil = source.convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise SafeQueryError("imagem", "Arquivo enviado não é uma imagem válida.") from e
    # Normaliza TUDO para JPEG: garante que o media_type bate com os bytes e que o
    # formato é sempre suportado pelo Claude (evita 400 com PNG/WebP/content-type
    # divergente). A mesma imagem normalizada vai pro storage, Voyage e Claude.
    # Thumbnail 1568x1568 primeiro: é o teto que a visão do Claude usa — acima
    # disso a API redimensiona do lado dela cobrando os tokens da imagem cheia.
    pil.thumbnail((1568, 1568))
    _buf = io.BytesIO()
    pil.save(_buf, format="JPEG", quality=90)
    return pil, _buf.getvalue()


def _validar_entrada_analise(
    numero_pedido: str,
    sku: str,
    descricao: str,
    checklist: list[str],
    fotos_extra_itens: list[str],
    tabela: dict[str, str],
) -> tuple[list[str], list[str]]:
    if not numero_pedido.strip() or len(numero_pedido) > 80:
        raise HTTPException(status_code=422, detail="numero_pedido inválido")
    if not sku.strip() or len(sku) > 120:
        raise HTTPException(status_code=422, detail="sku inválido")
    if len(descricao) > config.MAX_DESCRIPTION_CHARS:
        raise HTTPException(status_code=422, detail="descrição excede o limite permitido")
    if len(fotos_extra_itens) > config.MAX_EXTRA_IMAGES:
        raise HTTPException(status_code=422, detail="quantidade de fotos extras excede o limite")

    normalized_checklist = [item.strip() for item in checklist]
    normalized_extra_items = [item.strip() for item in fotos_extra_itens]
    if len(normalized_checklist) != len(set(normalized_checklist)):
        raise HTTPException(status_code=422, detail="checklist contém itens duplicados")
    unknown = set(normalized_checklist) - set(tabela)
    if unknown:
        raise HTTPException(status_code=422, detail="checklist contém item desconhecido")
    if not set(normalized_extra_items).issubset(normalized_checklist):
        raise HTTPException(status_code=422, detail="foto extra deve referenciar um item marcado")
    return normalized_checklist, normalized_extra_items


def _idempotency_hash(imagem_jpeg: bytes, numero_pedido: str, sku: str, checklist: list[str]) -> str:
    """Hash determinístico dos dados de entrada mais estáveis do pedido de análise.

    Calculado no BACKEND (não depende do frontend mandar uma chave) a partir do
    conteúdo binário já normalizado da foto principal + sku/pedido + checklist
    serializado de forma estável (ordenado — checklist já vem sem duplicatas).
    Não inclui fotos extras/descrição: são o "resto" do payload, e um duplo-clique
    ou retry de rede reenvia byte-a-byte o mesmo multipart.
    """
    h = hashlib.sha256()
    h.update(imagem_jpeg)
    h.update(b"|")
    h.update(numero_pedido.strip().upper().encode())
    h.update(b"|")
    h.update(sku.encode())
    h.update(b"|")
    h.update(json.dumps(sorted(checklist)).encode())
    return h.hexdigest()


def _gerar_numero_chamado() -> str:
    return f"CHM-{datetime.now(UTC).year}-{uuid4().hex[:6].upper()}"


async def _inserir_chamado_com_retry(doc: dict, max_tentativas: int = 3) -> str:
    """Insere `doc` em chamados(); em colisão de numero_chamado (achado #7 — 6
    hex chars tem chance baixa mas não nula de colidir), gera outro numero e
    tenta de novo, sem reprocessar o veredito (já está em memória em doc).
    """
    for tentativa in range(max_tentativas):
        try:
            await safe_query(chamados().insert_one(doc))
            return doc["numero_chamado"]
        except SafeQueryError as e:
            if e.kind == "duplicado" and tentativa < max_tentativas - 1:
                logger.warning(
                    "numero_chamado colidiu (tentativa %s/%s), gerando outro", tentativa + 1, max_tentativas
                )
                doc.pop("_id", None)
                doc["numero_chamado"] = _gerar_numero_chamado()
                continue
            raise
    raise SafeQueryError("duplicado", "Não foi possível gerar um numero_chamado único.")


async def _buscar_chamado_idempotente(idempotency_hash: str) -> dict | None:
    limiar = datetime.now(UTC) - timedelta(seconds=IDEMPOTENCY_WINDOW_SECONDS)
    return await safe_query(
        chamados().find_one(
            {"idempotency_hash": idempotency_hash, "created_at": {"$gte": limiar}},
            {"embedding": 0},
            sort=[("created_at", -1)],
            max_time_ms=config.MAX_TIME_MS,
        )
    )


def _resposta_de_chamado_existente(doc: dict) -> dict:
    """Reconstrói o payload de resposta de /api/analisar a partir de um chamado
    já persistido (replay idempotente — achado #1 — ou o próprio doc recém-criado).
    """
    imagem_url = url_for(doc["imagem_cliente_uri"]) if doc.get("imagem_cliente_uri") else None
    return clean({
        "numero_chamado": doc["numero_chamado"],
        "categoria": doc["categoria"],
        "produto": doc["produto"],
        "frase_analise": doc["frase_analise"],
        "imagem_url": imagem_url,
        "fotos_extra": doc.get("fotos_extra", []),
        "veredito": doc["veredito"],
        "identidade": doc.get("identidade_produto"),
        "precedentes": [],
        "funnel": {"modo": "idempotent_replay"},
        "embedding_model": VOYAGE_MODEL,
        "embedding_dim": len(doc["embedding"]) if doc.get("embedding") else EMBED_DIM,
        "idempotent_replay": True,
    })


@app.post("/api/analisar")
async def analisar(
    imagem: UploadFile,
    numero_pedido: str = Form(...),
    sku: str = Form(...),
    descricao: str = Form(""),
    checklist: list[str] = Form(default=[]),
    modo: str = Form("vector"),  # "vector" (padrão) ou "hybrid" ($rankFusion)
    # Fotos extras, uma por item de checklist marcado — cada uma gera seu próprio
    # embedding multimodal (roda verificar_identidade também) e vai junto da foto
    # principal para o Claude no veredito; não é só evidência guardada.
    fotos_extra: list[UploadFile] = File(default=[]),
    fotos_extra_itens: list[str] = Form(default=[]),
):
    produto = await _resolver_produto(numero_pedido, sku)
    categoria = produto["categoria"]

    if len(fotos_extra) != len(fotos_extra_itens):
        raise HTTPException(status_code=422, detail="Cada foto extra precisa estar associada a exatamente um item do checklist.")

    tabela = await _tabela_catalogo(categoria)
    checklist, fotos_extra_itens = _validar_entrada_analise(
        numero_pedido, sku, descricao, checklist, fotos_extra_itens, tabela
    )
    if modo not in {"vector", "hybrid"}:
        raise HTTPException(status_code=422, detail="modo deve ser vector ou hybrid")

    pil, imagem_jpeg = await _ler_e_normalizar(imagem)
    media_type = "image/jpeg"

    # Achado #1 — idempotência: hash determinístico da entrada mais estável
    # (foto principal normalizada + sku/pedido + checklist). Um duplo-clique ou
    # retry de rede do frontend reenvia o mesmo multipart byte-a-byte, então o
    # hash bate e devolvemos o chamado já criado em vez de pagar LLM+embedding
    # de novo. Janela curta (60s) pra não confundir com uma nova triagem
    # legítima do mesmo produto minutos depois.
    idempotency_hash = _idempotency_hash(imagem_jpeg, numero_pedido, sku, checklist)
    existente = await _buscar_chamado_idempotente(idempotency_hash)
    if existente:
        logger.info(
            "idempotent replay numero_pedido=%s sku=%s numero_chamado=%s",
            numero_pedido, sku, existente["numero_chamado"],
        )
        observability.metrics.bump("analisar_idempotent_replay")
        return _resposta_de_chamado_existente(existente)

    chamado = {
        "categoria": categoria,
        "produto": {"sku": produto["sku"], "nome": produto["nome"]},
        "checklist": checklist,
        "descricao_cliente": descricao,
    }
    frase = compor_frase(chamado)
    numero_chamado = _gerar_numero_chamado()
    key = f"chamados/{numero_chamado}/foto.jpg"
    # Upload em task paralela: não bloqueia o caminho crítico (embedding → RAG →
    # veredito); o resultado só é aguardado na montagem da resposta.
    upload_task = asyncio.create_task(
        run_in_threadpool(upload_imagem, imagem_jpeg, key, media_type)
    )

    extras_normalizadas = [await _ler_e_normalizar(f) for f in fotos_extra]
    extras_upload_tasks = [
        asyncio.create_task(
            run_in_threadpool(
                upload_imagem, jpeg_bytes, f"chamados/{numero_chamado}/extra_{i}_{item}.jpg", media_type
            )
        )
        for i, ((_, jpeg_bytes), item) in enumerate(zip(extras_normalizadas, fotos_extra_itens, strict=True))
    ]

    try:
        query_vector = await run_in_threadpool(embed_multimodal, frase, pil, "query")
    except PROVIDER_TRANSIENT_ERRORS as e:
        upload_task.cancel()
        for t in extras_upload_tasks:
            t.cancel()
        logger.warning("multimodal embedding failed (%s) numero_pedido=%s: %s", type(e).__name__, numero_pedido, str(e)[:200])
        raise SafeQueryError("embedding", f"Falha ao gerar o embedding multimodal: {str(e)[:160]}") from e
    except Exception as e:
        upload_task.cancel()
        for t in extras_upload_tasks:
            t.cancel()
        logger.critical("Unexpected error in multimodal embedding — programming bug suspected numero_pedido=%s", numero_pedido, exc_info=True)
        raise SafeQueryError("embedding", "Falha inesperada ao gerar o embedding multimodal.") from e

    # Embedding de cada foto extra: mesma frase do chamado (o item já está nela
    # via checklist), contrato idêntico ao da foto principal.
    try:
        extras_vetores = await asyncio.gather(
            *(run_in_threadpool(embed_multimodal, frase, extra_pil, "query") for extra_pil, _ in extras_normalizadas)
        )
    except PROVIDER_TRANSIENT_ERRORS as e:
        upload_task.cancel()
        for t in extras_upload_tasks:
            t.cancel()
        logger.warning("multimodal embedding (foto extra) failed (%s) numero_pedido=%s: %s", type(e).__name__, numero_pedido, str(e)[:200])
        raise SafeQueryError("embedding", f"Falha ao gerar o embedding de uma foto extra: {str(e)[:160]}") from e
    except Exception as e:
        upload_task.cancel()
        for t in extras_upload_tasks:
            t.cancel()
        logger.critical("Unexpected error in extra-photo embedding — programming bug suspected numero_pedido=%s", numero_pedido, exc_info=True)
        raise SafeQueryError("embedding", "Falha inesperada ao gerar o embedding de uma foto extra.") from e

    # Identidade e precedentes são consultas independentes sobre o mesmo vetor.
    # Identidade roda pra foto principal E pra cada foto extra — o mais restritivo
    # vence (se qualquer foto divergir do SKU, o chamado inteiro fica sinalizado).
    if modo == "hybrid":
        busca = rag.hybrid_search(query_vector, frase, categoria)
    else:
        busca = rag.vector_search(query_vector, categoria)
    identidade_principal, *identidades_extra, (precedentes, funnel) = await asyncio.gather(
        rag.verificar_identidade(query_vector, produto["sku"], categoria),
        *(rag.verificar_identidade(v, produto["sku"], categoria) for v in extras_vetores),
        busca,
    )
    identidade = {
        **identidade_principal,
        "fotos_extra": [
            {"item": item, **ident}
            for item, ident in zip(fotos_extra_itens, identidades_extra, strict=True)
        ],
        "abaixo_threshold": identidade_principal["abaixo_threshold"] or any(i["abaixo_threshold"] for i in identidades_extra),
    }

    try:
        imagens_extra_veredito = [
            (jpeg_bytes, media_type, item)
            for (_, jpeg_bytes), item in zip(extras_normalizadas, fotos_extra_itens, strict=True)
        ]
        veredito = await analisar_veredito(imagem_jpeg, media_type, frase, precedentes, imagens_extra_veredito)
    except PROVIDER_TRANSIENT_ERRORS as e:
        upload_task.cancel()
        for t in extras_upload_tasks:
            t.cancel()
        logger.warning("Claude verdict call failed (%s) numero_pedido=%s: %s", type(e).__name__, numero_pedido, str(e)[:200])
        raise SafeQueryError("modelo", f"Falha ao consultar o Claude: {str(e)[:160]}") from e
    except Exception as e:
        upload_task.cancel()
        for t in extras_upload_tasks:
            t.cancel()
        logger.critical("Unexpected error calling Claude verdict — programming bug suspected numero_pedido=%s", numero_pedido, exc_info=True)
        raise SafeQueryError("modelo", "Falha inesperada ao consultar o Claude.") from e

    # Achado #2 — a chamada cara ao Claude (paga) já aconteceu nesse ponto.
    # Persistimos o veredito AGORA, num estado intermediário sem depender do
    # upload de imagem terminar. Se o upload falhar depois (disco cheio,
    # storage lento, qualquer transitório) o veredito não se perde — o doc já
    # está gravado e pode ser reconciliado/retomado manualmente depois.
    doc = {
        "numero_chamado": numero_chamado,
        "numero_pedido": numero_pedido.strip().upper(),
        "produto": chamado["produto"],
        "categoria": categoria,
        "tipo_defeito": derivar_tipo_defeito(tabela, checklist),
        "checklist": checklist,
        "descricao_cliente": descricao,
        "frase_analise": frase,
        "imagem_cliente_uri": None,
        "fotos_extra": [],
        "embedding": query_vector,
        "veredito": veredito,
        "identidade_produto": identidade,
        "resolucao_final": None,
        "status": "veredito_pronto_aguardando_upload",
        "idempotency_hash": idempotency_hash,
        "created_at": datetime.now(UTC),
    }
    numero_chamado = await _inserir_chamado_com_retry(doc)

    try:
        uri, imagem_url = await upload_task
        extras_uploads = await asyncio.gather(*extras_upload_tasks)
    except Exception as e:
        # O veredito (já pago) está seguro em `doc` acima — só a foto não
        # terminou de subir. status fica "veredito_pronto_aguardando_upload"
        # em vez de se perder; o chamado pode ser reconciliado depois.
        logger.exception("image upload failed after verdict was persisted numero_chamado=%s", numero_chamado)
        raise SafeQueryError(
            "imagem",
            f"Veredito obtido e preservado (chamado {numero_chamado}), mas falhou ao salvar a imagem: {str(e)[:160]}",
        ) from e

    fotos_extra_doc = [
        {"item": item, "uri": extra_uri, "url": extra_url}
        for item, (extra_uri, extra_url) in zip(fotos_extra_itens, extras_uploads, strict=True)
    ]

    # Reconciliação: agora que o upload terminou, promove o chamado pro estado
    # final normal (mesmo contrato de sempre — status "em_analise").
    await safe_query(
        chamados().update_one(
            {"numero_chamado": numero_chamado},
            {"$set": {
                "imagem_cliente_uri": uri,
                "fotos_extra": fotos_extra_doc,
                "status": "em_analise",
            }},
        )
    )

    return clean({
        "numero_chamado": numero_chamado,
        "categoria": categoria,
        "produto": chamado["produto"],
        "frase_analise": frase,
        "imagem_url": imagem_url,
        "fotos_extra": fotos_extra_doc,
        "veredito": veredito,
        "identidade": identidade,
        "precedentes": [{k: v for k, v in p.items() if k != "embedding"} for p in precedentes],
        "funnel": funnel,
        "embedding_model": VOYAGE_MODEL,
        "embedding_dim": len(query_vector),
    })


@app.get("/api/chamados/pendentes")
async def chamados_pendentes(before_created_at: str | None = None, before_id: str | None = None, limit: int = 50):
    """Fila de revisão, paginada por cursor (achado #3).

    `cursor.to_list(length=50)` sem skip/cursor real deixava os casos mais
    antigos (ordenados created_at desc) permanentemente invisíveis acima de 50
    pendentes. Paginação real por (created_at, _id) — chave estável mesmo com
    created_at empatado — via `before_created_at`/`before_id` (do próximo_cursor
    da página anterior). Sem esses params, retorna a primeira página.
    """
    limit = max(1, min(limit, 100))
    query: dict = {"status": "em_analise"}
    if before_created_at:
        try:
            marco = datetime.fromisoformat(before_created_at)
        except ValueError as e:
            raise HTTPException(status_code=422, detail="before_created_at inválido (use ISO 8601)") from e
        if before_id:
            try:
                marco_id = ObjectId(before_id)
            except InvalidId as e:
                raise HTTPException(status_code=422, detail="before_id inválido") from e
            query["$or"] = [
                {"created_at": {"$lt": marco}},
                {"created_at": marco, "_id": {"$lt": marco_id}},
            ]
        else:
            query["created_at"] = {"$lt": marco}

    cursor = (
        chamados()
        .find(query, {"embedding": 0}, max_time_ms=config.MAX_TIME_MS)
        .sort([("created_at", -1), ("_id", -1)])
    )
    docs = await safe_query(cursor.to_list(length=limit + 1))
    has_more = len(docs) > limit
    docs = docs[:limit]

    next_cursor = None
    if has_more and docs:
        ultimo = docs[-1]
        next_cursor = {"created_at": ultimo["created_at"].isoformat(), "id": str(ultimo["_id"])}

    total_pendentes = (await _counts_por_status(chamados())).get("em_analise", 0)

    return clean({
        "chamados": docs,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "total_pendentes": total_pendentes,
    })


class RevisarBody(BaseModel):
    numero_chamado: str = Field(..., min_length=1, max_length=80)
    resolucao_final: str = Field(..., min_length=1, max_length=2000)
    reviewer: str = Field("demo-user", min_length=1, max_length=120)


@app.post("/api/revisar")
async def revisar(body: RevisarBody):
    res = await safe_query(
        chamados().update_one(
            {"numero_chamado": body.numero_chamado, "status": "em_analise"},
            {"$set": {
                "resolucao_final": body.resolucao_final,
                "status": "resolvido",
                "veredito.revisao_humana": True,
                "reviewer": body.reviewer,
                "revisado_at": datetime.now(UTC),
            }},
        )
    )
    if res.matched_count == 0:
        existing = await safe_query(
            chamados().find_one(
                {"numero_chamado": body.numero_chamado},
                {"_id": 1, "status": 1},
                max_time_ms=config.MAX_TIME_MS,
            )
        )
        if existing:
            raise HTTPException(status_code=409, detail="Chamado já foi revisado.")
        raise HTTPException(status_code=404, detail=f"Chamado {body.numero_chamado} não encontrado.")
    doc = await safe_query(
        chamados().find_one({"numero_chamado": body.numero_chamado}, {"embedding": 0}, max_time_ms=config.MAX_TIME_MS)
    )
    return clean(doc)


@app.get("/api/analytics")
async def analytics():
    """Aggregation Pipeline — material para Atlas Charts: distribuição de
    classificações, confiança média e latência média do modelo, por categoria."""
    col = chamados()
    por_classificacao = await safe_query(col.aggregate([
        {"$group": {
            "_id": "$veredito.classificacao",
            "n": {"$sum": 1},
            "confianca_media": {"$avg": "$veredito.confianca"},
            "latencia_media_ms": {"$avg": "$veredito._meta.latency_ms"},
        }},
        {"$sort": {"n": -1}},
    ], maxTimeMS=config.MAX_TIME_MS).to_list(length=20))

    por_categoria = await safe_query(col.aggregate([
        {"$group": {
            "_id": {"categoria": "$categoria", "classificacao": "$veredito.classificacao"},
            "n": {"$sum": 1},
        }},
        {"$sort": {"_id.categoria": 1, "n": -1}},
    ], maxTimeMS=config.MAX_TIME_MS).to_list(length=100))

    return clean({"por_classificacao": por_classificacao, "por_categoria": por_categoria})


@app.get("/api/chamados/stream")
async def chamados_stream():
    """Change Stream (SSE) — empurra novos chamados em_analise em tempo real,
    sem polling. Demonstra real-time operacional nativo do MongoDB."""

    async def _gen():
        # $project no próprio stream: sem ele cada evento carrega o fullDocument
        # inteiro — incluindo o embedding de 1024 floats — pela rede a cada chamado.
        pipeline = [
            {"$match": {"operationType": {"$in": ["insert", "update", "replace"]}}},
            {"$project": {
                "operationType": 1,
                "fullDocument.numero_chamado": 1,
                "fullDocument.categoria": 1,
                "fullDocument.produto": 1,
                "fullDocument.status": 1,
            }},
        ]
        try:
            async with chamados().watch(pipeline, full_document="updateLookup") as stream:
                yield ": stream conectado\n\n"
                async for change in stream:
                    doc = change.get("fullDocument") or {}
                    if doc.get("status") != "em_analise":
                        continue
                    payload = {
                        "numero_chamado": doc.get("numero_chamado"),
                        "categoria": doc.get("categoria"),
                        "produto": doc.get("produto"),
                        "status": doc.get("status"),
                    }
                    yield f"data: {json.dumps(payload, default=str)}\n\n"
        except Exception as e:  # change streams exigem replica set (Atlas tem)
            logger.exception("change stream failed")
            yield f"event: error\ndata: {json.dumps({'message': str(e)[:200]})}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")

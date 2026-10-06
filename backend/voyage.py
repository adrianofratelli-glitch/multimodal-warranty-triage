"""Embedding multimodal via SDK voyageai (modelo do .env).

Caminho B: NÃO usamos autoEmbed do Atlas (text-only). Computamos o vetor aqui e
gravamos embedding[EMBEDDING_DIM] no documento.

Contrato de consistência: a MESMA função embeda no seed (input_type="document")
e no runtime (input_type="query"). Modelo/dimensão vêm do config (.env).
"""

import os

import voyageai

import config

MODEL = config.EMBEDDING_MODEL
EMBED_DIM = config.EMBEDDING_DIM

_client: voyageai.Client | None = None


def get_client() -> voyageai.Client:
    """Client com timeout e retry explícitos (resiliência por padrão).

    Sem timeout, uma degradação lenta da Voyage trava a thread do
    run_in_threadpool indefinidamente. O SDK repete 429/503/timeout com backoff
    exponencial e jitter (tenacity); atenção: `max_retries` do SDK é o número
    TOTAL de tentativas (stop_after_attempt), por isso o padrão é 3.
    VOYAGE_MAX_RETRIES=1 desliga o retry.
    """
    global _client
    if _client is None:
        _client = voyageai.Client(
            # lê VOYAGE_API_KEY do ambiente (config carregou o .env)
            timeout=float(os.getenv("VOYAGE_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.getenv("VOYAGE_MAX_RETRIES", "3")),
        )
    return _client


def embed_multimodal(frase: str, imagem_pil, input_type: str) -> list[float]:
    """Retorna o vetor para o par (imagem, frase).

    input_type: "document" no seed, "query" no runtime — assimetria recomendada
    pela Voyage para alinhar consultas a documentos indexados.
    """
    result = get_client().multimodal_embed(
        inputs=[[frase, imagem_pil]],
        model=MODEL,
        input_type=input_type,
    )
    return result.embeddings[0]

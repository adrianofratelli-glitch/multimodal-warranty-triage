"""Conexão Atlas + helpers de collection + safe_query.

DB e nomes de collection vêm do config (.env), não mais hardcoded em "POC".
Toda leitura passa por maxTimeMS; erros operacionais viram SafeQueryError com
mensagem pronta para a UI (Banner), nunca um stack trace.
"""

import logging

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import (
    ConnectionFailure,
    DuplicateKeyError,
    ExecutionTimeout,
    NetworkTimeout,
    OperationFailure,
    ServerSelectionTimeoutError,
    WTimeoutError,
)

import config

logger = logging.getLogger("mm_garantia.db")

MAX_TIME_MS = config.MAX_TIME_MS

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        if not config.MONGODB_URI:
            raise SafeQueryError(
                "config",
                "MONGODB_URI não definida. Preencha o .env com a URI do cluster Atlas.",
            )
        _client = AsyncIOMotorClient(
            config.MONGODB_URI,
            serverSelectionTimeoutMS=MAX_TIME_MS,
            connectTimeoutMS=MAX_TIME_MS,
            appname="mm-analise-garantia-poc",
        )
    return _client


def db():
    return get_client()[config.DB_NAME]


def chamados():
    return db()[config.CHAMADOS_COLL]


def catalogo():
    return db()[config.CATALOGO_COLL]


def pedidos():
    return db()[config.PEDIDOS_COLL]


def catalogo_fotos():
    return db()[config.CATALOGO_FOTOS_COLL]


class SafeQueryError(Exception):
    """Erro operacional carregando uma mensagem pronta para a UI."""

    def __init__(self, kind: str, message: str):
        self.kind = kind
        self.message = message
        super().__init__(message)


async def safe_query(awaitable):
    """Await numa operação Motor, mapeando falhas para mensagens amigáveis."""
    try:
        return await awaitable
    except (ExecutionTimeout, NetworkTimeout, WTimeoutError) as e:
        logger.exception("query timeout")
        raise SafeQueryError(
            "timeout",
            "A consulta excedeu o tempo limite (maxTimeMS). O cluster pode estar sob carga — tente novamente.",
        ) from e
    except ServerSelectionTimeoutError as e:
        logger.exception("server selection failed")
        raise SafeQueryError(
            "conexao",
            "Não foi possível alcançar o cluster Atlas. Verifique a MONGODB_URI e o IP Access List.",
        ) from e
    except DuplicateKeyError as e:
        # Subclasse de OperationFailure — precisa vir ANTES do except genérico
        # abaixo, senão cai no branch "Operacao rejeitada" (mensagem genérica)
        # e o chamador perde a chance de tratar a colisão especificamente
        # (ex.: retry com nova chave, sem reprocessar trabalho caro já feito).
        logger.warning("duplicate key on write: %s", str(e)[:200])
        raise SafeQueryError("duplicado", "Chave duplicada ao gravar o documento.") from e
    except OperationFailure as e:
        logger.exception("operation failure")
        msg = str(e).lower()
        if "mongot" in msg or "search index" in msg or "$vectorsearch" in msg:
            raise SafeQueryError(
                "search",
                "O Atlas Search (mongot) está indisponível ou o índice vetorial não foi encontrado. "
                f"Confira o índice '{config.VECTOR_INDEX}' em {config.DB_NAME}.{config.CHAMADOS_COLL}.",
            ) from e
        if "index not found" in msg or "no such index" in msg:
            raise SafeQueryError("indice", "Índice necessário não encontrado nesta collection.") from e
        raise SafeQueryError(
            "operacao",
            f"Operação rejeitada pelo MongoDB: {e.details.get('errmsg', str(e)) if e.details else e}",
        ) from e
    except ConnectionFailure as e:
        logger.exception("connection failure")
        raise SafeQueryError("conexao", "Conexão com o cluster perdida. Tente novamente em alguns segundos.") from e

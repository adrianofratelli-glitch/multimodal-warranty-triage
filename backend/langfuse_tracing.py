"""Langfuse para a triagem (`POST /api/analisar`): uma trace por análise.

Fail-open: sem LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY, sem o pacote ou com o
Langfuse fora do ar, tudo vira no-op e a triagem segue igual. O client é criado
uma vez por processo e só é aceito depois de um `auth_check` bem-sucedido.

PII: quem chama passa SEMPRE texto já mascarado (`guardrails_triagem.mascarar_pii`).
A trace é criada depois da máscara e nunca recebe bytes de imagem nem vetores,
só contagens, scores e o veredito estruturado. Pin `langfuse>=2,<3` (o SDK v3+
mudou a API de trace/span e quebra em silêncio).
"""

import logging
import os

logger = logging.getLogger("mm_garantia.tracing")

_client = None


def _enabled() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def _get_client():
    global _client
    if not _enabled():
        return None
    if _client is None:
        try:
            from langfuse import Langfuse

            candidate = Langfuse()
            if not candidate.auth_check():
                raise RuntimeError("Langfuse auth_check falhou")
            _client = candidate
        except Exception:  # noqa: BLE001 - tracing nunca derruba a triagem
            logger.warning("Langfuse indisponível ou mal configurado; tracing desligado neste processo")
            _client = False
    return _client or None


def start_trace(*, name: str, input_text: str, metadata: dict | None = None, session_id: str | None = None):
    client = _get_client()
    if client is None:
        return None
    try:
        return client.trace(name=name, input=input_text, session_id=session_id, metadata=metadata or {})
    except Exception:  # noqa: BLE001
        logger.warning("falha ao criar trace Langfuse", exc_info=True)
        return None


def log_span(trace, *, name: str, input_data=None, output_data=None, metadata: dict | None = None) -> None:
    if trace is None:
        return
    try:
        trace.span(name=name, input=input_data, output=output_data, metadata=metadata or {})
    except Exception:  # noqa: BLE001
        logger.warning("falha ao logar span no Langfuse", exc_info=True)


def log_generation(trace, *, name: str, model: str, input_text: str, output, usage: dict | None,
                   metadata: dict | None = None) -> None:
    if trace is None:
        return
    try:
        trace.generation(name=name, model=model, input=input_text, output=output,
                         usage=usage, metadata=metadata or {})
    except Exception:  # noqa: BLE001
        logger.warning("falha ao logar generation no Langfuse", exc_info=True)


def finish_trace(trace, *, output=None) -> None:
    if trace is None:
        return
    try:
        trace.update(output=output)
    except Exception:  # noqa: BLE001
        logger.warning("falha ao finalizar trace Langfuse", exc_info=True)


def flush() -> None:
    client = _get_client() if _client else None
    if client is None:
        return
    try:
        client.flush()
    except Exception:  # noqa: BLE001
        logger.warning("falha no flush do Langfuse", exc_info=True)

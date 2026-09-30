"""Anthropic com visão — triagem de garantia via TOOL USE FORÇADO.

Em vez de pedir JSON em texto e dar parse frágil (json.loads + remover cercas
markdown + fallback), forçamos o Claude a chamar a ferramenta `emitir_veredito`.
O SDK devolve `block.input` já como dict validado contra o input_schema — sem
parsing, sem try/except de JSON quebrado.

Nunca é decisão final: revisao_humana sempre True (risco CDC). O modelo é
conservador por design — na dúvida, "inconclusivo". Modelo/limites vêm do config.
"""

import base64
import logging
import os
import time

import anthropic
from anthropic import AsyncAnthropic

import config
import observability

logger = logging.getLogger("mm_garantia.llm")

client = AsyncAnthropic(
    api_key="dummy",  # SDK exige valor não-vazio; auth real vai no header api-key abaixo
    base_url=config.ANTHROPIC_BASE_URL,
    default_headers={"api-key": os.getenv("ANTHROPIC_API_KEY", "")},
    timeout=float(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "45")),
    max_retries=int(os.getenv("ANTHROPIC_MAX_RETRIES", "2")),
)  # Grove/Azure APIM espera header "api-key", não "x-api-key" (o que api_key= geraria)
MODEL = config.ANTHROPIC_MODEL

SYSTEM = """Voce e um analista de triagem de garantia de uma loja online de moveis e itens para casa.
A partir da foto do produto com defeito, da descricao do cliente e de chamados
historicos semelhantes ja resolvidos, classifique a causa PROVAVEL do defeito.

Voce NAO e a decisao final — e uma triagem que sera revisada por um humano.
Seja conservador: na duvida, use "inconclusivo". Uma unica foto raramente prova
sozinha se foi mau uso vs. defeito de transporte vs. defeito de fabrica — so
afirme o que a imagem efetivamente sustenta. Use os precedentes como apoio,
nao como veredito automatico.

Sempre registre o resultado chamando a ferramenta emitir_veredito."""

VEREDITO_TOOL = {
    "name": "emitir_veredito",
    "description": "Registra o veredito estruturado da triagem de garantia.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classificacao": {
                "type": "string",
                "enum": ["defeito_fabrica", "defeito_transporte", "mau_uso", "inconclusivo"],
                "description": "Causa provável do defeito.",
            },
            "confianca": {
                "type": "number",
                "description": "Confiança de 0.0 a 1.0 na classificação.",
            },
            "racional": {"type": "string", "description": "1-2 frases objetivas justificando."},
            "sinais_observados": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Sinais visuais concretos observados na imagem.",
            },
        },
        "required": ["classificacao", "confianca", "racional", "sinais_observados"],
    },
    # Every /api/analisar call sends this same tool schema + SYSTEM below — mark
    # the boundary as cacheable so repeat requests within the demo (5-min TTL)
    # don't re-bill the same ~250 tokens as fresh input every single analysis.
    "cache_control": {"type": "ephemeral"},
}

_FALLBACK = {
    "classificacao": "inconclusivo",
    "confianca": 0.0,
    "racional": (
        "A triagem automática não ficou disponível. O caso foi preservado e "
        "encaminhado para revisão humana sem presumir a causa do defeito."
    ),
    "sinais_observados": [],
}

_CLASSIFICACOES = {"defeito_fabrica", "defeito_transporte", "mau_uso", "inconclusivo"}


def _normalizar_veredito(value, *, meta: dict) -> dict:
    """Enforce the business contract even if the provider returns malformed tool input."""
    veredito = dict(value) if isinstance(value, dict) else dict(_FALLBACK)
    valid_classification = veredito.get("classificacao") in _CLASSIFICACOES
    if not valid_classification:
        veredito["classificacao"] = "inconclusivo"
    try:
        veredito["confianca"] = max(0.0, min(1.0, float(veredito.get("confianca", 0.0))))
    except (TypeError, ValueError):
        veredito["confianca"] = 0.0
    if not valid_classification:
        veredito["confianca"] = 0.0
    racional = veredito.get("racional")
    veredito["racional"] = (
        str(racional).strip()[:1000] if racional else _FALLBACK["racional"]
    )
    sinais = veredito.get("sinais_observados")
    veredito["sinais_observados"] = (
        [str(item).strip()[:300] for item in sinais[:12] if str(item).strip()]
        if isinstance(sinais, list) else []
    )
    veredito["revisao_humana"] = True
    veredito["_meta"] = meta
    return veredito


def _montar_contexto(precedentes: list[dict]) -> str:
    if not precedentes:
        return "(sem precedentes recuperados — base historica ainda fria)"
    linhas = []
    for p in precedentes:
        linhas.append(
            f"- [score {p.get('score', 0):.3f}] "
            f"{p.get('categoria', '?')}/{p.get('tipo_defeito', '?')}: "
            f"\"{p.get('descricao_cliente', p.get('descricao', ''))}\" "
            f"=> resolvido como: {p.get('resolucao_final', '?')}"
        )
    return "\n".join(linhas)


async def analisar_veredito(
    imagem_bytes: bytes,
    media_type: str,
    frase_analise: str,
    precedentes: list[dict],
    imagens_extra: list[tuple[bytes, str, str]] | None = None,
) -> dict:
    """Chama o Claude com visão e tool use forçado; retorna o veredito estruturado.

    `imagens_extra` — fotos adicionais por item de checklist (bytes, media_type,
    rótulo do item), enviadas junto da foto principal para dar mais evidência
    visual ao veredito (não são só guardadas — o Claude efetivamente as vê).
    """
    contexto = _montar_contexto(precedentes)
    b64 = base64.standard_b64encode(imagem_bytes).decode()
    n_extra = len(imagens_extra or [])
    user_text = (
        f"Descricao do chamado:\n{frase_analise}\n\n"
        f"Chamados historicos semelhantes (resolvidos):\n{contexto}\n\n"
        + (f"A primeira imagem é a foto principal do defeito; as {n_extra} seguintes "
           f"são fotos extras relacionadas a itens específicos do checklist.\n\n" if n_extra else "")
        + "Classifique a causa provavel do defeito visivel nas imagens e registre via emitir_veredito."
    )

    content = [{"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}]
    for extra_bytes, extra_media_type, item_label in (imagens_extra or []):
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": extra_media_type, "data": base64.standard_b64encode(extra_bytes).decode()},
        })
        content.append({"type": "text", "text": f"(foto extra acima referente ao item de checklist: {item_label})"})
    content.append({"type": "text", "text": user_text})

    start = time.perf_counter()
    try:
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=config.ANTHROPIC_MAX_TOKENS,
            temperature=0.2,
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=[VEREDITO_TOOL],
            tool_choice={"type": "tool", "name": "emitir_veredito"},
            messages=[{"role": "user", "content": content}],
        )
    except (anthropic.APIError, TimeoutError, ConnectionError, OSError) as e:
        # Falha esperada de rede/API do provedor (timeout, rate limit, 5xx) —
        # transitória por natureza. Log em WARNING é suficiente: não é um bug
        # nosso, é o provedor indisponível/lento.
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.warning(
            "Claude verdict unavailable (%s: %s); preserving case for human review",
            type(e).__name__, str(e)[:200],
        )
        observability.metrics.bump("verdict_manual_review_fallback")
        return _normalizar_veredito(
            _FALLBACK,
            meta={
                "model": MODEL,
                "mode": "manual_review_fallback",
                "latency_ms": latency_ms,
                "precedentes_usados": len(precedentes),
            },
        )
    except Exception:
        # Qualquer outra coisa (TypeError/KeyError/AttributeError internos, bug
        # de programação) NÃO deve ser tratada como "provedor fora do ar" — ainda
        # devolvemos o fallback seguro pro usuário (revisão humana sempre cobre),
        # mas logamos CRITICAL com traceback completo pra diagnosticar de verdade.
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.critical("Unexpected error calling Claude verdict — programming bug suspected", exc_info=True)
        observability.metrics.bump("verdict_manual_review_fallback")
        return _normalizar_veredito(
            _FALLBACK,
            meta={
                "model": MODEL,
                "mode": "manual_review_fallback",
                "latency_ms": latency_ms,
                "precedentes_usados": len(precedentes),
            },
        )
    latency_ms = int((time.perf_counter() - start) * 1000)

    observability.metrics.bump("anthropic_input_tokens", resp.usage.input_tokens)
    observability.metrics.bump("anthropic_output_tokens", resp.usage.output_tokens)
    observability.metrics.bump("anthropic_cache_read_tokens", getattr(resp.usage, "cache_read_input_tokens", 0) or 0)
    observability.metrics.bump("anthropic_cache_write_tokens", getattr(resp.usage, "cache_creation_input_tokens", 0) or 0)

    tool_input = next((b.input for b in resp.content if b.type == "tool_use"), None)
    return _normalizar_veredito(tool_input, meta={
        "model": resp.model,
        "mode": "claude_tool_use",
        "latency_ms": latency_ms,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_read_tokens": getattr(resp.usage, "cache_read_input_tokens", 0),
        "cache_write_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0),
        "precedentes_usados": len(precedentes),
    })

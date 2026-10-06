"""Guardrails da triagem: máscara de PII e detecção de instrução embutida no relato.

Dois usos, ambos baseados em `_shared/guardrails` (pov-shared):

- `mascarar_pii(texto)`: CPF, CNPJ, telefone, e-mail etc. viram `<LABEL>`. É o
  texto que vai para o Claude, para os logs e para o Langfuse. O relato original
  continua no documento do chamado (é o registro de negócio do cliente).
- `avaliar_instrucao(texto)`: o relato do cliente é DADO, nunca instrução. A
  heurística offline (`check_injection`) é aplicada ao texto inteiro E a cada
  cláusula (`score_by_clause`), para que uma ordem curta escondida no meio de um
  relato longo e legítimo (diluição) não passe por ficar com peso pequeno.

Sem pov-shared instalado, os dois viram no-op com aviso no log (fail-open de
observabilidade, mas o veredito continua sempre sob revisão humana).
"""

import logging

from shared_lib import guardrails

logger = logging.getLogger("mm_garantia.guardrails")

# Mesmo threshold binário de antes: qualquer cláusula sinalizada pela heurística
# conta. score_by_clause não muda o limiar, só impede que ele seja diluído.
LIMIAR_INSTRUCAO = 0.5


def mascarar_pii(texto: str) -> str:
    if not texto or guardrails is None:
        return texto or ""
    try:
        return guardrails.mask_pii(texto).text
    except Exception:  # noqa: BLE001 - máscara nunca derruba a triagem
        logger.warning("mask_pii falhou; usando placeholder", exc_info=True)
        return "<texto omitido>"


def _score(clausula: str) -> tuple[float, str]:
    res = guardrails.check_injection(clausula, use_llm=False)
    return (0.0 if res.ok else 1.0), res.reason


def avaliar_instrucao(texto: str) -> dict:
    """Retorna {suspeito, motivo, clausula} sem lançar exceção."""
    if not texto or not texto.strip() or guardrails is None:
        return {"suspeito": False, "motivo": None, "por_clausula": False, "clausula": None}
    try:
        res = guardrails.score_by_clause(texto, _score, max_clauses=8, max_len=300)
    except Exception:  # noqa: BLE001
        logger.warning("score_by_clause falhou; seguindo sem sinal de injeção", exc_info=True)
        return {"suspeito": False, "motivo": None, "por_clausula": False, "clausula": None}
    suspeito = res.score >= LIMIAR_INSTRUCAO
    # Em empate o texto inteiro "vence"; para o revisor, a cláusula culpada é mais útil.
    culpada = next((c for c, s in zip(res.clauses, res.scores, strict=False) if s >= LIMIAR_INSTRUCAO), res.clause)
    return {
        "suspeito": suspeito,
        "motivo": res.payload if suspeito else None,
        "por_clausula": bool(suspeito and res.by_clause),
        "clausula": mascarar_pii(culpada)[:200] if suspeito and culpada else None,
    }

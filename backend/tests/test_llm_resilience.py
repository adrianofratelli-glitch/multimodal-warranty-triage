import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from llm import _normalizar_veredito, analisar_veredito


def test_malformed_tool_output_fails_safe_to_inconclusive():
    result = _normalizar_veredito(
        {
            "classificacao": "culpa_do_cliente",
            "confianca": 42,
            "racional": None,
            "sinais_observados": "não é lista",
        },
        meta={"mode": "test"},
    )

    assert result["classificacao"] == "inconclusivo"
    assert result["confianca"] == 0.0
    assert result["sinais_observados"] == []
    assert result["revisao_humana"] is True


def test_provider_failure_preserves_case_for_human_review():
    fake = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=TimeoutError("offline"))))
    with patch("llm._get_client", return_value=fake):
        result = asyncio.run(
            analisar_veredito(b"jpeg-bytes", "image/jpeg", "produto com avaria", [])
        )

    assert result["classificacao"] == "inconclusivo"
    assert result["confianca"] == 0.0
    assert result["revisao_humana"] is True
    assert result["_meta"]["mode"] == "manual_review_fallback"
    assert "revisão humana" in result["racional"]


def _resp(content):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=content, usage=usage, model="m", stop_reason="end_turn")


def test_text_only_answer_is_explicit_failure_not_verdict():
    # tool_choice=auto (fallback do grove_client p/ modelos que recusam tool_choice
    # forçado): resposta só em texto vira revisão humana com motivo, não veredito.
    texto = _resp([SimpleNamespace(type="text", text="parece defeito de fábrica")])
    fake = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=texto)))
    with patch("llm._get_client", return_value=fake):
        result = asyncio.run(analisar_veredito(b"jpeg-bytes", "image/jpeg", "produto com avaria", []))

    assert result["_meta"]["mode"] == "manual_review_fallback"
    assert result["_meta"]["fallback_motivo"] == "sem_tool_use"
    assert result["classificacao"] == "inconclusivo" and result["confianca"] == 0.0


def test_tool_use_answer_keeps_model_verdict():
    bloco = SimpleNamespace(type="tool_use", input={
        "classificacao": "defeito_transporte", "confianca": 0.7, "racional": "quina amassada",
        "sinais_observados": ["amassado"], "alerta_manipulacao": False})
    fake = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=_resp([bloco]))))
    with patch("llm._get_client", return_value=fake):
        result = asyncio.run(analisar_veredito(b"jpeg-bytes", "image/jpeg", "produto com avaria", []))

    assert result["_meta"]["mode"] == "claude_tool_use"
    assert result["classificacao"] == "defeito_transporte"

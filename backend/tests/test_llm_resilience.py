import asyncio
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
    with patch("llm.client.messages.create", new=AsyncMock(side_effect=TimeoutError("offline"))):
        result = asyncio.run(
            analisar_veredito(b"jpeg-bytes", "image/jpeg", "produto com avaria", [])
        )

    assert result["classificacao"] == "inconclusivo"
    assert result["confianca"] == 0.0
    assert result["revisao_humana"] is True
    assert result["_meta"]["mode"] == "manual_review_fallback"
    assert "revisão humana" in result["racional"]

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from main import LookupBody, _validar_entrada_analise

CATALOGO = {"estrutura": "estrutural", "acabamento": "estetico"}


def test_analysis_input_accepts_catalog_items():
    checklist, extras = _validar_entrada_analise(
        "PED-001", "SKU-001", "A peça chegou danificada", ["estrutura"], ["estrutura"], CATALOGO
    )
    assert checklist == ["estrutura"]
    assert extras == ["estrutura"]


def test_lookup_rejects_empty_or_oversized_order_number():
    for value in ("", "P" * 81):
        with pytest.raises(ValidationError):
            LookupBody(numero_pedido=value)


@pytest.mark.parametrize(
    ("checklist", "extras"),
    [(["../../segredo"], []), (["estrutura"], ["../../segredo"]), (["estrutura", "estrutura"], [])],
)
def test_analysis_input_rejects_unknown_or_duplicate_items(checklist, extras):
    with pytest.raises(HTTPException) as exc:
        _validar_entrada_analise("PED-001", "SKU-001", "", checklist, extras, CATALOGO)
    assert exc.value.status_code == 422

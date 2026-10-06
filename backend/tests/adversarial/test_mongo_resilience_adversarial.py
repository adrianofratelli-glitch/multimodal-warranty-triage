"""Queda/erro do Mongo no meio da operação vira erro legível, nunca stack trace (sem Atlas)."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import (
    AutoReconnect,
    ExecutionTimeout,
    NetworkTimeout,
    PyMongoError,
    ServerSelectionTimeoutError,
    WriteError,
)

import main
from db import SafeQueryError, safe_query


async def _falha(exc):
    raise exc


@pytest.mark.parametrize(("exc", "kind"), [
    (AutoReconnect("primary stepped down"), "conexao"),
    (ServerSelectionTimeoutError("no servers"), "conexao"),
    (NetworkTimeout("socket timeout"), "timeout"),
    (ExecutionTimeout("maxTimeMS"), "timeout"),
    (WriteError("Document failed validation", 121, {"errmsg": "Document failed validation"}), "operacao"),
    (PyMongoError("algo novo do driver"), "operacao"),
])
def test_driver_failures_become_readable_errors(exc, kind):
    with pytest.raises(SafeQueryError) as err:
        asyncio.run(safe_query(_falha(exc)))
    assert err.value.kind == kind
    assert "Traceback" not in err.value.message


def test_cluster_down_mid_request_returns_503_with_message(monkeypatch):
    async def caiu(*_a, **_kw):
        raise SafeQueryError("conexao", "Conexão com o cluster perdida. Tente novamente em alguns segundos.")

    monkeypatch.setattr(main, "_resolver_produto", caiu)
    with TestClient(main.app) as client:
        r = client.post("/api/analisar", data={"numero_pedido": "PED-1", "sku": "X"},
                        files={"imagem": ("f.jpg", b"\xff\xd8", "image/jpeg")})
    assert r.status_code == 503
    assert r.json()["error"]["kind"] == "conexao"

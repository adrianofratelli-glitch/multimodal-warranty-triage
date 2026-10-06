"""Entradas hostis na API e concorrência no envio do chamado (sem Atlas, sem rede).

Os acessos ao banco são substituídos por coleções em memória que reproduzem a
semântica que importa aqui: `_id` único (DuplicateKeyError) e update condicional.
"""

import asyncio
import io
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pymongo.errors import DuplicateKeyError

import main
from main import app

PRODUTO = {"sku": "CAD-OFF-PRO", "nome": "Cadeira Office Pro", "categoria": "cadeira"}
TABELA = {"perna_quebrada": "estrutural", "mancha": "estetico"}


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (120, 80, 40)).save(buf, format="JPEG")
    return buf.getvalue()


class _Res:
    def __init__(self, modified=0, deleted=0):
        self.modified_count = modified
        self.deleted_count = deleted


class FakeIdempotencia:
    """Subconjunto de uma coleção Motor: insert/update/delete/find por _id."""

    def __init__(self):
        self.docs = {}

    async def insert_one(self, doc):
        await asyncio.sleep(0)
        if doc["_id"] in self.docs:
            raise DuplicateKeyError("E11000 duplicate key")
        self.docs[doc["_id"]] = dict(doc)

    async def update_one(self, filtro, update):
        doc = self.docs.get(filtro["_id"])
        if doc and doc["created_at"] < filtro["created_at"]["$lt"]:
            doc.update(update["$set"])
            return _Res(modified=1)
        return _Res()

    async def delete_one(self, filtro):
        doc = self.docs.get(filtro["_id"])
        if doc and doc.get("request_id") == filtro.get("request_id"):
            del self.docs[filtro["_id"]]
            return _Res(deleted=1)
        return _Res()

    async def find_one(self, filtro, *_a, **_kw):
        return self.docs.get(filtro["_id"])


@pytest.fixture
def fake_pipeline(monkeypatch):
    store = {"chamados": [], "processados": 0}
    idem = FakeIdempotencia()

    async def resolver(numero_pedido, sku):
        return PRODUTO

    async def tabela(categoria):
        return TABELA

    async def buscar(h):
        return next((c for c in store["chamados"] if c["idempotency_hash"] == h), None)

    async def processar(**kw):
        store["processados"] += 1
        await asyncio.sleep(0.3)  # embedding + busca + LLM simulados
        doc = {
            "numero_chamado": f"CHM-TEST-{store['processados']}", "categoria": "cadeira",
            "produto": {"sku": PRODUTO["sku"], "nome": PRODUTO["nome"]}, "frase_analise": "f",
            "veredito": {"classificacao": "inconclusivo", "confianca": 0.0}, "identidade_produto": None,
            "idempotency_hash": kw["idempotency_hash"], "created_at": datetime.now(UTC),
        }
        store["chamados"].append(doc)
        return {**main._resposta_de_chamado_existente(doc), "idempotent_replay": False}

    monkeypatch.setattr(main, "_resolver_produto", resolver)
    monkeypatch.setattr(main, "_tabela_catalogo", tabela)
    monkeypatch.setattr(main, "_buscar_chamado_idempotente", buscar)
    monkeypatch.setattr(main, "_processar_analise", processar)
    monkeypatch.setattr(main, "_idempotencia", lambda: idem)
    return store, idem


def _form(**over):
    data = {"numero_pedido": "PED-90001", "sku": PRODUTO["sku"], "descricao": "perna quebrada",
            "checklist": ["perna_quebrada"], "modo": "vector"}
    data.update(over)
    return data


async def _post_paralelo(n: int):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        img = _jpeg()

        async def um():
            return await client.post("/api/analisar", data=_form(),
                                     files={"imagem": ("foto.jpg", img, "image/jpeg")})
        return await asyncio.gather(*(um() for _ in range(n)))


def test_concurrent_identical_submissions_process_once(fake_pipeline):
    store, idem = fake_pipeline
    respostas = asyncio.run(_post_paralelo(5))

    assert [r.status_code for r in respostas] == [200] * 5
    assert store["processados"] == 1, "embedding + LLM pagos uma única vez"
    assert len({r.json()["numero_chamado"] for r in respostas}) == 1
    assert sum(1 for r in respostas if r.json().get("idempotent_replay")) == 4
    assert idem.docs == {}, "a trava é liberada ao fim"


def test_failed_processing_releases_lock_for_retry(fake_pipeline, monkeypatch):
    store, idem = fake_pipeline
    original = main._processar_analise

    async def falha(**kw):
        raise main.SafeQueryError("embedding", "Voyage fora")

    monkeypatch.setattr(main, "_processar_analise", falha)
    with TestClient(app) as client:
        r1 = client.post("/api/analisar", data=_form(), files={"imagem": ("f.jpg", _jpeg(), "image/jpeg")})
        assert r1.status_code == 503
        assert idem.docs == {}
        monkeypatch.setattr(main, "_processar_analise", original)
        r2 = client.post("/api/analisar", data=_form(), files={"imagem": ("f.jpg", _jpeg(), "image/jpeg")})
    assert r2.status_code == 200
    assert store["processados"] == 1


@pytest.mark.parametrize(
    "body",
    [{"numero_pedido": {"$gt": ""}}, {"numero_pedido": {"$where": "sleep(1000)"}}, {"numero_pedido": ["PED-1"]},
     {"numero_pedido": ""}, {"numero_pedido": "P" * 1_000_000}, {}],
)
def test_lookup_rejects_operator_injection_and_bad_types(body):
    with TestClient(app) as client:
        r = client.post("/api/lookup", json=body)
    assert r.status_code == 422


def test_lookup_rejects_malformed_json():
    with TestClient(app) as client:
        r = client.post("/api/lookup", content=b'{"numero_pedido": ', headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_revisar_rejects_operator_injection():
    with TestClient(app) as client:
        r = client.post("/api/revisar", json={"numero_chamado": {"$ne": None}, "resolucao_final": "x"})
    assert r.status_code == 422


def test_analisar_rejects_unknown_mode_and_huge_description_before_any_work(fake_pipeline):
    store, _ = fake_pipeline
    with TestClient(app) as client:
        r1 = client.post("/api/analisar", data=_form(modo="$where"), files={"imagem": ("f.jpg", _jpeg(), "image/jpeg")})
        r2 = client.post("/api/analisar", data=_form(descricao="x" * 1_000_000),
                         files={"imagem": ("f.jpg", _jpeg(), "image/jpeg")})
    assert (r1.status_code, r2.status_code) == (422, 422)
    assert store["processados"] == 0


def test_analisar_rejects_traversal_in_extra_photo_item(fake_pipeline):
    with TestClient(app) as client:
        r = client.post(
            "/api/analisar", data=_form(fotos_extra_itens=["../../../etc/passwd"]),
            files=[("imagem", ("f.jpg", _jpeg(), "image/jpeg")), ("fotos_extra", ("x.jpg", _jpeg(), "image/jpeg"))],
        )
    assert r.status_code == 422


def test_non_image_upload_returns_422_not_503(fake_pipeline):
    with TestClient(app) as client:
        r = client.post("/api/analisar", data=_form(), files={"imagem": ("foto.jpg", b"MZ\x90\x00not-an-image", "image/jpeg")})
    assert r.status_code == 422
    assert r.json()["error"]["kind"] == "imagem"


def test_unicode_rtl_zero_width_description_is_accepted(fake_pipeline):
    store, _ = fake_pipeline
    desc = "perna ​quebrada ‮adsrever‬ 🪑💥 ﷽"
    with TestClient(app) as client:
        r = client.post("/api/analisar", data=_form(descricao=desc), files={"imagem": ("f.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200

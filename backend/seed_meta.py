"""Popula as collections operacionais `pedidos` e `catalogo` no MongoDB.

Antes esses dados eram dicts hardcoded no Python (PEDIDOS_MOCK, CATALOGO_DEFEITOS);
agora viram collections — é o coração da tese "MongoDB como motor de todas as
camadas". Idempotente (replace_one upsert).

    python seed_meta.py
"""

import sys
from datetime import UTC, datetime

from pymongo import MongoClient

import config
from defeitos_catalog import CATALOGO_DEFEITOS
from pedidos_data import PEDIDOS_SEED


def main():
    if not config.MONGODB_URI:
        sys.exit("MONGODB_URI não definida — preencha o .env.")
    c = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=10_000)
    c.admin.command("ping")
    db = c[config.DB_NAME]
    now = datetime.now(UTC)

    ped = db[config.PEDIDOS_COLL]
    for numero, produtos in PEDIDOS_SEED.items():
        ped.replace_one(
            {"numero_pedido": numero},
            {"numero_pedido": numero, "produtos": produtos, "created_at": now},
            upsert=True,
        )

    cat = db[config.CATALOGO_COLL]
    for categoria, tabela in CATALOGO_DEFEITOS.items():
        itens = [{"id": k, "tipo": v} for k, v in tabela.items()]
        cat.replace_one(
            {"categoria": categoria},
            {"categoria": categoria, "itens": itens},
            upsert=True,
        )

    print(f"✓ {config.DB_NAME}.{config.PEDIDOS_COLL}: {ped.count_documents({})} pedidos")
    print(f"✓ {config.DB_NAME}.{config.CATALOGO_COLL}: {cat.count_documents({})} categorias")


if __name__ == "__main__":
    main()

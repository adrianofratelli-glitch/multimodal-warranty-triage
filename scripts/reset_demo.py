#!/usr/bin/env python3
"""Recria TODOS os dados da demo, de forma idempotente, num único comando.

    backend/.venv/bin/python scripts/reset_demo.py                         # banco *_test: livre
    ALLOW_DEMO_DB_WRITE=1 backend/.venv/bin/python scripts/reset_demo.py   # banco da demo

O que faz, nesta ordem, só nas coleções desta PoV (o banco pode ser compartilhado
com outras PoVs, cujas coleções não são tocadas):

1. `pedidos` e `catalogo` (seed_meta.py).
2. Remove de `chamados` tudo que não é um dos 15 precedentes do seed (chamados
   abertos ou revisados durante demos) e limpa `idempotencia`. Os arquivos em
   `media/chamados/` NÃO são apagados (ficam órfãos, inofensivos).
3. Os 15 precedentes resolvidos, com imagem e embedding Voyage (seed.py).
4. As fotos de referência do catálogo com embedding (seed_catalogo_fotos.py).
5. Índices regulares, TTL, Vector Search, Atlas Search e $jsonSchema (setup_indexes.py).
6. Espera os índices de busca ficarem READY e valida com um $vectorSearch real.

Recusa qualquer banco que não termine em `_test` sem ALLOW_DEMO_DB_WRITE=1.
Leva de 1 a 3 min (embeddings + build dos índices no Atlas).
"""

import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from demo_guard import exigir_permissao_de_escrita  # noqa: E402

INDEX_TIMEOUT_SECONDS = 600


def _esperar_indices(db) -> None:
    alvos = {
        (config.CHAMADOS_COLL, config.VECTOR_INDEX),
        (config.CHAMADOS_COLL, config.TEXT_INDEX),
        (config.CATALOGO_FOTOS_COLL, config.CATALOGO_FOTOS_VECTOR_INDEX),
    }
    prazo = time.monotonic() + INDEX_TIMEOUT_SECONDS
    while alvos and time.monotonic() < prazo:
        for coll, name in sorted(alvos):
            info = next(iter(db[coll].list_search_indexes(name)), None)
            if info and info.get("status") == "READY" and info.get("queryable", True):
                print(f"  ✓ {coll}.{name} READY")
                alvos.discard((coll, name))
        if alvos:
            time.sleep(5)
    if alvos:
        sys.exit(f"Índices não ficaram READY em {INDEX_TIMEOUT_SECONDS}s: {sorted(alvos)}")


def _validar(db) -> None:
    from seed_data import CHAMADOS_SEED

    ref = db[config.CHAMADOS_COLL].find_one({"numero_chamado": CHAMADOS_SEED[0]["numero_chamado"]})
    pipeline = [
        {"$vectorSearch": {"index": config.VECTOR_INDEX, "path": "embedding", "queryVector": ref["embedding"],
                           "numCandidates": 50, "limit": 3,
                           "filter": {"categoria": ref["categoria"], "status": "resolvido"}}},
        {"$project": {"numero_chamado": 1}},
    ]
    # Índice recém-criado pode levar alguns segundos para refletir os documentos.
    for _ in range(24):
        hits = list(db[config.CHAMADOS_COLL].aggregate(pipeline))
        if hits:
            print(f"  ✓ $vectorSearch devolveu {len(hits)} precedentes ({hits[0]['numero_chamado']} primeiro)")
            return
        time.sleep(5)
    sys.exit("$vectorSearch não devolveu precedentes depois do reset.")


def main() -> None:
    if not config.MONGODB_URI:
        sys.exit("MONGODB_URI não definida — preencha o .env.")
    exigir_permissao_de_escrita("reset_demo.py")

    from pymongo import MongoClient

    import seed
    import seed_catalogo_fotos
    import seed_meta
    import setup_indexes
    from seed_data import CHAMADOS_SEED

    t0 = time.monotonic()
    client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=10_000)
    client.admin.command("ping")
    db = client[config.DB_NAME]
    print(f"▶ reset de {config.DB_NAME} (coleções: {config.PEDIDOS_COLL}, {config.CATALOGO_COLL}, "
          f"{config.CHAMADOS_COLL}, {config.CATALOGO_FOTOS_COLL}, idempotencia)")

    print("1/6 pedidos + catálogo")
    seed_meta.main()

    print("2/6 removendo chamados criados em demos")
    seed_ids = [c["numero_chamado"] for c in CHAMADOS_SEED]
    removidos = db[config.CHAMADOS_COLL].delete_many({"numero_chamado": {"$nin": seed_ids}}).deleted_count
    db["idempotencia"].delete_many({})
    print(f"  ✓ {removidos} chamados de demo removidos (arquivos em media/ preservados)")

    print("3/6 precedentes (embeddings Voyage)")
    seed.main()

    print("4/6 fotos de referência do catálogo (embeddings Voyage)")
    seed_catalogo_fotos.main()

    print("5/6 índices + $jsonSchema")
    setup_indexes.main()

    print("6/6 aguardando índices de busca e validando")
    _esperar_indices(db)
    _validar(db)

    counts = {c: db[c].count_documents({}) for c in
              (config.PEDIDOS_COLL, config.CATALOGO_COLL, config.CHAMADOS_COLL, config.CATALOGO_FOTOS_COLL)}
    print(f"\n✓ reset concluído em {time.monotonic() - t0:.0f}s: {counts}")


if __name__ == "__main__":
    main()

"""Popula `catalogo_fotos` — as fotos de referência de cada SKU, usadas na
verificação de identidade ("essa foto bate com o produto que o cliente comprou?").

Para cada SKU em CATALOGO_PRODUTOS, embeda as N fotos em
<SEED_IMAGES_DIR>/catalogo/<sku>/1.jpg..N.jpg (input_type="document", mesma função
usada em seed.py — contrato de consistência com o embed do runtime).

O repo não vem com fotos de exemplo. Aponte SEED_IMAGES_DIR (.env ou variável de
ambiente) para uma pasta própria com fotos reais do catálogo, ou gere placeholders
com generate_catalogo_placeholders.py.

Idempotente: replace_one(upsert) por (sku, foto_idx). Índice vetorial
(catalogo_fotos_vector_index) é criado por setup_indexes.py.

    python seed_catalogo_fotos.py
"""

import sys
from datetime import UTC, datetime

from PIL import Image
from pymongo import MongoClient

import config
from catalogo_produtos_data import CATALOGO_PRODUTOS
from storage import upload_imagem
from voyage import embed_multimodal

NOW = datetime.now(UTC)
SEED_IMAGES = config.SEED_IMAGES_DIR / "catalogo"


def montar_documento(produto: dict, foto_idx: int) -> dict:
    sku = produto["sku"]
    arquivo = f"{foto_idx}.jpg"
    caminho = SEED_IMAGES / sku / arquivo
    if not caminho.exists():
        sys.exit(
            f"Imagem ausente: {caminho}.\n"
            f"Rode generate_catalogo_placeholders.py para gerar placeholders, "
            f"ou coloque as fotos reais nesse caminho."
        )

    with Image.open(caminho) as img:
        imagem = img.convert("RGB")
        imagem_bytes = caminho.read_bytes()
        uri, _ = upload_imagem(imagem_bytes, f"catalogo/{sku}/{arquivo}", "image/jpeg")
        frase = f"Foto de referência do produto {produto['nome']} ({sku}), sem defeito."
        embedding = embed_multimodal(frase, imagem, input_type="document")

    return {
        "sku": sku,
        "foto_idx": foto_idx,
        "nome": produto["nome"],
        "categoria": produto["categoria"],
        "imagem_uri": uri,
        "embedding": embedding,
        "created_at": NOW,
    }


def main():
    if not config.MONGODB_URI:
        sys.exit("MONGODB_URI não definida — preencha o .env.")
    client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=10_000)
    client.admin.command("ping")
    col = client[config.DB_NAME][config.CATALOGO_FOTOS_COLL]

    total = 0
    for produto in CATALOGO_PRODUTOS:
        for foto_idx in range(1, produto["n_fotos"] + 1):
            doc = montar_documento(produto, foto_idx)
            col.replace_one({"sku": doc["sku"], "foto_idx": doc["foto_idx"]}, doc, upsert=True)
            print(f"  ✓ {doc['sku']} foto {doc['foto_idx']}/{produto['n_fotos']} -> {doc['imagem_uri']}")
            total += 1

    print(f"\nSeed concluído em {config.DB_NAME}.{config.CATALOGO_FOTOS_COLL}:")
    print(f"  total fotos: {col.count_documents({})}")
    print(f"  skus:        {len(col.distinct('sku'))}")
    print("\nAgora rode:  python setup_indexes.py")


if __name__ == "__main__":
    main()

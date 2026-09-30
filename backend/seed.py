"""Popula a collection `chamados` com os 15 chamados resolvidos (precedentes).

Para cada item de CHAMADOS_SEED:
  1. compor_frase()  (IDÊNTICA à do runtime em main.py — contrato de consistência)
  2. grava a imagem em storage local -> imagem_cliente_uri (file://)
  3. embed_multimodal(imagem, frase, input_type="document") -> embedding
  4. insere com tipo_defeito derivado, status="resolvido", created_at

Idempotente: replace_one(upsert) por numero_chamado. Os índices (vetorial, texto,
regulares) são criados pelo setup_indexes.py.

O repo não vem com fotos de exemplo. Aponte SEED_IMAGES_DIR (.env ou variável de
ambiente) para uma pasta com os arquivos referenciados em seed_data.py
(imagem_arquivo), ou gere placeholders com generate_placeholders.py.

    python seed.py
"""

import io
import sys
from datetime import UTC, datetime

from PIL import Image
from pymongo import MongoClient

import config
from defeitos_catalog import CATALOGO_DEFEITOS, compor_frase, derivar_tipo_defeito
from seed_data import CHAMADOS_SEED
from storage import upload_imagem
from voyage import embed_multimodal

NOW = datetime.now(UTC)
SEED_IMAGES = config.SEED_IMAGES_DIR


def montar_documento(item: dict) -> dict:
    frase = compor_frase(item)
    arquivo = item["imagem_arquivo"]
    caminho = SEED_IMAGES / arquivo
    if not caminho.exists():
        sys.exit(
            f"Imagem ausente: {caminho}.\n"
            f"Este repo não vem com fotos de exemplo — aponte SEED_IMAGES_DIR (.env) "
            f"para uma pasta com suas próprias fotos, ou rode "
            f"'python generate_placeholders.py' para gerar placeholders sintéticos."
        )

    with Image.open(caminho) as img:
        imagem = img.convert("RGB")
        # Normaliza para JPEG (mesmo contrato do runtime em main.py): os bytes
        # gravados no storage devem ser exatamente os bytes usados no embedding,
        # não os bytes originais do arquivo (que podem ser PNG/WebP/etc).
        _buf = io.BytesIO()
        imagem.save(_buf, format="JPEG", quality=90)
        imagem_bytes = _buf.getvalue()
        uri, _ = upload_imagem(imagem_bytes, f"seed/{item['numero_chamado']}/{arquivo}", "image/jpeg")
        embedding = embed_multimodal(frase, imagem, input_type="document")

    tabela = CATALOGO_DEFEITOS.get(item["categoria"], {})
    return {
        "numero_chamado": item["numero_chamado"],
        "numero_pedido": item["numero_pedido"],
        "produto": item["produto"],
        "categoria": item["categoria"],
        "tipo_defeito": derivar_tipo_defeito(tabela, item["checklist"]),
        "checklist": item["checklist"],
        "descricao_cliente": item["descricao_cliente"],
        "frase_analise": frase,
        "imagem_cliente_uri": uri,
        "embedding": embedding,
        "veredito": {
            "classificacao": item["resolucao_final"],
            "confianca": 1.0,
            "racional": "Chamado histórico já resolvido (precedente do flywheel).",
            "sinais_observados": [],
            "revisao_humana": True,
        },
        "resolucao_final": item["resolucao_final"],
        "status": "resolvido",
        "created_at": NOW,
    }


def main():
    if not config.MONGODB_URI:
        sys.exit("MONGODB_URI não definida — preencha o .env.")
    client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=10_000)
    client.admin.command("ping")
    col = client[config.DB_NAME][config.CHAMADOS_COLL]

    for item in CHAMADOS_SEED:
        doc = montar_documento(item)
        col.replace_one({"numero_chamado": doc["numero_chamado"]}, doc, upsert=True)
        print(f"  ✓ {doc['numero_chamado']} [{doc['categoria']}/{doc['tipo_defeito']}] -> {doc['imagem_cliente_uri']}")

    print(f"\nSeed concluído em {config.DB_NAME}.{config.CHAMADOS_COLL}:")
    print(f"  total:     {col.count_documents({})}")
    print(f"  resolvido: {col.count_documents({'status': 'resolvido'})}")
    print("\nAgora rode:  python setup_indexes.py")


if __name__ == "__main__":
    main()

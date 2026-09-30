"""Configuração central — tudo parametrizado pelo .env.

Substitui os valores hardcoded espalhados (DB "POC", índice "chamados_vector",
modelo de embedding) por leitura única do .env. O .env é procurado subindo a
árvore de diretórios a partir daqui, então funciona tanto com .env na raiz do
repo quanto dentro de mm-analise-garantia/.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


def _find_env() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        cand = parent / ".env"
        if cand.exists():
            return cand
    return None


_ENV_PATH = _find_env()
if _ENV_PATH:
    load_dotenv(_ENV_PATH)

# --- MongoDB ---
MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB", "analise_garantia")
CHAMADOS_COLL = os.getenv("MONGODB_COLLECTION", "chamados")
CATALOGO_COLL = os.getenv("MONGODB_CATALOGO_COLLECTION", "catalogo")
PEDIDOS_COLL = os.getenv("MONGODB_PEDIDOS_COLLECTION", "pedidos")
CATALOGO_FOTOS_COLL = os.getenv("MONGODB_CATALOGO_FOTOS_COLLECTION", "catalogo_fotos")
VECTOR_INDEX = os.getenv("VECTOR_INDEX_NAME", "defeitos_vector_index")
TEXT_INDEX = os.getenv("TEXT_INDEX_NAME", "chamados_text_index")
CATALOGO_FOTOS_VECTOR_INDEX = os.getenv("CATALOGO_FOTOS_VECTOR_INDEX_NAME", "catalogo_fotos_vector_index")
MAX_TIME_MS = int(os.getenv("MONGODB_MAX_TIME_MS", "10000"))

# --- Embedding (Voyage multimodal) ---
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "voyage-multimodal-3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))

# --- Anthropic (Claude visão) ---
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "1024"))
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL")

# --- Armazenamento de imagens (local no PoV; trocar backend p/ S3 em prod) ---
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(Path(__file__).resolve().parent / "media")))
MEDIA_URL_PREFIX = os.getenv("MEDIA_URL_PREFIX", "/media")
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))  # 10 MB
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", "25000000"))
MAX_EXTRA_IMAGES = int(os.getenv("MAX_EXTRA_IMAGES", "6"))
MAX_DESCRIPTION_CHARS = int(os.getenv("MAX_DESCRIPTION_CHARS", "4000"))

# --- Fotos de seed (fornecidas pelo usuário, não versionadas no repo) ---
# O repo não vem com fotos de exemplo: quem roda o PoV deve apontar SEED_IMAGES_DIR
# para uma pasta própria (mesma estrutura esperada por seed.py/seed_catalogo_fotos.py/
# generate_placeholders*.py). Default abaixo é só uma convenção de nome de pasta.
SEED_IMAGES_DIR = Path(
    os.getenv("SEED_IMAGES_DIR", str(Path(__file__).resolve().parents[1] / "seed_images"))
)

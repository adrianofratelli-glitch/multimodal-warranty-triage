"""Gera fotos sinteticas de referencia do catalogo (N por SKU, sem defeito).

Renders de estudio por codigo, sem nenhum texto de aviso embutido na imagem
(evita que o modelo de visao veja "placeholder" e desconte confianca). Este
repo NAO vem com fotos de exemplo bundladas — troque por fotos reais do
catalogo do cliente assim que disponiveis: mesmo caminho
(<SEED_IMAGES_DIR>/catalogo/<sku>/1.jpg .. N.jpg), depois rode
seed_catalogo_fotos.py.

Uso (a partir de backend/):
    python generate_catalogo_placeholders.py
Gera os arquivos na pasta apontada por SEED_IMAGES_DIR (.env ou variavel de
ambiente; default "../seed_images" relativo a backend/).
"""

import os

from PIL import ImageDraw, ImageFilter

import config
from catalogo_produtos_data import CATALOGO_PRODUTOS
from generate_placeholders import _shadow, _silhueta, _studio_bg

OUT_DIR = str(config.SEED_IMAGES_DIR / "catalogo")
W, H = 800, 600

COR_CATEGORIA = {
    "cadeira":      (52, 58, 64),
    "colchao":      (233, 236, 239),
    "guarda_roupa": (74, 58, 46),
}

# Pequena variacao de angulo/zoom por indice de foto — simula fotos diferentes
# do mesmo produto sem depender de imagens reais.
VARIACAO_BOX = [
    (0.28, 0.12, 0.72, 0.88),
    (0.24, 0.10, 0.76, 0.90),
    (0.32, 0.15, 0.68, 0.85),
    (0.26, 0.08, 0.74, 0.92),
]


def gerar():
    os.makedirs(OUT_DIR, exist_ok=True)
    total = 0

    for p in CATALOGO_PRODUTOS:
        pasta = os.path.join(OUT_DIR, p["sku"])
        os.makedirs(pasta, exist_ok=True)
        cor_base = COR_CATEGORIA.get(p["categoria"], (60, 60, 60))

        for i in range(1, p["n_fotos"] + 1):
            bx0, by0, bx1, by1 = VARIACAO_BOX[(i - 1) % len(VARIACAO_BOX)]
            box = (W * bx0, H * by0, W * bx1, H * by1)

            img = _studio_bg(cor_base)
            img = _shadow(img, box)
            d = ImageDraw.Draw(img)
            _silhueta(d, p["categoria"], box)
            img = img.filter(ImageFilter.GaussianBlur(0.4))

            caminho = os.path.join(pasta, f"{i}.jpg")
            img.save(caminho, "JPEG", quality=88)
            print("ok", os.path.relpath(caminho, OUT_DIR))
            total += 1

    print(f"\n{total} imagens sinteticas em {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    gerar()

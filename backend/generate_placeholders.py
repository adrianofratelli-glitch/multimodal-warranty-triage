"""Gera fotos sinteticas de seed para validar o pipeline end-to-end.

Nao sao fotos reais do produto — sao renders de estudio gerados por codigo
(silhueta do movel + marca de defeito no proprio objeto), sem nenhum texto
de aviso embutido na imagem. Isso evita que o modelo de visao veja um aviso
tipo "placeholder" e desconte confianca por causa disso. Este repo NAO vem
com fotos de exemplo bundladas: use este script so para ter algo rodando
rapido, e troque por fotos reais do catalogo do cliente (mesmos nomes de
arquivo, na pasta apontada por SEED_IMAGES_DIR) assim que disponiveis —
visualmente mais convincente para o cliente final.

Uso (a partir de backend/):
    python generate_placeholders.py
Gera os arquivos na pasta apontada por SEED_IMAGES_DIR (.env ou variavel de
ambiente; default "../seed_images" relativo a backend/) com os nomes
referenciados em seed_data.py.
"""

import os

from PIL import Image, ImageDraw, ImageFilter

import config

try:
    from seed_data import CHAMADOS_SEED
except ImportError as e:
    raise SystemExit("Rode a partir de backend/ (precisa importar seed_data.py).") from e

OUT_DIR = str(config.SEED_IMAGES_DIR)
W, H = 800, 600

# Cor de fundo de estudio por categoria (gradiente sutil, sem texto).
COR_CATEGORIA = {
    "cadeira":      (52, 58, 64),
    "colchao":      (233, 236, 239),
    "guarda_roupa": (74, 58, 46),
}

COR_DEFEITO = {
    "estrutural": (183, 28, 28),
    "funcional":  (198, 100, 20),
    "estetico":   (90, 70, 20),
    "faltante":   (60, 60, 60),
}

ITEM_TIPO = {
    "perna_quebrada": "estrutural", "rodinha_solta": "estrutural", "base_travada": "funcional",
    "pistao_vazando": "funcional", "estofado_rasgado": "estetico", "mancha": "estetico",
    "parafuso_faltando": "faltante", "afundamento": "estrutural", "molas_salientes": "estrutural",
    "rasgo_tecido": "estetico", "costura_solta": "estetico", "odor_forte": "funcional",
    "porta_desalinhada": "funcional", "dobradica_quebrada": "estrutural",
    "painel_lascado": "estrutural", "arranhado": "estetico", "puxador_faltando": "faltante",
}


def _studio_bg(cor_base):
    """Fundo em vinheta radial, imitando ciclorama de estudio fotografico."""
    img = Image.new("RGB", (W, H), cor_base)
    vign = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(vign)
    cx, cy, r = W // 2, int(H * 0.42), int(W * 0.75)
    for i in range(r, 0, -4):
        alpha = int(140 * (1 - i / r))
        d.ellipse([cx - i, cy - i, cx + i, cy + i], fill=alpha)
    vign = vign.filter(ImageFilter.GaussianBlur(60))
    light = Image.new("RGB", (W, H), tuple(min(255, c + 45) for c in cor_base))
    return Image.composite(light, img, vign)


def _shadow(img, box):
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse([x0 - 20, y1 - 15, x1 + 20, y1 + 35], fill=(0, 0, 0, 60))
    return img.filter(ImageFilter.GaussianBlur(0))


def _silhueta(d, categoria, box):
    """Silhueta simples do movel, so com formas geometricas (sem texto)."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    base = (222, 216, 204) if categoria == "colchao" else (120, 92, 60) if categoria == "guarda_roupa" else (90, 96, 102)

    if categoria == "cadeira":
        d.rounded_rectangle([x0 + w * 0.15, y0, x1 - w * 0.15, y0 + h * 0.45], radius=18, fill=base)
        d.rounded_rectangle([x0 + w * 0.1, y0 + h * 0.45, x1 - w * 0.1, y0 + h * 0.55], radius=14, fill=base)
        for lx in (x0 + w * 0.15, x1 - w * 0.2):
            d.rectangle([lx, y0 + h * 0.55, lx + w * 0.05, y1], fill=(50, 50, 50))
    elif categoria == "colchao":
        d.rounded_rectangle([x0, y0 + h * 0.25, x1, y1], radius=22, fill=base)
        for qx in range(int(x0 + w * 0.12), int(x1 - w * 0.05), int(w * 0.14)):
            for qy in range(int(y0 + h * 0.4), int(y1 - h * 0.1), int(h * 0.22)):
                d.ellipse([qx, qy, qx + 6, qy + 6], fill=(190, 184, 170))
    else:  # guarda_roupa
        d.rectangle([x0, y0, x1, y1], fill=base)
        for i in range(1, 3):
            lx = x0 + w * i / 3
            d.line([(lx, y0), (lx, y1)], fill=(60, 44, 30), width=4)
        for i in range(3):
            hx = x0 + w * (i + 0.85) / 3
            d.ellipse([hx, y0 + h * 0.5, hx + 10, y0 + h * 0.5 + 10], fill=(20, 20, 20))
    return box


def _marca_defeito(draw, tipo, box):
    x0, y0, x1, y1 = box
    cor = COR_DEFEITO.get(tipo, (120, 30, 30))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if tipo == "estrutural":
        pts = [(x0, y0), (x0 + (x1 - x0) * 0.3, cy - 10), (x0 + (x1 - x0) * 0.15, cy + 20),
               (x0 + (x1 - x0) * 0.55, cy + 5), (x0 + (x1 - x0) * 0.35, y1)]
        draw.line(pts, fill=cor, width=5, joint="curve")
    elif tipo == "estetico":
        draw.ellipse([cx - 45, cy - 30, cx + 45, cy + 30], fill=(*cor, 160) if len(cor) == 3 else cor)
    elif tipo == "funcional":
        draw.line([(cx, y0 + 10), (cx, y1 - 20)], fill=cor, width=6)
        draw.polygon([(cx - 18, y1 - 40), (cx + 18, y1 - 40), (cx, y1 - 10)], fill=cor)
    else:
        draw.line([(x0 + 10, y0 + 10), (x1 - 10, y1 - 10)], fill=cor, width=6)
        draw.line([(x1 - 10, y0 + 10), (x0 + 10, y1 - 10)], fill=cor, width=6)


def gerar():
    os.makedirs(OUT_DIR, exist_ok=True)

    for c in CHAMADOS_SEED:
        cat = c["categoria"]
        img = _studio_bg(COR_CATEGORIA.get(cat, (60, 60, 60)))
        d = ImageDraw.Draw(img)

        box = (W * 0.28, H * 0.12, W * 0.72, H * 0.88)
        img = _shadow(img, box)
        d = ImageDraw.Draw(img)
        _silhueta(d, cat, box)

        item = c["checklist"][0] if c["checklist"] else ""
        tipo = ITEM_TIPO.get(item, "estetico")
        _marca_defeito(d, tipo, box)

        img = img.filter(ImageFilter.GaussianBlur(0.4))
        caminho = os.path.join(OUT_DIR, c["imagem_arquivo"])
        img.save(caminho, "JPEG", quality=88)
        print("ok", c["imagem_arquivo"])

    print(f"\n{len(CHAMADOS_SEED)} imagens sinteticas em {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    gerar()

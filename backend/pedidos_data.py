"""Pedidos (FONTE DE SEED) — antes era um dict hardcoded em main.py.

seed_pedidos.py grava isto na collection `pedidos`; o runtime (main.py) passa a
LER do MongoDB via /api/lookup. Cobre todos os SKUs presentes no seed de chamados.
"""

PEDIDOS_SEED = {
    "PED-90001": [
        {"sku": "CAD-OFF-PRO", "nome": "Cadeira Office Pro", "categoria": "cadeira"},
        {"sku": "CAD-GAMER-X", "nome": "Cadeira Gamer X", "categoria": "cadeira"},
    ],
    "PED-90002": [
        {"sku": "COL-MOLAS-Q", "nome": "Colchao Molas Ensacadas Queen", "categoria": "colchao"},
        {"sku": "COL-ESPUMA-S", "nome": "Colchao Espuma Solteiro", "categoria": "colchao"},
    ],
    "PED-90003": [
        {"sku": "GR-6PORTAS", "nome": "Guarda-Roupa 6 Portas", "categoria": "guarda_roupa"},
        {"sku": "GR-3PORTAS", "nome": "Guarda-Roupa 3 Portas", "categoria": "guarda_roupa"},
    ],
    "PED-90004": [
        {"sku": "CAD-OFF-PRO", "nome": "Cadeira Office Pro", "categoria": "cadeira"},
        {"sku": "COL-MOLAS-Q", "nome": "Colchao Molas Ensacadas Queen", "categoria": "colchao"},
        {"sku": "GR-6PORTAS", "nome": "Guarda-Roupa 6 Portas", "categoria": "guarda_roupa"},
    ],
}

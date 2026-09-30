"""Fotos de referência do catálogo (FONTE DE SEED) — usadas na verificação de
identidade: "a foto que o cliente subiu é realmente do produto que ele comprou?"

Cada SKU tem suas fotos de referência (ângulos/detalhes diferentes do produto
sem defeito). seed_catalogo_fotos.py embeda cada uma (input_type="document")
e grava em `catalogo_fotos`. Em runtime, a foto do cliente é comparada via
$vectorSearch contra as fotos do SKU do pedido — score baixo = produto
provavelmente errado/divergente, não necessariamente "sem defeito".

Arquivos esperados em <SEED_IMAGES_DIR>/catalogo/<sku>/1.jpg .. N.jpg (numeração
sequencial, sem buracos — n_fotos abaixo tem que bater com o que existe na pasta).
SEED_IMAGES_DIR é configurável via .env/variável de ambiente (ver config.py);
este repo não vem com fotos de exemplo — use a sua própria pasta ou gere
placeholders com generate_catalogo_placeholders.py.
"""

CATALOGO_PRODUTOS = [
    {"sku": "CAD-OFF-PRO", "nome": "Cadeira Office Pro", "categoria": "cadeira", "n_fotos": 3},
    {"sku": "CAD-GAMER-X", "nome": "Cadeira Gamer X", "categoria": "cadeira", "n_fotos": 4},
    {"sku": "COL-MOLAS-Q", "nome": "Colchao Molas Ensacadas Queen", "categoria": "colchao", "n_fotos": 2},
    {"sku": "GR-6PORTAS", "nome": "Guarda-Roupa 6 Portas", "categoria": "guarda_roupa", "n_fotos": 3},
    # SKU distrator — mesma categoria, produto visualmente parecido porem diferente.
    # Existe so para demonstrar que a verificacao de identidade e relativa ao catalogo
    # inteiro (nao um limiar absoluto): uma foto do GR-3PORTAS deve perder para o
    # GR-6PORTAS certo quando o pedido e do GR-6PORTAS, e vice-versa.
    {"sku": "GR-3PORTAS", "nome": "Guarda-Roupa 3 Portas", "categoria": "guarda_roupa", "n_fotos": 2},
]

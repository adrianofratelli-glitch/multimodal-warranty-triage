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

# COL-ESPUMA-S (vendido em PED-90002) nao tem foto de referencia: a identidade dele
# sai "sem_referencia" (revisao humana), nunca "divergente" por falta de foto.
CATALOGO_PRODUTOS = [
    {"sku": "CAD-OFF-PRO", "nome": "Cadeira Office Pro", "categoria": "cadeira", "n_fotos": 3},
    {"sku": "CAD-GAMER-X", "nome": "Cadeira Gamer X", "categoria": "cadeira", "n_fotos": 4},
    {"sku": "COL-MOLAS-Q", "nome": "Colchao Molas Ensacadas Queen", "categoria": "colchao", "n_fotos": 2},
    {"sku": "GR-6PORTAS", "nome": "Guarda-Roupa 6 Portas", "categoria": "guarda_roupa", "n_fotos": 3},
    # SKU distrator — mesma categoria, produto visualmente parecido porem diferente.
    # Existe para mostrar que a identidade e relativa ao catalogo inteiro: o SKU do
    # pedido precisa vencer o melhor OUTRO SKU por IDENTIDADE_MARGEM (rag.py).
    # Medido so com a imagem (2026-11-12): foto do 3 portas -> GR-3PORTAS 0,858 x
    # GR-6PORTAS 0,823; foto do 6 portas -> GR-6PORTAS 0,880 x GR-3PORTAS 0,796.
    # Nos dois sentidos a foto errada sai "divergente"; um empate dentro da margem
    # sairia "inconclusivo" (revisao), nunca "aprovado". Com a frase do chamado no
    # vetor (regra antiga) o nome do SKU reivindicado invertia esse resultado.
    {"sku": "GR-3PORTAS", "nome": "Guarda-Roupa 3 Portas", "categoria": "guarda_roupa", "n_fotos": 2},
]

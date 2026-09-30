"""15 chamados resolvidos sintéticos para o seed de POC.chamados.

Defeitos visualmente distintos por categoria e classificações variadas
(defeito_fabrica / defeito_transporte / mau_uso) — sem 'inconclusivo',
porque precedente bom é precedente confiante.

Cada item referencia um arquivo dentro de SEED_IMAGES_DIR (configurável via .env/
variável de ambiente — ver config.py; este repo não vem com fotos de exemplo, use
a sua própria pasta ou gere placeholders com generate_placeholders.py). O seed.py
deve, para cada chamado: compor a frase (defeitos_catalog.compor_frase), subir a
imagem pro storage, embeddar (imagem + frase) com input_type="document" e inserir
com status="resolvido".
"""

CHAMADOS_SEED = [
    # ---------- CADEIRA ----------
    {"numero_chamado": "CHM-2026-0001", "numero_pedido": "PED-88471", "categoria": "cadeira",
     "produto": {"sku": "CAD-OFF-PRO", "nome": "Cadeira Office Pro"},
     "checklist": ["perna_quebrada"],
     "descricao_cliente": "Perna traseira direita trincada, caixa amassada num canto.",
     "imagem_arquivo": "cad_01.jpg", "resolucao_final": "defeito_transporte"},

    {"numero_chamado": "CHM-2026-0002", "numero_pedido": "PED-88472", "categoria": "cadeira",
     "produto": {"sku": "CAD-OFF-PRO", "nome": "Cadeira Office Pro"},
     "checklist": ["estofado_rasgado"],
     "descricao_cliente": "Rasgo de aproximadamente 5cm no assento apos 3 meses de uso diario.",
     "imagem_arquivo": "cad_02.jpg", "resolucao_final": "mau_uso"},

    {"numero_chamado": "CHM-2026-0003", "numero_pedido": "PED-88473", "categoria": "cadeira",
     "produto": {"sku": "CAD-GAMER-X", "nome": "Cadeira Gamer X"},
     "checklist": ["pistao_vazando"],
     "descricao_cliente": "Afunda sozinha minutos apos sentar, nao segura a altura.",
     "imagem_arquivo": "cad_03.jpg", "resolucao_final": "defeito_fabrica"},

    {"numero_chamado": "CHM-2026-0004", "numero_pedido": "PED-88474", "categoria": "cadeira",
     "produto": {"sku": "CAD-GAMER-X", "nome": "Cadeira Gamer X"},
     "checklist": ["mancha"],
     "descricao_cliente": "Mancha escura de cafe no encosto, aconteceu em casa.",
     "imagem_arquivo": "cad_04.jpg", "resolucao_final": "mau_uso"},

    {"numero_chamado": "CHM-2026-0005", "numero_pedido": "PED-88475", "categoria": "cadeira",
     "produto": {"sku": "CAD-OFF-PRO", "nome": "Cadeira Office Pro"},
     "checklist": ["base_travada"],
     "descricao_cliente": "Base giratoria nao gira, veio travada da fabrica.",
     "imagem_arquivo": "cad_05.jpg", "resolucao_final": "defeito_fabrica"},

    # ---------- COLCHÃO ----------
    {"numero_chamado": "CHM-2026-0006", "numero_pedido": "PED-88476", "categoria": "colchao",
     "produto": {"sku": "COL-MOLAS-Q", "nome": "Colchao Molas Ensacadas Queen"},
     "checklist": ["afundamento"],
     "descricao_cliente": "Afundou no centro em 2 semanas, forma uma cova visivel.",
     "imagem_arquivo": "col_01.jpg", "resolucao_final": "defeito_fabrica"},

    {"numero_chamado": "CHM-2026-0007", "numero_pedido": "PED-88477", "categoria": "colchao",
     "produto": {"sku": "COL-MOLAS-Q", "nome": "Colchao Molas Ensacadas Queen"},
     "checklist": ["mancha"],
     "descricao_cliente": "Mancha amarelada grande no canto, ocorreu durante o uso.",
     "imagem_arquivo": "col_02.jpg", "resolucao_final": "mau_uso"},

    {"numero_chamado": "CHM-2026-0008", "numero_pedido": "PED-88478", "categoria": "colchao",
     "produto": {"sku": "COL-ESPUMA-S", "nome": "Colchao Espuma Solteiro"},
     "checklist": ["rasgo_tecido"],
     "descricao_cliente": "Tecido lateral rasgado, plastico da entrega estava furado.",
     "imagem_arquivo": "col_03.jpg", "resolucao_final": "defeito_transporte"},

    {"numero_chamado": "CHM-2026-0009", "numero_pedido": "PED-88479", "categoria": "colchao",
     "produto": {"sku": "COL-MOLAS-Q", "nome": "Colchao Molas Ensacadas Queen"},
     "checklist": ["molas_salientes"],
     "descricao_cliente": "Molas saltando na superficie, da pra ver e sentir ao deitar.",
     "imagem_arquivo": "col_04.jpg", "resolucao_final": "defeito_fabrica"},

    {"numero_chamado": "CHM-2026-0010", "numero_pedido": "PED-88480", "categoria": "colchao",
     "produto": {"sku": "COL-ESPUMA-S", "nome": "Colchao Espuma Solteiro"},
     "checklist": ["costura_solta"],
     "descricao_cliente": "Costura da borda soltando ja na primeira semana.",
     "imagem_arquivo": "col_05.jpg", "resolucao_final": "defeito_fabrica"},

    # ---------- GUARDA-ROUPA ----------
    {"numero_chamado": "CHM-2026-0011", "numero_pedido": "PED-88481", "categoria": "guarda_roupa",
     "produto": {"sku": "GR-6PORTAS", "nome": "Guarda-Roupa 6 Portas"},
     "checklist": ["porta_desalinhada"],
     "descricao_cliente": "Portas de correr nao alinham, fresta constante desde a montagem.",
     "imagem_arquivo": "gr_01.jpg", "resolucao_final": "defeito_fabrica"},

    {"numero_chamado": "CHM-2026-0012", "numero_pedido": "PED-88482", "categoria": "guarda_roupa",
     "produto": {"sku": "GR-6PORTAS", "nome": "Guarda-Roupa 6 Portas"},
     "checklist": ["arranhado"],
     "descricao_cliente": "Arranhao profundo no painel frontal, caixa chegou rasgada.",
     "imagem_arquivo": "gr_02.jpg", "resolucao_final": "defeito_transporte"},

    {"numero_chamado": "CHM-2026-0013", "numero_pedido": "PED-88483", "categoria": "guarda_roupa",
     "produto": {"sku": "GR-3PORTAS", "nome": "Guarda-Roupa 3 Portas"},
     "checklist": ["dobradica_quebrada"],
     "descricao_cliente": "Dobradica da porta quebrada, caixa com sinais de impacto no transporte.",
     "imagem_arquivo": "gr_03.jpg", "resolucao_final": "defeito_transporte"},

    {"numero_chamado": "CHM-2026-0014", "numero_pedido": "PED-88484", "categoria": "guarda_roupa",
     "produto": {"sku": "GR-3PORTAS", "nome": "Guarda-Roupa 3 Portas"},
     "checklist": ["painel_lascado"],
     "descricao_cliente": "Canto inferior lascado ao tirar da embalagem amassada.",
     "imagem_arquivo": "gr_04.jpg", "resolucao_final": "defeito_transporte"},

    {"numero_chamado": "CHM-2026-0015", "numero_pedido": "PED-88485", "categoria": "guarda_roupa",
     "produto": {"sku": "GR-6PORTAS", "nome": "Guarda-Roupa 6 Portas"},
     "checklist": ["puxador_faltando"],
     "descricao_cliente": "Faltou um puxador no kit, conferi todos os sacos de pecas.",
     "imagem_arquivo": "gr_05.jpg", "resolucao_final": "defeito_fabrica"},
]

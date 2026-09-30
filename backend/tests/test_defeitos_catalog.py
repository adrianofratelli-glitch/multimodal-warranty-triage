from defeitos_catalog import CATALOGO_DEFEITOS, compor_frase, derivar_tipo_defeito


def test_derivar_tipo_defeito_prioriza_estrutural_sobre_estetico():
    tabela = CATALOGO_DEFEITOS["cadeira"]
    tipo = derivar_tipo_defeito(tabela, ["mancha", "perna_quebrada"])
    assert tipo == "estrutural"


def test_derivar_tipo_defeito_ignora_item_desconhecido():
    tabela = CATALOGO_DEFEITOS["cadeira"]
    tipo = derivar_tipo_defeito(tabela, ["item_que_nao_existe"])
    assert tipo == "estetico"


def test_derivar_tipo_defeito_sem_itens_marcados_cai_no_default():
    tabela = CATALOGO_DEFEITOS["colchao"]
    assert derivar_tipo_defeito(tabela, []) == "estetico"


def test_derivar_tipo_defeito_respeita_ordem_de_prioridade():
    tabela = CATALOGO_DEFEITOS["guarda_roupa"]
    # funcional (porta_desalinhada) deve vencer estetico (arranhado)
    tipo = derivar_tipo_defeito(tabela, ["arranhado", "porta_desalinhada"])
    assert tipo == "funcional"


def test_compor_frase_inclui_categoria_produto_checklist_e_descricao():
    chamado = {
        "categoria": "cadeira",
        "produto": {"nome": "Cadeira Office Pro"},
        "checklist": ["perna_quebrada", "mancha"],
        "descricao_cliente": "Chegou quebrada.",
    }
    frase = compor_frase(chamado)
    assert "cadeira" in frase
    assert "Cadeira Office Pro" in frase
    assert "perna_quebrada, mancha" in frase
    assert "Chegou quebrada." in frase


def test_compor_frase_sem_checklist_usa_texto_padrao():
    chamado = {
        "categoria": "colchao",
        "produto": {"nome": "Colchao Queen"},
        "checklist": [],
        "descricao_cliente": "",
    }
    frase = compor_frase(chamado)
    assert "nenhum item marcado" in frase


def test_compor_frase_sem_descricao_cliente_nao_quebra():
    chamado = {
        "categoria": "cadeira",
        "produto": {"nome": "Cadeira Gamer X"},
        "checklist": ["mancha"],
    }
    # descricao_cliente ausente do dict — main.py sempre manda "" mas o
    # helper precisa ser resiliente pra quem chamar fora desse caminho.
    frase = compor_frase(chamado)
    assert frase.endswith("Relato do cliente: ")

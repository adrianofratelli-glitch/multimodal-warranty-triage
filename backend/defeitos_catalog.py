"""Catálogo de defeitos (FONTE DE SEED) + helpers compartilhados.

CATALOGO_DEFEITOS aqui é só a SEMENTE: seed_catalogo.py grava esta tabela na
collection `catalogo` do MongoDB, e o runtime (main.py) passa a LER do banco.
Os helpers compor_frase / derivar_tipo_defeito continuam sendo o contrato de
consistência usado nos dois lados (seed e runtime) — a frase embedada no seed
precisa ser IDÊNTICA à montada no runtime.
"""

CATALOGO_DEFEITOS = {
    "cadeira": {
        "perna_quebrada":    "estrutural",
        "rodinha_solta":     "estrutural",
        "base_travada":      "funcional",
        "pistao_vazando":    "funcional",   # afunda sozinha
        "estofado_rasgado":  "estetico",
        "mancha":            "estetico",
        "parafuso_faltando": "faltante",
    },
    "colchao": {
        "afundamento":     "estrutural",
        "molas_salientes": "estrutural",
        "rasgo_tecido":    "estetico",
        "mancha":          "estetico",
        "costura_solta":   "estetico",
        "odor_forte":      "funcional",
    },
    "guarda_roupa": {
        "porta_desalinhada":  "funcional",
        "dobradica_quebrada": "estrutural",
        "painel_lascado":     "estrutural",
        "arranhado":          "estetico",
        "puxador_faltando":   "faltante",
        "parafuso_faltando":  "faltante",
    },
}

# Prioridade para reduzir os itens marcados a um único tipo_defeito (vira o
# valor de pré-filtro). Estrutural domina funcional, que domina faltante, etc.
_PRIORIDADE = ["estrutural", "funcional", "faltante", "estetico"]


def derivar_tipo_defeito(tabela: dict, marcados: list[str]) -> str:
    """Reduz os itens de checklist marcados a um único tipo_defeito.

    `tabela` é o mapa {id_item: tipo} de uma categoria — vindo de CATALOGO_DEFEITOS
    no seed, ou do documento da collection `catalogo` no runtime.
    """
    tipos = {tabela[m] for m in marcados if m in tabela}
    return next((t for t in _PRIORIDADE if t in tipos), "estetico")


def compor_frase(chamado: dict) -> str:
    """Monta a frase de análise enviada ao embedding multimodal E ao Claude.

    Espera um dict com: categoria, produto{nome}, checklist[], descricao_cliente.
    USAR ESTA FUNÇÃO nos dois lados (seed e runtime) — contrato de consistência.
    """
    itens = ", ".join(chamado.get("checklist", [])) or "nenhum item marcado"
    return (
        f"Categoria: {chamado['categoria']}. "
        f"Produto: {chamado['produto']['nome']}. "
        f"Defeitos marcados: {itens}. "
        f"Relato do cliente: {chamado.get('descricao_cliente', '').strip()}"
    )

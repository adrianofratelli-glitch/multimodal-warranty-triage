# 0002 — Identidade do produto: vetor só da imagem e sinal relativo

- **Status:** aceita (2026-11-12)
- **Onde:** `backend/rag.py` (`verificar_identidade`, `decidir_identidade`, `IDENTIDADE_MARGEM`, `IDENTIDADE_THRESHOLD`), `backend/voyage.py` (`embed_imagem`), eval em `eval/run_quality.py` (seção `identidade`)

## Contexto

"A foto é do produto comprado?" é uma pergunta de imagem. A primeira versão usava o mesmo vetor frase + foto da busca de precedentes e um limiar absoluto. Medido: a frase nomeia o SKU reivindicado e puxa o score para ele (a foto do guarda-roupa 6 portas "ganhava" como 3 portas por 0,8601 x 0,8597), e fotos de estúdio pontuam alto entre si, então limiar absoluto sozinho deixa passar produto errado.

## Decisão

1. Vetor de consulta **só da imagem** (`voyage.embed_imagem`), sem texto do chamado. As referências de `catalogo_fotos` continuam como o seed as grava (`backend/seed_catalogo_fotos.py`): foto + frase neutra "Foto de referência do produto <nome> (<sku>), sem defeito.", com `input_type="document"`. A frase do cliente (a alegação) nunca entra; a assimetria consulta só-imagem × referência foto+nome foi a medida no eval.
2. Sinal **relativo**: score do SKU do pedido menos o do melhor outro SKU do catálogo inteiro (`$vectorSearch` em `catalogo_fotos`, sem filtro de SKU).
3. Regra (`decidir_identidade`): SKU sem foto de referência → `sem_referencia`; margem ≤ −0,02 → `divergente`; |margem| < 0,02 → `inconclusivo` (empate entre variantes nunca aprova); score < 0,80 → `inconclusivo`; senão `aprovado`. Todo resultado vai para revisão humana de qualquer forma.

## Medição

Matriz 5 fotos de demo × 6 SKUs (30 casos), `eval/run_quality.py`: acurácia 1,0, falsa aceitação 0, falsa rejeição 0 (regra anterior: 0,767 / 0,08 / 0). Revalidado em 2026-11-12 após a ADR 0004 (o `$rerank` não toca a identidade): mesmos números.

## Consequências

- Regravar as referências só com a imagem é uma mudança de dataset: só com o eval rodado antes e depois.
- Amostra pequena: mudar limiar ou margem exige rodar o eval; a deriva em produção sai no WARNING `identidade_metrica` (logger `mm_garantia.rag`).
- Um segundo embedding por foto (só imagem) é calculado em paralelo ao da frase; custo Voyage dobra por foto, latência não.
- O embedding mede semelhança visual, não defeito: a causa continua sendo decisão do Claude sobre precedentes.

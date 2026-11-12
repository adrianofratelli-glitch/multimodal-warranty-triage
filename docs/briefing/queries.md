# Queries, Aggregation Pipelines e Índices — MongoDB

> Números de linha podem ficar defasados após mudanças: a fonte atualizada é [MAPA_DO_CODIGO.md](../MAPA_DO_CODIGO.md).

> Todas as queries reais do backend, com arquivo:linha, o que fazem e por quê. Sem dados sensíveis de cliente — os exemplos usam os mesmos placeholders fictícios do seed (SKUs tipo `CAD-GAMER-X`, pedidos tipo `PED-90001`). Arquitetura geral em `architecture.md`.

---

## Coleções

> Além das quatro abaixo, `idempotencia` guarda só reservas efêmeras de envio (query #6b, TTL).

| Coleção | Conteúdo | Validador `$jsonSchema` |
|---|---|---|
| `pedidos` | pedidos e itens (sku, categoria) | sim |
| `catalogo` | checklist de defeito por categoria | não |
| `catalogo_fotos` | fotos de referência por SKU + embedding | não |
| `chamados` | casos: checklist, descrição, imagem, embedding, veredito, identidade, status | sim |

Nomes reais das coleções/índices vêm do `.env` via `backend/config.py` — os nomes abaixo são os defaults.

---

## Queries — `backend/main.py`

### 1. Contagem por status — `_counts_por_status` (`main.py`)

**O que faz:** um único `$group` substitui três `count_documents` separados (total / resolvido / em_analise).

```python
col.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}], maxTimeMS=config.MAX_TIME_MS)
```

**Por que existe:** usado em `/api/health`, que o frontend faz poll a cada 10s (`App.jsx`). Três `count_documents` seriam três scans completos por poll — desperdício visível na fatura do Atlas. Aproveita o índice `status_created`.

### 2. Listar pedidos — `GET /api/pedidos` (`main.py`)

```python
pedidos().find({}, {"_id": 0}, max_time_ms=config.MAX_TIME_MS).sort("numero_pedido", 1)
```

**O que faz:** popula o seletor de pedido no Portal. Projeção exclui `_id` (não usado no frontend).

### 3. Lookup de pedido — `POST /api/lookup` (`main.py`)

```python
pedidos().find_one({"numero_pedido": numero}, {"_id": 0}, max_time_ms=config.MAX_TIME_MS)
# se não encontrar:
pedidos().distinct("numero_pedido", maxTimeMS=config.MAX_TIME_MS)
```

**Por que existe:** se o pedido não existe, a mensagem de erro devolve a lista dos pedidos que *existem* (via `distinct`) — numa demo ao vivo, um número digitado errado já resolve sozinho em vez de virar tentativa e erro na frente do cliente. Usa o índice único `numero_pedido`.

### 4. Checklist por categoria — `GET /api/checklist/{categoria}` e `_tabela_catalogo` (`main.py`)

```python
catalogo().find_one({"categoria": categoria}, {"_id": 0}, max_time_ms=config.MAX_TIME_MS)
```

**Por que existe:** o checklist é lido do banco, não de um dict hardcoded — cada categoria de produto tem seu próprio conjunto de defeitos possíveis. Índice único `categoria`.

### 5. Resolver produto do pedido — `_resolver_produto` (`main.py`)

```python
pedidos().find_one({"numero_pedido": numero_pedido.strip().upper()}, max_time_ms=config.MAX_TIME_MS)
```

**O que faz:** valida que o SKU informado pertence de fato ao pedido informado (evita SKU forjado no request).

### 6. Busca do chamado idempotente — `_buscar_chamado_idempotente` (`main.py`)

```python
chamados().find_one(
    {"idempotency_hash": idempotency_hash, "created_at": {"$gte": limiar}},
    {"embedding": 0},
    sort=[("created_at", -1)],
    max_time_ms=config.MAX_TIME_MS,
)
```

**Por que existe:** antes de pagar LLM+embedding de novo, checa se um chamado com o mesmo hash de entrada (foto+pedido+sku+checklist) já foi criado nos últimos 60s — cobre duplo-clique e retry de rede do frontend. Usa o índice composto `idempotency_hash + created_at`.

### 6b. Reserva atômica do envio — `_reservar_idempotencia` / `_aguardar_chamado_concorrente` (`main.py`)

```python
db()["idempotencia"].insert_one({"_id": idempotency_hash, "created_at": agora,
                                 "expires_at": agora + timedelta(seconds=180), "request_id": rid})
# DuplicateKeyError -> outro envio idêntico está processando; só retoma reserva vencida:
db()["idempotencia"].update_one({"_id": idempotency_hash, "created_at": {"$lt": vencida}},
                                {"$set": {"created_at": agora, "expires_at": ..., "request_id": rid}})
```

**Por que existe:** o `find_one` da query #6 sozinho tem corrida: dois envios simultâneos (duplo clique, duas abas, retry) passavam juntos e os dois pagavam embedding + LLM. O `_id` único é a trava atômica; quem perde espera o chamado aparecer (polling de 0,5 s até `IDEMPOTENCY_WAIT_SECONDS`) e devolve o mesmo `numero_chamado`. A reserva é apagada ao fim (`delete_one` por `_id` + `request_id`) e o índice TTL em `expires_at` limpa a de um processo que morreu no meio. Medido: 5 envios paralelos idênticos → 1 processamento, 4 replays (`tests/adversarial/test_api_adversarial.py`); 3 envios paralelos reais no Atlas → 1 chamado (`test_live_adversarial.py`).

### 7. Insert do chamado, com retry em colisão — `_inserir_chamado_com_retry` (`main.py`)

```python
chamados().insert_one(doc)
```

**Por que existe:** `numero_chamado` (6 hex chars) tem chance baixa mas não nula de colidir. Em `DuplicateKeyError`, gera outro número e tenta de novo (até 3x) sem reprocessar o veredito já pago e em memória.

### 8. Fila de revisão paginada por cursor — `GET /api/chamados/pendentes` (`main.py`)

```python
query = {"status": "em_analise"}
# páginas seguintes:
query["$or"] = [
    {"created_at": {"$lt": marco}},
    {"created_at": marco, "_id": {"$lt": marco_id}},
]
chamados().find(query, {"embedding": 0}, max_time_ms=config.MAX_TIME_MS).sort([("created_at", -1), ("_id", -1)])
```

**Por que existe:** paginação real por `(created_at, _id)` — chave composta estável mesmo com `created_at` empatado. Substitui um `to_list(length=50)` sem `skip`/cursor que escondia permanentemente os casos mais antigos acima de 50 pendentes (achado de auditoria). Usa o índice `status_created`.

### 9. Revisão humana — `POST /api/revisar` (`main.py`)

```python
chamados().update_one(
    {"numero_chamado": body.numero_chamado, "status": "em_analise"},
    {"$set": {
        "resolucao_final": body.resolucao_final,
        "status": "resolvido",
        "veredito.revisao_humana": True,
        "reviewer": body.reviewer,
        "revisado_at": datetime.now(UTC),
    }},
)
```

**Por que existe:** é a transição que torna um chamado elegível como precedente futuro. O `update_one` é **condicionado a `status: "em_analise"`** de propósito — se dois analistas revisarem o mesmo caso quase ao mesmo tempo, o segundo recebe 409 em vez de sobrescrever a decisão do primeiro em silêncio (checa `matched_count == 0` e distingue 404 de 409 depois).

### 10. Analytics — `GET /api/analytics` (`main.py`)

```python
col.aggregate([
    {"$group": {
        "_id": "$veredito.classificacao",
        "n": {"$sum": 1},
        "confianca_media": {"$avg": "$veredito.confianca"},
        "latencia_media_ms": {"$avg": "$veredito._meta.latency_ms"},
    }},
    {"$sort": {"n": -1}},
], maxTimeMS=config.MAX_TIME_MS)

col.aggregate([
    {"$group": {
        "_id": {"categoria": "$categoria", "classificacao": "$veredito.classificacao"},
        "n": {"$sum": 1},
    }},
    {"$sort": {"_id.categoria": 1, "n": -1}},
], maxTimeMS=config.MAX_TIME_MS)
```

**Por que existe:** alimenta Atlas Charts. Depende do `_meta` (modelo, latência, tokens) gravado em cada veredito por `llm.py` — se isso não for gravado na análise, a página de analytics vira estimativa.

### 11. Change Stream da fila ao vivo — `GET /api/chamados/stream` (`main.py`)

```python
pipeline = [
    {"$match": {"operationType": {"$in": ["insert", "update", "replace"]}}},
    {"$project": {
        "operationType": 1,
        "fullDocument.numero_chamado": 1,
        "fullDocument.categoria": 1,
        "fullDocument.produto": 1,
        "fullDocument.status": 1,
    }},
]
chamados().watch(pipeline, full_document="updateLookup")
```

**Por que existe:** fila de revisão em tempo real sem polling, via SSE (`EventSource` no `Revisao.jsx`). O `$project` **dentro** do pipeline do Change Stream é essencial — sem ele, cada evento carregaria o `fullDocument` inteiro pela rede a cada chamado, **incluindo o embedding de 1024 floats**. O evento serve de gatilho (o front rechama `/api/chamados/pendentes`), não de payload — assim a fila fica sempre consistente com o banco mesmo se um evento se perder ou chegar fora de ordem. Requer replica set (Atlas sempre tem).

---

## Queries — `backend/rag.py` (recuperação de precedentes)

### 12. Busca vetorial pura — `vector_search` (`rag.py`, `vector_search` + `_executar`)

```python
pipeline = [
    {"$vectorSearch": {
        "index": config.VECTOR_INDEX,       # defeitos_vector_index
        "path": "embedding",
        "queryVector": query_vector,         # pré-computado (Caminho B, Voyage)
        "numCandidates": 100,
        "limit": 5,
        "filter": {"categoria": categoria, "status": "resolvido"},
    }},
    # com texto_rerank (frase com PII mascarada) e RERANK_MODEL não vazio — ver #14b:
    {"$addFields": {"score_recuperacao": {"$meta": "vectorSearchScore"}}},
    {"$set": {"frase_analise": {"$ifNull": ["$frase_analise", ""]}}},
    {"$rerank": {"query": {"text": frase_mascarada}, "path": "frase_analise",
                 "numDocsToRerank": 5, "model": config.RERANK_MODEL}},   # rerank-2.5-lite
    {"$addFields": {"score": {"$meta": "score"}}},
    {"$project": {"embedding": 0}},
]
# sem rerank: {"$addFields": {"score": {"$meta": "vectorSearchScore"}}} + $project
chamados().aggregate(pipeline, maxTimeMS=config.MAX_TIME_MS)
```

**O que faz:** recupera até 5 chamados históricos semanticamente parecidos, restritos à mesma categoria de produto e já resolvidos (só caso resolvido pode virar precedente — o filtro é aplicado nativamente pelo índice vetorial, não como pós-filtro).

**Por que `queryVector` pré-computado (Caminho B):** o embedding é calculado no backend (Voyage) antes da agregação, não via `$vectorSearch` com texto bruto — o autoEmbed do Atlas é só texto e esta busca usa vetor de imagem + texto (`docs/adr/0003-embedding-na-aplicacao-sem-autoembed.md`).

### 13. Verificação de identidade do produto — `verificar_identidade` (`rag.py`, regra em `decidir_identidade`)

```python
pipeline = [
    {"$vectorSearch": {
        "index": config.CATALOGO_FOTOS_VECTOR_INDEX,  # catalogo_fotos_vector_index
        "path": "embedding",
        "queryVector": ident_vector,   # voyage.embed_imagem: SÓ a imagem, sem a frase
        "numCandidates": 150,
        "limit": 30,
        # SEM filtro de sku — compara contra TODO o catálogo de propósito
    }},
    {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
    {"$project": {"embedding": 0}},
]
catalogo_fotos().aggregate(pipeline, maxTimeMS=config.MAX_TIME_MS)
# só se o SKU do pedido não estiver entre os 30: a mesma busca com "filter": {"sku": sku}, "limit": 1
# (o índice tem sku como campo de filtro). Vazio = SKU sem foto de referência.
```

**O que faz:** responde "essa foto é do produto do pedido?" — separado de "tem defeito?" (papel do Claude). Compara a foto com as fotos de referência de **todos** os SKUs, não só do SKU reivindicado.

**Por que só a imagem:** o vetor da busca de precedentes leva a frase do chamado, que nomeia o produto reivindicado. Medido em 2026-11-12, esse texto puxa o score para o SKU do pedido: a foto do guarda-roupa de 6 portas num pedido do de 3 portas ficava 0,8601 × 0,8597 e a foto de uma cadeira num pedido de colchão chegou a "ganhar" como colchão (0,813 × 0,809). Na identidade a alegação não pode entrar na evidência.

**Por que relativo:** fotos de produto em estúdio pontuam alto entre si (com só a imagem, o pior par de categorias diferentes medido foi 0,73; o de variantes da mesma categoria, 0,823). O SKU do pedido é comparado com o melhor **outro** SKU do catálogo: `margem = score_pedido − score_concorrente`.

| Condição | `status` |
|---|---|
| SKU do pedido sem foto em `catalogo_fotos` | `sem_referencia` (revisão humana; nunca `divergente` por falta de foto) |
| `margem <= −IDENTIDADE_MARGEM` (0,02) | `divergente` |
| `|margem| < 0,02` | `inconclusivo` — empate técnico, típico de variante da mesma categoria; nunca `aprovado` |
| `margem >= 0,02` e `score < IDENTIDADE_THRESHOLD` (0,80) | `inconclusivo` — é o mais parecido, mas pouco parecido com tudo |
| senão | `aprovado` |

A resposta traz `status`, `motivo`, `score`, `concorrente_sku`, `concorrente_score`, `margem`, `top_sku`, `top_score` e `abaixo_threshold` (compatibilidade: `status != "aprovado"`). O chamado guarda também `status_chamado`/`motivo_chamado`, o pior status entre a foto principal e as extras.

**Medição (2026-11-12, `eval/run_quality.py`, gabarito com `_status` validado em 2026-11-12):** matriz completa das 5 fotos de demo versionadas × 6 SKUs (30 casos: 5 legítimos, 4 de variante da mesma categoria, 16 de outra categoria, 5 de SKU sem foto). Foto certa: 0,839–0,912; menor margem legítima +0,035 (foto do 3 portas contra o 6 portas). `IDENTIDADE_MARGEM` = 0,02 fica abaixo dela; o piso 0,80 fica entre o pior acerto (0,839) e o pior SKU de outra categoria (0,73). Resultado: acerto 1,0, falsa aceitação 0, falsa rejeição 0. A regra antiga (frase no vetor, margem de empate 0,01) nos mesmos 30 casos: acerto 0,767, falsa aceitação 0,08 (2 de 25: 6 portas pedido como 3 portas e foto do 3 portas pedida como colchão) e os 5 casos sem foto marcados `divergente`. A amostra é pequena (5 fotos): mudar limiar exige rodar o eval; a deriva em produção aparece no WARNING `identidade_metrica` (status, scores, margem, SKUs).

### 14. Busca híbrida — `hybrid_search` via `$rankFusion` (`rag.py`, `hybrid_search`)

```python
pipeline = [
    {"$rankFusion": {
        "input": {"pipelines": {
            "vetorial": [{"$vectorSearch": {
                "index": config.VECTOR_INDEX,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 100,
                "limit": 5,
                "filter": {"categoria": categoria, "status": "resolvido"},
            }}],
            "textual": [
                {"$search": {
                    "index": config.TEXT_INDEX,   # chamados_text_index
                    "compound": {
                        "must": [{"text": {"query": texto, "path": ["descricao_cliente", "frase_analise"]}}],
                        "filter": [
                            {"equals": {"path": "categoria", "value": categoria}},
                            {"equals": {"path": "status", "value": "resolvido"}},
                        ],
                    },
                }},
                {"$limit": 5},
            ],
        }},
        "combination": {"weights": {"vetorial": 0.7, "textual": 0.3}},
    }},
    {"$limit": 5},
    # + os mesmos estágios de $rerank do #12 (score_recuperacao guarda o RRF)
    {"$project": {"embedding": 0}},
]
```

**O que faz:** funde ranking vetorial (semântico) com ranking full-text BM25 (Atlas Search) numa agregação só, pesos 70/30. É o modo padrão usado pelo Portal na demo (`modo` fixo em `'hybrid'` no `Portal.jsx`).

**Degradação controlada:** se o cluster não suportar `$rankFusion` ou faltar o índice de texto, cai para `vector_search` automaticamente — **mas só quando a causa é ausência de suporte/índice** (`SafeQueryError.kind in ("search", "indice")` ou mensagem contendo "rankfusion"/"unrecognized pipeline stage"). Qualquer outro erro (conexão, timeout) sobe normal para o Banner — um fallback que engolisse erro de infraestrutura transformaria "o cluster está fora" em "os resultados ficaram meio estranhos hoje". Quando cai no fallback, o `funnel` retornado à UI expõe o motivo.

### 14b. `$rerank` dos precedentes (`rag.py`, `_estagios_rerank` e `_executar`)

**O que faz:** reordena o top 5 de #12 ou #14 pela relevância entre a frase do chamado (com PII mascarada, porque o texto sai do cluster para a Voyage) e a `frase_analise` de cada precedente. O score anterior fica em `score_recuperacao`; `score` passa a ser o do reranker (0-1).

**Degradação:** só quando o MongoDB rejeita a agregação com `$rerank` (`SafeQueryError.kind == "operacao"`: estágio desconhecido, Voyage fora, cota) a mesma busca roda sem o estágio e `funnel.rerank = {"aplicado": false, "motivo": ...}`; a UI mostra o aviso com o motivo e o pipeline que de fato rodou. `timeout`, `search`, `indice` e `conexao` sobem sem repetir a consulta (na híbrida, `search`/`indice` seguem para o fallback vetorial de #14). `RERANK_MODEL=` vazio desliga.

**Medição (2026-11-12, `eval/run_quality.py`, 20 consultas, corpus do seed):** recall@1 0,95 → 1,0 e MRR 0,975 → 1,0 em vetor e híbrido (um caso, o R20, subiu de 2º para 1º); +~190 ms p50 na agregação. Detalhe e motivo de não quantizar em `docs/adr/0004-rerank-precedentes.md`.

**Por que `categoria`/`status` são indexados como `token`, não `string`:** são enums — o filtro usa `{"equals": ...}` (exact match). Indexar como texto analisado (`string`) traria falso positivo/negativo por stemming.

---

## Índices — `backend/setup_indexes.py`

### Regulares

| Índice | Coleção | Campos | Motivação |
|---|---|---|---|
| `status_created` | `chamados` | `status` asc, `created_at` desc | Alimenta a fila de revisão paginada (query #8) e `_counts_por_status` (query #1) |
| `numero_chamado` | `chamados` | `numero_chamado` asc | **único** — lookup direto por número de chamado; garante que a colisão de 6 hex chars vire `DuplicateKeyError` tratável |
| `idempotency_hash` | `chamados` | `idempotency_hash` asc, `created_at` desc | Busca rápida da janela de idempotência (query #6). **Não** único — o mesmo hash pode reaparecer legitimamente depois da janela de 60s |
| `numero_pedido` | `pedidos` | `numero_pedido` asc | **único** — lookup de pedido (query #3) |
| `categoria` | `catalogo` | `categoria` asc | **único** — um checklist por categoria (query #4) |
| `sku_foto` | `catalogo_fotos` | `sku` asc, `foto_idx` asc | **único** — evita foto de referência duplicada para o mesmo SKU |
| `ttl_expires_at` | `idempotencia` | `expires_at` (TTL, `expireAfterSeconds=0`) | Limpa reservas de envio órfãs (query #6b); o `_id` (hash) é a trava |

### Vetoriais (Atlas Vector Search)

| Índice | Coleção | Definição |
|---|---|---|
| `defeitos_vector_index` | `chamados` | vetor `embedding` (1024d, cosine) + filtros nativos `categoria`, `status` |
| `catalogo_fotos_vector_index` | `catalogo_fotos` | vetor `embedding` (1024d, cosine) + filtro nativo `sku` |

**Por que `categoria`/`status` são "filter" no índice vetorial, não pós-filtro em memória:** filtro nativo do índice é o que permite ao `$vectorSearch` restringir candidatos antes do ranqueamento, sem precisar buscar mais do que `numCandidates` e filtrar depois em aplicação.

### Atlas Search (full-text)

| Índice | Coleção | Campos mapeados |
|---|---|---|
| `chamados_text_index` | `chamados` | `descricao_cliente` (string, analisado), `frase_analise` (string, analisado), `categoria` (token), `status` (token) |

Necessário para `$rankFusion` — não é opcional, sem ele a busca híbrida (query #14) não funciona.

### Validadores `$jsonSchema`

- **`chamados`** — exige `numero_chamado`, `categoria`, `status` (enum `em_analise`/`resolvido`/`veredito_pronto_aguardando_upload`), `veredito` (com `classificacao` enum, `confianca` 0-1, `revisao_humana` bool) e `embedding` com **exatamente** `EMBEDDING_DIM` doubles — é o que pega na hora o erro clássico de trocar o modelo de embedding e a busca vetorial começar a devolver bobagem em silêncio.
- **`pedidos`** — exige `numero_pedido` e `produtos`.
- Default `validationAction=error`; `warn` só existe via `VALIDATION_ACTION=warn` explícito, para migrar seed antigo — nunca é o padrão.

Criados via `python setup_indexes.py` (idempotente — detecta "already exists"/"duplicate" e segue). Se o cluster/permissão não permitir criar via código, imprime o JSON pronto para colar no Atlas UI.

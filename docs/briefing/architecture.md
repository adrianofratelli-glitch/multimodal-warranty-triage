# Arquitetura — Triagem de Garantia Multimodal

> Referência rápida para achar "onde está X" e "como isso funciona" sem reler o código inteiro. Queries e índices detalhados em `queries.md`; telas e fluxos em `ui-flows.md`. Esta PoV **não tem agente de IA com memória/state graph** — é uma chamada única ao Claude com tool use forçado (ver seção "Por que não há agent-behavior.md").

---

## O que essa PoV prova

Triagem de defeito em garantia, genérica para qualquer varejista que venda produto físico (aqui com dados fictícios ambientados como um e-commerce de móveis só para a demo ter cara de varejo real). Fluxo do cliente: busca o pedido → marca checklist de defeito → descreve o problema → envia foto (e opcionalmente uma foto extra por item marcado). O Claude classifica a causa provável do defeito usando precedentes históricos recuperados por busca vetorial no próprio Atlas.

Veredito possível: `defeito_fabrica` / `defeito_transporte` / `mau_uso` / `inconclusivo` — **sempre** marcado para revisão humana (`revisao_humana: true`, exigência do CDC no Brasil, setado pelo backend após a resposta do modelo, não configurável).

Tese comercial central: **um cluster Atlas único faz tudo** — não há vector DB separado, motor de busca separado, fila de mensagens separada. Nenhum Redis/Elastic/fila adicional.

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | FastAPI (Python 3.14, async), Motor (driver Mongo async) |
| LLM de visão | Claude, sempre via gateway Grove com `_shared/grove_client.AsyncGroveClient` (pacote `pov-shared`): `Authorization: Bearer` + chave real em `x-api-key`, retry com jitter, circuit breaker e fallback de modelo ligados por padrão |
| Embedding multimodal | Voyage AI `voyage-multimodal-3.5`, 1024 dimensões |
| Banco | MongoDB Atlas — único cluster para dados operacionais, vetor, full-text e change streams |
| Frontend | React 18 + Vite + LeafyGreen (design system MongoDB), sem TypeScript, sem router, sem state lib |
| Storage de imagem | Disco local (`backend/media/`, servido por FastAPI StaticFiles) — troca-se por S3+CDN em produção |
| Observabilidade | Logging estruturado próprio + métricas em processo (`/api/metrics`, `/metrics` Prometheus) + Langfuse opcional e fail-open (`langfuse>=2,<3`, uma trace por análise, criada depois da máscara de PII) |

## Componentes e onde vivem

| Componente | Arquivo |
|---|---|
| Rotas HTTP (thin, sem lógica de negócio) | `backend/main.py` |
| Config central (tudo vem do `.env`) | `backend/config.py` |
| Cliente Mongo + `safe_query`/`SafeQueryError` | `backend/db.py` |
| Recuperação de precedentes ($vectorSearch, $rankFusion, verificação de identidade) | `backend/rag.py` |
| Chamada ao Claude via Grove (tool use forçado, prazo total, fallback de revisão manual) | `backend/llm.py` |
| Localiza o `pov-shared` (instalado ou pasta irmã `../../_shared`) | `backend/shared_lib.py` |
| Máscara de PII e detecção de instrução no relato (por cláusula, anti-diluição) | `backend/guardrails_triagem.py` |
| Langfuse fail-open | `backend/langfuse_tracing.py` |
| Guarda de escrita (`*_test` ou `ALLOW_DEMO_DB_WRITE=1`) | `backend/demo_guard.py` |
| Reset único da demo / benchmark da tese | `scripts/reset_demo.py`, `scripts/bench_documento_unico.py` |
| Wrapper do embedding multimodal Voyage | `backend/voyage.py` |
| Storage de blob (disco local no PoV) | `backend/storage.py` |
| Checklist → frase natural, derivação de `tipo_defeito` | `backend/defeitos_catalog.py` |
| Criação de índices (regulares, vetoriais, texto) + validadores `$jsonSchema` | `backend/setup_indexes.py` |
| Logging JSON + métricas em processo | `backend/observability.py` |
| Seeds (`pedidos`, `catalogo`, `chamados`, `catalogo_fotos`) | `backend/seed_meta.py`, `seed.py`, `seed_catalogo_fotos.py` |
| Portal do cliente (React) | `frontend/src/tabs/Portal.jsx` |
| Fila de revisão (React, alimentada por Change Stream) | `frontend/src/tabs/Revisao.jsx` |
| Shell/abas | `frontend/src/App.jsx` |

## Fluxo de dados — `POST /api/analisar` (`backend/main.py`, `analisar` + `_processar_analise`)

Este é o endpoint central da PoV — todo o resto orbita ele.

1. **Valida o barato primeiro** — `modo`, pareamento foto extra/item, tamanho da descrição: 422 antes de tocar no banco.
2. **Resolve o produto** — `pedidos().find_one` por `numero_pedido` + `sku` → `categoria` (pedido inexistente = 404, SKU de outro pedido = 422).
3. **Valida entrada contra o catálogo real** — checklist desconhecido, duplicado, foto extra sem item marcado → 422 antes de qualquer chamada paga (`_validar_entrada_analise`).
4. **Normaliza a imagem para JPEG** (`_ler_e_normalizar`) — o content-type é só o primeiro filtro: quem decide é o formato real dos bytes (JPEG/PNG/MPO; GIF, WebP, SVG, PDF com extensão `.jpg` = 422). Teto de bytes (413) e de pixels antes de decodificar (`Image.MAX_IMAGE_PIXELS`, sem 500 por decompression bomb), orientação EXIF aplicada e **todo metadado descartado** (GPS, aparelho). O nome do arquivo enviado nunca é usado. `thumbnail((1568,1568))` porque é o teto que a visão do Claude usa.
5. **Idempotência atômica** — hash SHA-256 (foto normalizada + pedido/sku/checklist ordenado), janela de 60 s, mais a reserva `_id`=hash em `idempotencia`: envios idênticos simultâneos pagam embedding + LLM uma vez só e recebem o mesmo chamado (ver `queries.md` #6b).
6. **Compõe a `frase`** (`defeitos_catalog.compor_frase`) — o mesmo texto vira embedding. Uma cópia com **PII mascarada** (`guardrails_triagem.mascarar_pii`) é a única que sai do processo para o Claude, o Langfuse e os logs; o relato original fica só no documento.
7. **Sinal de instrução no relato** — `guardrails_triagem.avaliar_instrucao` aplica a heurística offline do `_shared/guardrails` ao texto inteiro e a cada cláusula (`score_by_clause`), para que uma ordem curta escondida num relato longo não se dilua. Cada cláusula é pontuada isoladamente (pov-shared ≥ 0.2.0, sem reagrupar); relato com mais de `MAX_CLAUSULAS` (128) cláusulas é marcado como suspeito (fail-closed), nunca tratado como "sem sinal".
8. **Upload da imagem em paralelo** (`asyncio.create_task` + `run_in_threadpool`) — não bloqueia embedding→RAG→veredito.
9. **Embedding multimodal manual** — `voyage.embed_multimodal(frase, imagem, "query")`, 1024d, foto principal e cada foto extra; timeout 30 s, 3 tentativas com backoff do SDK e prazo total `EMBED_DEADLINE_SECONDS`.
10. **Identidade do produto + precedentes em paralelo** — `rag.verificar_identidade` contra `catalogo_fotos` inteiro e `rag.vector_search`/`hybrid_search` filtrado por `{categoria, status: "resolvido"}`.
11. **Veredito do Claude via Grove** — `llm.analisar_veredito` (tool use forçado). Relato e precedentes vão entre `<relato_cliente>`/`<precedentes>` como dado; o modelo marca `alerta_manipulacao` se o relato, um precedente ou **texto escrito na foto** tentar dar ordens. Com alerta (do modelo ou da heurística) a confiança fica limitada a 50% e o revisor vê o motivo. Falha do gateway depois das tentativas, breaker aberto ou prazo `LLM_DEADLINE_SECONDS` estourado → veredito `inconclusivo` de revisão manual, caso preservado.
12. **Persistência em dois estágios** — insert com `status: "veredito_pronto_aguardando_upload"` assim que o veredito (pago) existe; depois do upload, um update promove a `em_analise` e grava `persistencia` (1 documento, 2 escritas, bytes do documento, ms do insert e do update), que a UI mostra.
### Por que Claude usa tool use forçado, não parsing de JSON em texto

`backend/llm.py` define a tool `emitir_veredito` com `input_schema` estrito (classificação enum, confiança 0-1, racional, sinais observados). A chamada usa `tool_choice={"type": "tool", "name": "emitir_veredito"}` — o SDK devolve `block.input` já como dict validado, sem parsing frágil de markdown fences ou `json.loads` que quebra em produção. Depois de receber, o backend ainda reimpõe as invariantes (`_normalizar_veredito`, `llm.py`): confiança clampada, `revisao_humana` sempre `True`, mesmo se o provedor devolver algo malformado.

System prompt e schema da tool levam `cache_control: {"type": "ephemeral"}` — são idênticos em toda chamada, então análises repetidas dentro do TTL de cache não pagam de novo os ~250 tokens de entrada fixos.

## Decisões de arquitetura (resumo — motivação completa nos comentários do código)

- **Imagem nunca entra no MongoDB.** Blob fica em disco local no PoV (`backend/storage.py`), interface `(uri, url)` é contrato — trocar para S3+CDN em produção é reescrever só esse arquivo. `_safe_path` rejeita path traversal (a key inclui o id do item de checklist vindo do cliente).
- **Tudo parametrizado pelo `.env`**, lido uma vez por `config.py` que sobe a árvore de diretórios procurando o arquivo. Nunca hardcoda nome de coleção/índice/modelo.
- **Erro tem uma via só**: toda leitura/escrita no Mongo passa por `db.safe_query`, que mapeia exceções pymongo/motor (inclusive qualquer `PyMongoError`) para `SafeQueryError(kind, message)`; um único exception handler converte isso em `{"error": {"kind", "message"}}` com status pelo `kind`: `imagem`/`entrada` 422, `imagem_grande` 413, `nao_encontrado` 404, `em_processamento` 409, e 503 só para infraestrutura (banco, Voyage). O frontend mostra o Banner e só repete 5xx sem corpo de domínio. O cliente Motor tem `serverSelectionTimeoutMS`, `connectTimeoutMS`, `socketTimeoutMS` (escritas não levam `maxTimeMS`) e `retryReads`/`retryWrites`.
- **Resiliência é o padrão, sem flag**: retry/breaker/fallback do `grove_client`, retry da Voyage e prazos totais estão ligados por padrão; as variáveis (`GROVE_RETRIES`, `GROVE_CB_THRESHOLD`, `VOYAGE_MAX_RETRIES`, `LLM_DEADLINE_SECONDS`...) só ajustam ou desligam.
- **Falha transitória de provedor (timeout/rede/5xx do gateway/Voyage) é tratada separado de bug de programação** — a primeira vira log WARNING e fallback seguro (`_FALLBACK`, veredito "inconclusivo" preservando o caso para revisão humana); a segunda vira log CRITICAL com stack trace completo, porque não é "provedor fora do ar", é bug nosso.
- **Colisão de `numero_chamado`** (6 hex chars, `CHM-{ano}-{hex}`) tem retry automático (`_inserir_chamado_com_retry`, até 3 tentativas) sem reprocessar o veredito já em memória.
- **Change Streams em vez de polling** para a fila de revisão em tempo real — `GET /api/chamados/stream` (SSE) sobre `chamados().watch(...)`. O evento serve de **gatilho**, não payload: o front recebe e rechama `GET /api/chamados/pendentes`, então a fila fica sempre consistente com o banco mesmo se um evento se perder.
- **Paginação real por cursor** em `/api/chamados/pendentes` (`created_at`+`_id`, não `skip`) — um `to_list(length=50)` sem paginação escondia permanentemente os casos mais antigos acima de 50 pendentes.

## Por que não há `agent-behavior.md`

Esta PoV **não usa LangGraph nem nenhum framework de agente com grafo de estados, checkpointer ou memória persistente**. `backend/llm.py` faz uma única chamada (`AsyncGroveClient().messages.create`) ao Claude, com tool use forçado, sem loop de decisão, sem múltiplos nodes, sem ferramentas que o modelo escolhe invocar dinamicamente. É "LLM com visão + tool use obrigatório", não um agente autônomo. Se essa PoV evoluir para ter um agente de verdade (ex.: um step de triagem que decide dinamicamente pedir mais fotos ao cliente), crie `agent-behavior.md` nessa hora.

## Como rodar (resumo)

```bash
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
uv pip install --python .venv/bin/python -e "../../_shared[llm]"   # pov-shared (Grove + guardrails)
MONGODB_DB=<banco>_test ./.venv/bin/python ../scripts/reset_demo.py  # ou ALLOW_DEMO_DB_WRITE=1 no banco da demo
cd .. && ./start.sh   # backend :8100 + frontend :5190
```

## Tese: um documento por chamado (medido)

Tudo que a triagem produz (metadados, vetor de 1024 floats, identidade, veredito, referência da foto) vive em um documento de `chamados`, gravado com 1 insert + 1 update. `scripts/bench_documento_unico.py` é uma comparação de modelagem dentro do MongoDB (não é benchmark de concorrente): grava e lê o mesmo chamado como 1 documento e como 3 coleções (metadados, vetor, veredito) no mesmo cluster e driver, para mostrar o custo de round trips da divisão e o custo extra de torná-la atômica com transação. Não mede outro banco nem serve de piso/teto para outra arquitetura. Medição de 2026-10-09, N=30, cluster de demo a partir da máquina local (`MONGODB_DB=<banco>_test backend/.venv/bin/python scripts/bench_documento_unico.py 30`): escrita p50 386,8 ms (1 op) vs 854,6 ms (3 ops sem atomicidade) vs 1075,1 ms (3 ops em transação); leitura p50 379,2 ms (1 op) vs 701,8 ms (3 ops). A UI mostra, a cada análise, os bytes do documento e o tempo do insert/update reais.

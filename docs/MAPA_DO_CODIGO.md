# Mapa do código — multimodal-warranty-triage

> Também conhecida como: Triagem de garantia (multimodal). Portas: frontend 5190 / backend 8100. Em uma frase: o cliente abre um chamado de garantia com foto, o sistema confere se a foto é do produto certo, busca chamados parecidos já resolvidos (Atlas Vector Search + `$rankFusion`), o Claude sugere a causa do defeito e um humano confirma na fila de revisão.

Este mapa é para localizar código rápido. O detalhe de cada query está em [briefing/queries.md](briefing/queries.md), a arquitetura em [briefing/architecture.md](briefing/architecture.md) e as telas em [briefing/ui-flows.md](briefing/ui-flows.md). Aqui só aponto o caminho.

## 1. Árvore anotada

```
backend/                         FastAPI (Python), toda a lógica
  main.py                        As rotas /api/* e o fluxo completo da análise (o arquivo mais importante)
  rag.py                         As buscas Atlas: $vectorSearch, identidade do produto, $rankFusion e $rerank
  llm.py                         Chamada ao Claude (tool use forçado) e normalização do veredito
  voyage.py                      Embedding multimodal (foto + frase) via Voyage
  db.py                          Cliente Motor, helpers de collection e safe_query (erro -> mensagem pronta para a UI)
  config.py                      Lê o .env: banco, collections, nomes de índice, limites
  storage.py                     Grava a foto em disco (backend/media) e devolve uri/url; o Mongo guarda só a referência
  guardrails_triagem.py          Mascara PII e detecta instrução embutida no relato (usa _shared/guardrails)
  shared_lib.py                  Localiza o pacote _shared (grove_client, guardrails) com degradação explícita
  defeitos_catalog.py            Tabela de defeitos por categoria + compor_frase / derivar_tipo_defeito
  langfuse_tracing.py            Tracing Langfuse, no-op se não houver chave
  observability.py               Logs e contadores em /api/metrics e /metrics
  demo_guard.py                  Trava: scripts que escrevem só rodam em banco *_test (ou ALLOW_DEMO_DB_WRITE=1)
  setup_indexes.py               Cria índices regulares, TTL, Vector Search, Atlas Search e $jsonSchema
  seed.py / seed_data.py         Os 15 chamados resolvidos (precedentes) com embedding
  seed_meta.py / pedidos_data.py Pedidos e catálogo de checklist
  seed_catalogo_fotos.py         Fotos de referência dos SKUs (usadas na verificação de identidade)
  catalogo_produtos_data.py      Lista de produtos que alimenta as fotos de referência
  generate_placeholders.py       Gera imagens de exemplo (o repo não traz fotos)
  generate_catalogo_placeholders.py  Idem, para o catálogo
  test_http.py                   Smoke test HTTP contra o uvicorn rodando
  tests/                         Testes unitários e adversariais (ver seção 6)
frontend/                        React + Vite + LeafyGreen
  src/App.jsx                    Casca: 2 abas, poll de /api/health, estado elevado das abas
  src/api.js                     Cliente fetch (timeout, retry, ApiError); todas as chamadas HTTP passam aqui
  src/tabs/Portal.jsx            Aba "Abrir chamado" (pedido, produto, checklist, foto, Analisar, resultado)
  src/tabs/Revisao.jsx           Aba "Revisar" (fila, stream ao vivo, confirmar)
  src/components/                IdentidadeCard, VeredictoCard, PipelineSteps, QueryDetails, JsonViewer
  src/lib/triagem.js             Regras puras de rótulo (grau de match, $rerank, identidade, confiança)
  src/polyfills.js               Polyfills de Node exigidos pelo LeafyGreen
  vite.config.js                 Porta 5190 e proxy de /api e /media para 8100 (POV_API_URL troca o alvo)
  tests/http-deadline.test.mjs   Teste do prazo do cliente HTTP
  tests/triagem.test.mjs         Testes das regras de rótulo (src/lib/triagem.js)
scripts/
  reset_demo.py                  Recria todos os dados da demo num comando (seed + índices + validação)
  bench_documento_unico.py       Benchmark "1 documento" x "3 coleções" x transação
seed_images/                     Fotos usadas nos cenários prontos
docs/briefing/                   Briefings (arquitetura, queries, telas)
docs/adr/                        Decisões de arquitetura (documento único, identidade, embedding, $rerank)
docs/screenshots/                Capturas de tela
run.sh / start.sh                Sobem backend e frontend (ver README)
Dockerfile, docker/, nginx.conf  Empacotamento
```

## 2. "Apertei o botão X, o que roda?"

Todas as chamadas do front passam por `frontend/src/api.js` (objeto `api`, a partir da linha 68). O proxy do Vite leva `/api` para o backend.

| Tela / ação | Componente (arquivo:linha) | Chamada HTTP | Handler da rota | Função de negócio | Onde toca o MongoDB |
|---|---|---|---|---|---|
| Abrir o app (status e contadores no topo, a cada 10 s) | `frontend/src/App.jsx:26-46` | `GET /api/health` | `backend/main.py:148` `health` | `_counts_por_status` (`main.py:168`) | `main.py::_counts_por_status` (`$group` por status, `chamados`) e `ping` |
| Carregar a lista de pedidos | `Portal.jsx:146` (`api.pedidos()`) | `GET /api/pedidos` | `main.py:184` `listar_pedidos` | a própria rota | `main.py::listar_pedidos` (`find`, `pedidos`) |
| Escolher o pedido no Select | `Portal.jsx:333-341` -> `buscar` (`Portal.jsx:152`) | `POST /api/lookup` | `main.py:195` `lookup` | a própria rota | `main.py::lookup` (`find_one` e `distinct`, `pedidos`) |
| Clicar no produto/SKU do pedido | `Portal.jsx:357-359` -> `escolher` (`Portal.jsx:163`) | `GET /api/checklist/{categoria}` | `main.py:210` `checklist` | a própria rota | `main.py::checklist` (`find_one`, `catalogo`) |
| Menu "Cenário" (pedido+produto+checklist+foto prontos) | `Portal.jsx:314-322` -> `aplicarCenario` (`Portal.jsx:221`) | `POST /api/lookup` e `GET /api/checklist/{categoria}` | idem acima | idem acima | idem acima (o `CENARIOS` está em `Portal.jsx:32`) |
| Marcar item do checklist / foto extra | `Portal.jsx:372` (`toggle`, linha 197) e `Portal.jsx:377` (`onFileExtra`, linha 213) | nenhuma (só estado local) | n/a | n/a | n/a |
| Foto principal | `Portal.jsx:398` (`onFile`, linha 251) | nenhuma (só estado local) | n/a | n/a | n/a |
| **Analisar defeito** | `Portal.jsx:409` -> `analisar` (`Portal.jsx:258`) | `POST /api/analisar` (multipart; `modo` é fixo `hybrid`, `Portal.jsx:137`) | `main.py:465` `analisar` | `main.py::_processar_analise` (`main.py:525`), que chama `rag.verificar_identidade`, `rag.hybrid_search`, `llm.analisar_veredito` | ver tabela da seção 3 (idempotência, 2 buscas Atlas, insert e update de `chamados`) |
| Novo chamado | `Portal.jsx:349` -> `reiniciar` (`Portal.jsx:295`) | nenhuma | n/a | n/a | n/a |
| Aba Revisar: carga inicial e "Atualizar" | `Revisao.jsx:141` -> `carregar` (`Revisao.jsx:30`) | `GET /api/chamados/pendentes` | `main.py:743` `chamados_pendentes` | a própria rota | `main.py::chamados_pendentes` (`find` paginado por cursor + `_counts_por_status`, `chamados`) |
| "Carregar mais" | `Revisao.jsx:177` -> `carregarMais` (`Revisao.jsx:51`) | `GET /api/chamados/pendentes?before_created_at=..&before_id=..` | idem | idem | idem |
| Fila ao vivo (badge "live") | `Revisao.jsx:88` (`new EventSource`) | `GET /api/chamados/stream` (SSE) | `main.py:859` `chamados_stream` | gerador `_gen` dentro da rota | `main.py::chamados_stream` (`chamados().watch`, Change Stream) |
| Selecionar um chamado da fila | `Revisao.jsx:164` -> `selecionar` (`Revisao.jsx:101`) | nenhuma (usa o doc já carregado) | n/a | n/a | n/a |
| **Confirmar** resolução | `Revisao.jsx:208` -> `confirmar` (`Revisao.jsx:108`) | `POST /api/revisar` | `main.py:802` `revisar` | a própria rota | `main.py::revisar` (`update_one` filtrando `status: em_analise`, depois `find_one`; `chamados`) |

Sem botão na UI (só por API): `GET /api/analytics` (`main.py:833`, agregações para Atlas Charts), `GET /api/metrics` (`main.py:105`), `GET /metrics` (`main.py:111`, formato Prometheus), `GET /health/live` (`main.py:163`).

### O que o `POST /api/analisar` faz, em ordem (para explicar em call)

1. Valida entrada e resolve o produto no pedido (`main.py::_resolver_produto`, `_tabela_catalogo`, `_validar_entrada_analise`) e normaliza a foto (`_ler_e_normalizar`, remove EXIF, aceita só JPEG/PNG).
2. Idempotência: hash da foto+pedido+SKU+checklist, `_buscar_chamado_idempotente` e trava em `idempotencia` (`_reservar_idempotencia`). Envio repetido devolve o mesmo chamado sem cobrar LLM de novo.
3. `_processar_analise`: compõe a frase (`defeitos_catalog.py::compor_frase`), mascara PII (`guardrails_triagem.py::mascarar_pii`), sobe a foto em paralelo (`storage.py::upload_imagem`).
4. Embedding multimodal (`voyage.py::embed_multimodal`, via `main.py::_embed`).
5. Em paralelo: `rag.verificar_identidade` (a foto é do SKU certo?) e `rag.hybrid_search` (precedentes).
6. `llm.py::analisar_veredito` (Claude, tool `emitir_veredito`). Se o gateway falhar, devolve o veredito "inconclusivo" de revisão manual.
7. Insert do chamado já com o veredito (`_inserir_chamado_com_retry`, status `veredito_pronto_aguardando_upload`), espera o upload e faz o update para `em_analise` com a medição `persistencia` (`main.py:707`).

## 3. Onde estão as queries MongoDB

Detalhe e exemplos em [briefing/queries.md](briefing/queries.md). Collections: `pedidos`, `catalogo`, `chamados`, `catalogo_fotos`, `idempotencia` (nomes configuráveis em `backend/config.py`).

| O que faz | arquivo::função (linha) | Operador / pipeline | Collection |
|---|---|---|---|
| Contagem por status (health e fila) | `backend/main.py::_counts_por_status` (168) | `aggregate [$group]` | `chamados` |
| Listar pedidos | `main.py::listar_pedidos` (184) | `find` + `sort` | `pedidos` |
| Buscar pedido; sugerir pedidos válidos | `main.py::lookup` (194) | `find_one`, `distinct` | `pedidos` |
| Checklist da categoria | `main.py::checklist` (209) e `_tabela_catalogo` (225) | `find_one` | `catalogo` |
| Conferir se o SKU pertence ao pedido | `main.py::_resolver_produto` (217) | `find_one` | `pedidos` |
| Achar chamado idêntico na janela de 60 s | `main.py::_buscar_chamado_idempotente` (347) | `find_one` por `idempotency_hash` + `created_at` | `chamados` |
| Reservar / retomar / liberar trava de idempotência | `main.py::_reservar_idempotencia` (363), `_liberar_idempotencia` (395), `_aguardar_chamado_concorrente` (403) | `insert_one` (`_id` = hash), `update_one`, `delete_one`, `find_one`; TTL em `expires_at` | `idempotencia` |
| Gravar o chamado com veredito | `main.py::_inserir_chamado_com_retry` (326) | `insert_one` com retry em chave duplicada | `chamados` |
| Promover o chamado a `em_analise` (upload concluído) | `main.py::_processar_analise` (update em `main.py:707`) | `update_one $set` | `chamados` |
| Precedentes, modo vetorial | `backend/rag.py::vector_search` (51) | `$vectorSearch` (filtro `categoria` + `status: resolvido`) + `$addFields` + `$project` | `chamados` |
| Precedentes, modo híbrido (o que a UI usa) | `rag.py::hybrid_search` (159) | `$rankFusion` com `$vectorSearch` + `$search` (`compound`), pesos 0,7/0,3; cai para `vector_search` se faltar suporte/índice | `chamados` |
| "A foto é do produto certo?" | `rag.py::verificar_identidade` (147) | `$vectorSearch` só com o vetor da imagem, sem filtro de SKU, 30 resultados (+1 busca filtrada por sku se ele não aparecer); decisão relativa em `decidir_identidade` | `catalogo_fotos` |
| Fila de revisão paginada | `main.py::chamados_pendentes` (728) | `find` + `sort(created_at,_id)` + cursor com `$or` | `chamados` |
| Confirmar revisão (só um revisor vence) | `main.py::revisar` (787) | `update_one` com filtro `status: em_analise`; `find_one` para distinguir 404 e 409 | `chamados` |
| Analytics | `main.py::analytics` (818) | 2x `aggregate [$group, $sort]` | `chamados` |
| Fila ao vivo | `main.py::chamados_stream` (844) | `watch` (Change Stream) com `$match` e `$project` | `chamados` |
| Criar índices e validadores | `backend/setup_indexes.py::main` (143); `_regular_indexes`, `_search_index`, `_apply_validator` | índices regulares/TTL, `create_search_index` (vector e search), `collMod` com `$jsonSchema` | `chamados`, `pedidos`, `catalogo`, `catalogo_fotos`, `idempotencia` |
| Seed dos precedentes | `backend/seed.py::main` (87) | `replace_one` upsert por `numero_chamado` | `chamados` |
| Seed de pedidos e catálogo | `backend/seed_meta.py::main` (21) | `replace_one` upsert | `pedidos`, `catalogo` |
| Seed das fotos de referência | `backend/seed_catalogo_fotos.py::main` (65) | `replace_one` upsert por (`sku`, `foto_idx`) | `catalogo_fotos` |
| Reset da demo | `scripts/reset_demo.py::main` (75) | `delete_many` (tudo que não é seed), `list_search_indexes`, `$vectorSearch` de validação | `chamados`, `idempotencia` e as demais do seed |
| Benchmark de modelagem | `scripts/bench_documento_unico.py::main` (58) | `insert_one`/`find_one`, transação | coleções temporárias do benchmark |

Nome dos índices (padrões em `config.py`): `defeitos_vector_index` (vetorial de `chamados`), `chamados_text_index` (Atlas Search), `catalogo_fotos_vector_index` (vetorial de `catalogo_fotos`).

## 4. Compartilhado × só desta PoV

**Vem de `_shared`** (pacote `pov-shared`, carregado por `backend/shared_lib.py::_load`, que tenta `import` e depois a pasta irmã `../../_shared`; se não achar, vira `None` e a PoV degrada):
- `grove_client` -> `backend/llm.py` (`from shared_lib import grove_client`, linha 24; `grove_client.AsyncGroveClient()` em `llm.py::_get_client`). Toda chamada ao Claude passa por aqui, via gateway Grove.
- `guardrails` -> `backend/guardrails_triagem.py` (`from shared_lib import guardrails`, linha 19): `mask_pii`, `check_injection` e `score_by_clause`.
- Visual: `frontend/src/pov-signature.css` é cópia gerada de `_shared/ui` (não editar à mão; ver `CLAUDE.md`).

**Variáveis de ambiente** (nomes em `.env.example`; o `.env` não vai para o Git):
- Comuns, vindas de `PoVs/.env.shared` via `_shared/sync_env.py`: `MONGODB_URI`, `GROVE_BASE_URL`, `GROVE_API_KEY`, `VOYAGE_API_KEY`.
- Locais desta PoV: `MONGODB_DB` (padrão `analise_garantia`), `MONGODB_COLLECTION`, `MONGODB_CATALOGO_COLLECTION`, `MONGODB_PEDIDOS_COLLECTION`, `MONGODB_CATALOGO_FOTOS_COLLECTION`, `VECTOR_INDEX_NAME`, `TEXT_INDEX_NAME`, `CATALOGO_FOTOS_VECTOR_INDEX_NAME`, `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`. Limites e prazos opcionais lidos direto no código: `MAX_IMAGE_BYTES`, `MAX_IMAGE_PIXELS`, `MAX_EXTRA_IMAGES`, `MAX_DESCRIPTION_CHARS`, `MEDIA_ROOT` (`config.py`), `LLM_DEADLINE_SECONDS` (`llm.py`), `EMBED_DEADLINE_SECONDS` e `IDEMPOTENCY_WAIT_SECONDS` (`main.py`), `VOYAGE_TIMEOUT_SECONDS` e `VOYAGE_MAX_RETRIES` (`voyage.py`), `ALLOW_DEMO_DB_WRITE` e `VALIDATION_ACTION` (scripts de escrita). Langfuse: `LANGFUSE_PUBLIC_KEY` e `LANGFUSE_SECRET_KEY` (`langfuse_tracing.py`).
- A porta 8100 está fixa em `run.sh`, `main.py` (CORS) e `frontend/vite.config.js`; a 5190 em `vite.config.js` e `run.sh`.

**Coleções e banco**: o banco (`analise_garantia`) pode ser compartilhado com outras PoVs, mas as cinco coleções acima são exclusivas desta PoV (o `reset_demo.py` só toca nelas). Não encontrei no código coleção usada por outra PoV.

**Chamadas externas**:
- Claude via Grove: `backend/llm.py::analisar_veredito` (`_get_client().messages.create`, linha 246).
- Voyage (embedding multimodal): `backend/voyage.py::embed_multimodal`, chamado em `main.py::_embed` (runtime) e nos seeds (`input_type="document"`).
- Langfuse: `backend/langfuse_tracing.py`, usado em `main.py::_processar_analise` (`start_trace`, `log_span`, `log_generation`, `finish_trace`); fail-open.

## 5. "Quero mexer em..." (atalhos)

- Texto do cabeçalho, nome das abas -> `frontend/src/App.jsx` (`TABS` na linha 7 e o `<h1>`).
- Textos das 7 etapas animadas -> `frontend/src/tabs/Portal.jsx` (`STEPS` linha 14, `STEP_DETAILS` linha 19).
- Cenários prontos da demo (pedido, foto, descrição) -> `frontend/src/tabs/Portal.jsx` (`CENARIOS`, linha 32) e as fotos em `seed_images/`.
- Sugestão de resolução por classificação na Revisão -> `frontend/src/tabs/Revisao.jsx` (`SUGESTAO`, linha 11).
- Adicionar uma rota -> `backend/main.py` (decorator `@app.get/post`; erro de negócio via `SafeQueryError`, o status por tipo está em `_STATUS_POR_KIND`) e um método novo em `frontend/src/api.js`.
- Trocar modo da busca (híbrida x vetorial) -> `Portal.jsx:137` (constante `modo`); a lógica está em `backend/rag.py`.
- Mudar a query de precedentes (pesos, `numCandidates`, filtro) -> `backend/rag.py::hybrid_search` / `vector_search` (`NUM_CANDIDATES`, `LIMIT` no topo do arquivo).
- Regra de "foto do produto errado" -> `backend/rag.py` (`IDENTIDADE_THRESHOLD`, `IDENTIDADE_MARGEM`, função pura `decidir_identidade`, consulta `verificar_identidade`); vetor só da imagem em `backend/voyage.py::embed_imagem`; testes em `backend/tests/test_identidade.py`; medição em `eval/run_quality.py`.
- Prompt e formato do veredito do Claude -> `backend/llm.py` (`SYSTEM`, `VEREDITO_TOOL`, `_normalizar_veredito`); o teto de confiança sob suspeita de manipulação é `CONFIANCA_MAX_SOB_ALERTA`.
- Categorias, itens de checklist e tipos de defeito -> `backend/defeitos_catalog.py` (`CATALOGO_DEFEITOS`); depois rode `seed_meta.py` para gravar no banco.
- Pedidos e produtos de exemplo -> `backend/pedidos_data.py` e `backend/catalogo_produtos_data.py`.
- Os 15 precedentes do seed -> `backend/seed_data.py`.
- Definição dos índices -> `backend/setup_indexes.py` (`VECTOR_DEF`, `TEXT_DEF`, `CATALOGO_FOTOS_VECTOR_DEF`, `CHAMADOS_SCHEMA`).
- Mudar porta -> `frontend/vite.config.js`, `run.sh`, o CORS em `backend/main.py` e `PORTS.md` na raiz do workspace.
- Limites de upload, modelo, nomes de índice -> `backend/config.py` ou o `.env`.

## 6. Testes

Rodar (do README): `cd backend && ./.venv/bin/pytest -q` (unitário e adversarial, sem Atlas nem rede, gateway mockado); `cd frontend && node --test tests/*.test.mjs`; smoke contra o servidor rodando: `cd backend && ./.venv/bin/python test_http.py`; suíte viva (Atlas, Voyage e Grove reais, só em banco `*_test`): `LIVE_API_URL=http://127.0.0.1:8100 backend/.venv/bin/pytest -q backend/tests/adversarial/test_live_adversarial.py`.

| Arquivo | O que cobre |
|---|---|
| `backend/tests/test_defeitos_catalog.py` | `derivar_tipo_defeito` e `compor_frase` |
| `backend/tests/test_input_validation.py` | Validação de entrada de `/api/lookup` e da análise |
| `backend/tests/test_llm_resilience.py` | Saída malformada do modelo e falha do provedor viram "inconclusivo" |
| `backend/tests/test_storage.py` | `url_for`/`path_for` e bloqueio de path traversal |
| `backend/tests/test_observability.py`, `test_api_metrics.py` | Contadores, `/api/metrics` e header `X-Request-Id` |
| `backend/tests/adversarial/test_api_adversarial.py` | Envios idênticos concorrentes (idempotência), injeção de operador NoSQL, revisões paralelas |
| `backend/tests/adversarial/test_upload_adversarial.py` | Uploads hostis (MIME falso, bomba de descompressão, EXIF, nomes com traversal) |
| `backend/tests/adversarial/test_llm_adversarial.py` | Prompt injection, PII em prompt/trace, timeout/429/5xx do gateway, Langfuse fora |
| `backend/tests/adversarial/test_mongo_resilience_adversarial.py` | Falhas do MongoDB viram erro tratado |
| `backend/tests/adversarial/test_demo_guard_adversarial.py` | Trava de escrita em banco da demo |
| `backend/tests/adversarial/test_live_adversarial.py` | Cenários reais contra a API rodando |
| `frontend/tests/http-deadline.test.mjs` | Prazo do cliente HTTP |

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
| LLM de visão | Claude (Anthropic), via gateway Grove — `Authorization: Bearer` + chave real em `x-api-key` |
| Embedding multimodal | Voyage AI `voyage-multimodal-3.5`, 1024 dimensões |
| Banco | MongoDB Atlas — único cluster para dados operacionais, vetor, full-text e change streams |
| Frontend | React 18 + Vite + LeafyGreen (design system MongoDB), sem TypeScript, sem router, sem state lib |
| Storage de imagem | Disco local (`backend/media/`, servido por FastAPI StaticFiles) — troca-se por S3+CDN em produção |
| Observabilidade | Logging estruturado próprio + métricas em processo (`/api/metrics`, `/metrics` Prometheus) |

## Componentes e onde vivem

| Componente | Arquivo |
|---|---|
| Rotas HTTP (thin, sem lógica de negócio) | `backend/main.py` |
| Config central (tudo vem do `.env`) | `backend/config.py` |
| Cliente Mongo + `safe_query`/`SafeQueryError` | `backend/db.py` |
| Recuperação de precedentes ($vectorSearch, $rankFusion, verificação de identidade) | `backend/rag.py` |
| Chamada ao Claude (tool use forçado) | `backend/llm.py` |
| Wrapper do embedding multimodal Voyage | `backend/voyage.py` |
| Storage de blob (disco local no PoV) | `backend/storage.py` |
| Checklist → frase natural, derivação de `tipo_defeito` | `backend/defeitos_catalog.py` |
| Criação de índices (regulares, vetoriais, texto) + validadores `$jsonSchema` | `backend/setup_indexes.py` |
| Logging JSON + métricas em processo | `backend/observability.py` |
| Seeds (`pedidos`, `catalogo`, `chamados`, `catalogo_fotos`) | `backend/seed_meta.py`, `seed.py`, `seed_catalogo_fotos.py` |
| Portal do cliente (React) | `frontend/src/tabs/Portal.jsx` |
| Fila de revisão (React, alimentada por Change Stream) | `frontend/src/tabs/Revisao.jsx` |
| Shell/abas | `frontend/src/App.jsx` |

## Fluxo de dados — `POST /api/analisar` (`backend/main.py:343-558`)

Este é o endpoint central da PoV — todo o resto orbita ele.

1. **Resolve o produto** — `pedidos().find_one` por `numero_pedido` + `sku` → obtém `categoria` (`main.py:191-196`).
2. **Valida entrada contra o catálogo real** — checklist desconhecido, duplicado, foto extra sem item marcado, limites de tamanho → tudo 422 antes de qualquer chamada paga (`main.py:235-261`).
3. **Normaliza a imagem para JPEG** (Pillow) — garante `media_type` consistente com os bytes e formato aceito pela visão do Claude; `thumbnail((1568,1568))` porque é o teto de resolução que a visão do Claude usa (acima disso a API cobra os tokens da imagem cheia mesmo redimensionando do lado dela) (`main.py:204-232`).
4. **Idempotência** — hash SHA-256 determinístico (foto principal normalizada + pedido/sku/checklist ordenado), janela de 60s. Um duplo-clique ou retry de rede reaproveita o chamado já criado em vez de pagar LLM+embedding de novo (`main.py:264-281`, `309-318`).
5. **Compõe a `frase`** em linguagem natural a partir do checklist+descrição (`defeitos_catalog.compor_frase`) — é o mesmo texto que vai virar embedding.
6. **Upload da imagem em paralelo** (`asyncio.create_task` + `run_in_threadpool`) — não bloqueia o caminho crítico embedding→RAG→veredito; só é aguardado na montagem da resposta.
7. **Embedding multimodal manual** (Caminho B) — `voyage.embed_multimodal(frase, imagem_pil, "query")`, 1024d, roda para a foto principal e para cada foto extra.
8. **Identidade do produto** — `rag.verificar_identidade` compara o embedding contra `catalogo_fotos` inteiro (todos os SKUs, sem filtro), roda em paralelo com a busca de precedentes via `asyncio.gather` (`main.py:451-467`). Ver critério relativo em `queries.md`.
9. **Recuperação de precedentes** — `rag.vector_search` (padrão) ou `rag.hybrid_search` (`modo=hybrid`, usa `$rankFusion`), filtrado por `{categoria, status: "resolvido"}`.
10. **Veredito do Claude** — `llm.analisar_veredito`, tool use forçado (ver seção própria abaixo).
11. **Persistência em dois estágios** — grava o chamado com `status: "veredito_pronto_aguardando_upload"` **assim que o veredito (caro, já pago) sai do Claude**, antes mesmo do upload da imagem terminar. Se o upload falhar depois, o chamado não perde o veredito — fica em estado intermediário reconciliável, e só depois é promovido a `status: "em_analise"` (`main.py:488-543`). Essa é a decisão de resiliência mais importante do fluxo.

### Por que Claude usa tool use forçado, não parsing de JSON em texto

`backend/llm.py:46-74` define a tool `emitir_veredito` com `input_schema` estrito (classificação enum, confiança 0-1, racional, sinais observados). A chamada usa `tool_choice={"type": "tool", "name": "emitir_veredito"}` — o SDK devolve `block.input` já como dict validado, sem parsing frágil de markdown fences ou `json.loads` que quebra em produção. Depois de receber, o backend ainda reimpõe as invariantes (`_normalizar_veredito`, `llm.py:89-112`): confiança clampada, `revisao_humana` sempre `True`, mesmo se o provedor devolver algo malformado.

System prompt e schema da tool levam `cache_control: {"type": "ephemeral"}` — são idênticos em toda chamada, então análises repetidas dentro do TTL de cache não pagam de novo os ~250 tokens de entrada fixos.

## Decisões de arquitetura (resumo — motivação completa nos comentários do código)

- **Imagem nunca entra no MongoDB.** Blob fica em disco local no PoV (`backend/storage.py`), interface `(uri, url)` é contrato — trocar para S3+CDN em produção é reescrever só esse arquivo. `_safe_path` rejeita path traversal (a key inclui o id do item de checklist vindo do cliente).
- **Tudo parametrizado pelo `.env`**, lido uma vez por `config.py` que sobe a árvore de diretórios procurando o arquivo. Nunca hardcoda nome de coleção/índice/modelo.
- **Erro tem uma via só**: toda leitura/escrita no Mongo passa por `db.safe_query`, que mapeia exceções pymongo/motor para `SafeQueryError(kind, message)`; um único exception handler no FastAPI converte isso em 503 `{"error": {"kind", "message"}}`, renderizado como Banner no frontend. Falha de domínio (pedido não encontrado, SKU inválido) também levanta `SafeQueryError` — não há caminho de erro paralelo. Validação de formato de entrada usa `HTTPException` 422 (erro do cliente, categoria diferente).
- **Falha transitória de provedor (timeout/rede/5xx do Anthropic/Voyage) é tratada separado de bug de programação** — a primeira vira log WARNING e fallback seguro (`_FALLBACK`, veredito "inconclusivo" preservando o caso para revisão humana); a segunda vira log CRITICAL com stack trace completo, porque não é "provedor fora do ar", é bug nosso.
- **Colisão de `numero_chamado`** (6 hex chars, `CHM-{ano}-{hex}`) tem retry automático (`_inserir_chamado_com_retry`, até 3 tentativas) sem reprocessar o veredito já em memória.
- **Change Streams em vez de polling** para a fila de revisão em tempo real — `GET /api/chamados/stream` (SSE) sobre `chamados().watch(...)`. O evento serve de **gatilho**, não payload: o front recebe e rechama `GET /api/chamados/pendentes`, então a fila fica sempre consistente com o banco mesmo se um evento se perder.
- **Paginação real por cursor** em `/api/chamados/pendentes` (`created_at`+`_id`, não `skip`) — um `to_list(length=50)` sem paginação escondia permanentemente os casos mais antigos acima de 50 pendentes.

## Por que não há `agent-behavior.md`

Esta PoV **não usa LangGraph nem nenhum framework de agente com grafo de estados, checkpointer ou memória persistente**. `backend/llm.py` faz uma única chamada síncrona (`client.messages.create`) ao Claude, com tool use forçado, sem loop de decisão, sem múltiplos nodes, sem ferramentas que o modelo escolhe invocar dinamicamente. É "LLM com visão + tool use obrigatório", não um agente autônomo. Se essa PoV evoluir para ter um agente de verdade (ex.: um step de triagem que decide dinamicamente pedir mais fotos ao cliente), crie `agent-behavior.md` nessa hora.

## Como rodar (resumo)

```bash
cd backend
./.venv/bin/python seed_meta.py && ./.venv/bin/python seed.py && ./.venv/bin/python seed_catalogo_fotos.py
./.venv/bin/python setup_indexes.py
./start.sh   # backend :8100 + frontend :5190
```

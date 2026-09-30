# Telas, fluxos e componentes — Frontend

> Onde cada tela/componente vive e o que ela mostra. Arquitetura geral em `architecture.md`; queries por trás de cada tela em `queries.md`.

---

## Stack

React 18 + Vite + LeafyGreen (design system MongoDB), JavaScript puro (sem TypeScript), sem router, sem lib de state — `fetch` cru embrulhado em `frontend/src/api.js`. Portas fixas (`strictPort: true`, Vite em `5190`); o proxy do Vite encaminha `/api` e `/media` para o backend em `8100`.

`nodePolyfills` é obrigatório no `vite.config.js` — `@emotion/server` (dependência transitiva do LeafyGreen) usa builtins do Node no bundle de browser.

## Shell — `frontend/src/App.jsx`

Duas abas: **Abrir chamado** (Portal) e **Revisar** (Revisão). `TABS = ['Abrir chamado', 'Revisar']` (`App.jsx:7`).

- Estado das duas abas é **elevado para o App** (`portalState`, `revisaoState`), não vive dentro de cada aba — trocar de aba não apaga o resultado da análise nem a seleção da revisão (`App.jsx:14-21`).
- `visited` (Set) garante que cada aba só monta na primeira visita, mas depois fica sempre viva em memória (`display: none` quando não selecionada) — evita remount que perderia estado do EventSource da Revisão.
- Poll de `/api/health` a cada 10s, só quando a aba do browser está visível (`document.visibilityState`), alimenta o contador "N precedentes · N em análise" no cabeçalho e o status-dot de conexão com o Atlas (`App.jsx:26-46`).

## Aba 1 — Portal do cliente (`frontend/src/tabs/Portal.jsx`)

Fluxo de várias etapas, cada uma com seu próprio argumento de demo:

1. **Selecionar pedido** — dropdown populado por `GET /api/pedidos`. Ao escolher, `POST /api/lookup` traz os produtos do pedido.
2. **Escolher produto/SKU** — botões por produto do pedido; carrega o checklist da categoria via `GET /api/checklist/{categoria}`.
3. **Marcar checklist + descrição** — marcar um item sugere uma frase automática na descrição (sem apagar o que o cliente já escreveu); cada item marcado pode receber sua própria foto extra.
4. **Upload da foto principal** — obrigatório para habilitar "Analisar defeito".
5. **Analisar** — dispara `POST /api/analisar`; enquanto a resposta não chega, `PipelineSteps` anima 7 etapas (2s cada, canceladas se a resposta real chegar antes) mostrando visualmente o que está acontecendo no backend (`Portal.jsx:258-293`).
6. **Resultado** — `IdentidadeCard`, `VeredictoCard`, foto(s), painel de precedentes com `funnel` e `QueryDetails` (pipeline de agregação real executado, sem os 1024 floats do vetor).

### Cenários prontos (`Portal.jsx:32-120`)

Um dropdown de "Cenário" carrega de uma vez pedido + produto + checklist + descrição + foto real do catálogo — elimina risco de erro de upload manual ao vivo numa apresentação. Inclui:
- 4 cenários "felizes" (foto certa para o produto certo) cobrindo categorias diferentes (cadeira, colchão, guarda-roupa) e um pedido multi-categoria.
- 2 cenários **negativos** (`negativo: true`) que sobem de propósito uma foto de produto diferente do pedido, para demonstrar que a verificação de identidade pega o erro antes de qualquer conclusão sobre causa do defeito — um mostra "produto parecido mas errado" (dois guarda-roupas com número de portas diferente), outro "produto totalmente errado" (cadeira em vez de colchão).

### Componentes usados no Portal

| Componente | Arquivo | O que mostra |
|---|---|---|
| `PipelineSteps` | `frontend/src/components/PipelineSteps.jsx` | as 7 etapas do `POST /api/analisar` em `pending → running → done`, cada uma com uma linha explicando o que acontece no MongoDB naquele passo (texto fixo em `STEP_DETAILS`, `Portal.jsx:19-27`) |
| `IdentidadeCard` | `frontend/src/components/IdentidadeCard.jsx` | resultado de `verificar_identidade` — % de similaridade, badge verde/vermelho conforme `abaixo_threshold`, e dois textos de aviso **diferentes** conforme o modo de falha (SKU disputado vs. produto desconhecido) |
| `VeredictoCard` | `frontend/src/components/VeredictoCard.jsx` | classificação (badge colorido por tipo), barra de confiança com 3 faixas (baixa/moderada/alta), racional em texto, sinais observados, aviso fixo de revisão humana, e metadados (`_meta`: precedentes usados, latência) |
| `JsonViewer` | `frontend/src/components/JsonViewer.jsx` | documento Mongo cru — usado tanto nos precedentes quanto no chamado completo na Revisão |
| `QueryDetails` | `frontend/src/components/QueryDetails.jsx` | expõe o pipeline de agregação real que rodou (via `funnel.query_details`/`identidade.query_details`), com o `queryVector` substituído por `"<N floats omitidos>"` (`rag.py:_display_pipeline`) — nunca expõe o vetor cru na tela |

### Painel de precedentes (`Portal.jsx:468-514`)

Mostra o `funnel` (quantos candidatos, filtro aplicado, quantos retornaram, modo — `$rankFusion`/`$vectorSearch`/fallback), os pesos vetorial/textual quando é híbrido, e um badge visual de "match forte/moderado/fraco" **relativo ao melhor score da própria busca** (não ao valor absoluto — o score do `$rankFusion` é Reciprocal Rank Fusion, sempre baixo em módulo por construção do algoritmo).

## Aba 2 — Revisão (`frontend/src/tabs/Revisao.jsx`)

Fila de chamados `status: em_analise` aguardando confirmação humana.

- **Carga inicial e "Atualizar"** — `GET /api/chamados/pendentes` sem cursor.
- **"Carregar mais"** — passa `next_cursor` da página anterior; aparece só quando `has_more` é true.
- **Change Stream ao vivo** — abre um `EventSource('/api/chamados/stream')` só quando a aba está `active` e o browser está visível; cada evento recarrega a fila do zero via `GET /api/chamados/pendentes` (o SSE é gatilho, não payload). Badge "● live" reflete o estado real da conexão (`es.onopen`/`es.onerror`), não fica verde por otimismo.
- **Selecionar um chamado** — mostra `VeredictoCard`, sugestão de resolução por classificação (`SUGESTAO`, `Revisao.jsx:11-16` — o humano confirma/edita, nunca é aplicada automaticamente), campo de texto livre, e o documento Mongo cru via `JsonViewer`.
- **Confirmar** — `POST /api/revisar`; sucesso remove o item da lista local e mostra banner de sucesso mencionando explicitamente "adicionado à base de precedentes" — reforça o flywheel na tela.

## Regra de fronteira entre UI e backend

**A UI não conclui nada.** Veredito, tipo de defeito, comparação com o catálogo e precedentes vêm todos prontos do backend; o React só exibe e organiza. Nenhum componente recalcula score, threshold ou classificação no cliente.

## Screenshots (`docs/screenshots/`)

| Arquivo | Tela |
|---|---|
| `01-portal.png` | Portal do cliente — seleção de pedido/produto/checklist |
| `02-verdict.png` | Resultado da análise — coluna do pipeline + card de identidade + card de veredito juntos |
| `03-review.png` | Fila de revisão humana |

Capturados em 1600×1000 contra o cluster real. O nome do varejista é mascarado no DOM antes da captura (o README vende a PoV como genérica para "qualquer varejista"). O screenshot do veredito (`02-verdict.png`) mostra honestamente **inconclusivo com 35%** — a foto seedada é de catálogo, sem dano visível; é comportamento correto do sistema (a revisão humana existe exatamente para pegar isso), não uma captura para refazer.

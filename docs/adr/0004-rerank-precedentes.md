# 0004 — `$rerank` nativo sobre os precedentes; sem quantização por ora

- **Status:** aceita (2026-11-12)
- **Onde:** `backend/rag.py` (`_estagios_rerank`, `_executar`, `vector_search`, `hybrid_search`), `backend/config.py` (`RERANK_MODEL`), `backend/main.py` (passa a frase com PII mascarada), eval em `eval/run_quality.py` (seção `busca`), testes em `backend/tests/test_rerank.py`

## Contexto

Os precedentes recuperados alimentam o Claude, e o primeiro é o que o modelo mais cita. Com o corpus limpo (15 precedentes do seed), vetor e `$rankFusion` empatavam: recall@1 0,95 (19/20), recall@3 1,0, MRR 0,975. O cluster da demo roda MongoDB 9.0.7, que tem o estágio `$rerank` (Voyage, chamado pelo próprio Atlas). A ficha de avaliação também pedia quantização de vetor.

## Decisão

1. **`$rerank` no fim de `vector_search` e `hybrid_search`**, sobre `frase_analise` do top 5, com `query.text` = a frase do chamado **com PII mascarada** (o texto sai do cluster para a Voyage). O score da recuperação é guardado em `score_recuperacao` antes do estágio (o `$rerank` substitui `$meta: "score"`); `$set` garante `frase_analise` string para não quebrar o estágio.
2. **Degradação, não flag:** se o MongoDB rejeitar a agregação com `$rerank` (erro `operacao`: estágio indisponível, Voyage fora, cota), a mesma busca roda sem rerank e `funnel.rerank` diz o motivo; `timeout`, `search`, `indice` e `conexao` sobem sem repetir a consulta (repetir só dobraria a espera). `RERANK_MODEL=` vazio desliga (só para reverter).
3. **Modelo `rerank-2.5-lite`**: mesmo resultado que `rerank-2.5` no eval, menor custo.
4. **Sem quantização** (`scalar`/`binary`) nos índices por ora.

## Medição (2026-11-12, banco `*_test` resetado, 20 consultas do gabarito)

| Configuração | recall@1 | recall@3 | MRR | latência da agregação p50 |
|---|---|---|---|---|
| `$vectorSearch` | 0,95 | 1,0 | 0,975 | ~470 ms |
| `$rankFusion` | 0,95 | 1,0 | 0,975 | ~485 ms |
| `$vectorSearch` + `$rerank` | 1,0 | 1,0 | 1,0 | ~660 ms |
| `$rankFusion` + `$rerank` | 1,0 | 1,0 | 1,0 | ~675 ms |

O ganho é **um caso** (R20, que vinha em 2º): amostra pequena, sem intervalo de confiança. O custo é ~+190 ms numa análise que leva ~10 s (o Claude domina). Identidade intacta (acurácia 1,0 nos 30 casos): a ADR 0002 não usa `$rerank`.

## Por que sem quantização

Com 15 precedentes e 14 fotos de catálogo não há RAM a economizar, e a regra de identidade opera com folgas pequenas (menor margem legítima +0,035, piso 0,80 entre 0,823 e 0,839): quantizar `catalogo_fotos` pode deslocar scores perto desses limites sem ganho mensurável. Revisar quando o corpus crescer: medir recall e scores de identidade com `quantization: "scalar"` contra o eval antes de trocar.

## Consequências

- O reranker lê só texto (`frase_analise`); a imagem entra na recuperação pelo vetor, não no rerank.
- A UI mostra o badge "reordenado por $rerank (modelo)" ou o aviso de indisponível com o motivo, o título do passo de busca segue `funnel.modo`/`funnel.rerank`, e o pipeline exibido é o que rodou. O span `atlas_vector_search` do Langfuse leva `rerank` no metadata.
- Com o `$rerank` o `score` dos precedentes é relevância do reranker (0-1), não RRF; o grau de match continua relativo ao topo (`frontend/src/lib/triagem.js`).

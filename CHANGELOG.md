# Changelog

## Unreleased

- Precedent retrieval: Atlas-native `$rerank` (Voyage `rerank-2.5-lite`) reorders the top 5 of `$vectorSearch` and `$rankFusion`, using the PII-masked case phrase. Measured with `eval/run_quality.py` (20 queries, seed corpus): recall@1 0.95 → 1.0, MRR 0.975 → 1.0, about +190 ms p50 per search; identity unchanged (accuracy 1.0 on 30 cases). If MongoDB rejects the stage the same search runs without it and the UI shows why; timeouts, missing indexes and connection errors surface without a second query. The Langfuse search span records `rerank`. `RERANK_MODEL` selects or disables it.
- UI: retrieval panel shows the `$rerank` badge (or a warning with the reason); the search step title follows the mode and rerank actually used; pipeline step texts describe the two embeddings (phrase + image for precedents, image only for identity); display rules moved to `frontend/src/lib/triagem.js` with tests; an identity without a known status shows "inconclusive", never "approved".
- `POV_API_URL` points the Vite proxy at a backend on another port (default `:8100`).
- Docs: ADRs in `docs/adr/`; README states the answer key's validation status and the Python versions actually used.
- Identity check ("does the photo match the ordered product?"): embeds the image only (the case text named the claimed SKU and biased the score, approving a 6-door wardrobe photo on a 3-door order), compares the order's SKU with the best other SKU by a 0.02 margin and returns an explicit `status` (`aprovado`, `inconclusivo`, `divergente`, `sem_referencia`) with a `motivo`. A tie between variants is never approved; a SKU with no reference photo goes to review instead of `divergente`. Measured with `eval/run_quality.py` on a 30-case matrix: false acceptance 0.08 → 0, accuracy 0.767 → 1.0.
- Atualiza dependências compatíveis e pisos de segurança; alinha metadados de versão entre aplicação e frontend.
- Retira logs temporários de validação do repositório.

## 1.1.1 (2026-10-09)

- Security: with `pov-shared` >= 0.2.0 a report with more than 8 distinct clauses raised `ClauseBudgetExceeded` and was treated as "no signal" (fail-open), so an instruction hidden after many sentences was not flagged. Every clause is now scored (budget 128) and a report above the budget is flagged as suspicious. Regression tests in `tests/adversarial/test_llm_adversarial.py`.
- Docs: `scripts/bench_documento_unico.py` is described as a data-modeling comparison inside MongoDB (one document vs three collections on the same cluster), not as a floor for other databases; numbers re-measured on 2026-10-09. The script accepts `--help`.
- UI: model signals as a wrapping list (long text no longer overflows the badges); retrieved precedents show report + resolution with the full document on demand; an idempotent replay explains that retrieval was not repeated instead of an empty "0" card.
- `pov-shared` 0.2.1 (editable).

## 1.1.0 (2026-10-06)

- LLM through the Grove gateway with `pov-shared` (`AsyncGroveClient`): retry with jitter, circuit breaker, total deadline; manual-review fallback.
- Prompt safety: delimited data, PII masking before prompt/logs/traces, per-clause injection heuristic, model flag for instructions written in photos, confidence cap on alert.
- Langfuse tracing, fail-open (`langfuse>=2,<3`).
- Hostile uploads rejected by real format; decompression bombs no longer return 500; EXIF stripped.
- Atomic idempotency for parallel identical submissions; input errors return 4xx.
- `scripts/reset_demo.py` (single guarded reset), `ALLOW_DEMO_DB_WRITE` guard on every writing script.
- Adversarial test suite (unit + opt-in live) and `scripts/bench_documento_unico.py`.
- UI: manipulation alert, measured persistence of the case document, correct retrieval-mode label.
- UI: layout MongoDB 2026 "Dark Stage v4" (tokens mais escuros, Special Gothic / Source Code Pro locais, motivos de escada e grade, movimento escalonado).

## 1.0.0 (2026-09-30)

First public release.

- Repository rebuilt with a clean, single-commit history.
- English README and repository description, with screenshots captured against a real Atlas cluster.
- MIT license.
- Internal notes, presentation decks, test-output snapshots, and tooling configuration removed from the repository.

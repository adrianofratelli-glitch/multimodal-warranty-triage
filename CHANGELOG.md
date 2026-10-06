# Changelog

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

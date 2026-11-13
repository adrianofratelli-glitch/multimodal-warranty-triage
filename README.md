# Multimodal warranty triage

Mapa do código: docs/MAPA_DO_CODIGO.md

Every retailer that ships physical products receives thousands of warranty claims: a photo, a vague description ("arrived broken"), and an analyst who has to decide whether it is a factory defect, shipping damage, or misuse. Triage is slow, inconsistent between analysts, and everything already resolved stays locked in spreadsheets. Nothing even guarantees that the submitted photo shows the product that was bought.

This PoV triages the claim with multimodal AI, with MongoDB Atlas as the engine behind every layer: Voyage for embeddings, Claude for the verdict, a human for the decision.

The UI is in Brazilian Portuguese (used in customer sessions); the code and this README are in English.

## The demo in four steps

**1. The customer opens a claim.** Order number, symptom checklist, description, photo. Preloaded scenarios (including two where the photo does not match the product) make this one click.

![Warranty portal with scenario shortcuts, order, checklist, and photo](docs/screenshots/01-portal.png)

**2. Is this even the right product?** The photo becomes an embedding and is compared against the reference photos of the *entire* catalog. The signal is relative: the ordered product must be the best match among all of them. An absolute threshold alone would let the wrong product through, since studio photos score high against each other anyway.

**3. Precedents, then a structured verdict.** `$vectorSearch` (or hybrid `$rankFusion`) retrieves resolved claims similar to this one, Atlas-native `$rerank` (Voyage) reorders the top 5, and Claude classifies the probable cause with *forced tool use*: structured output, no fragile parsing of free-text JSON.

![Pipeline stages, the identity-check score, and the structured verdict with its reasoning](docs/screenshots/02-verdict.png)

The run above is a good example of the model not bluffing: the submitted photo was a catalog image with no visible damage, so the verdict came back **inconclusive with 35% confidence**, saying exactly that and asking for a photo of the real defect.

**4. A human decides.** Every verdict is born `em_analise` (under review); only a person promotes it to `resolvido` (resolved), as Brazilian consumer law requires. Each confirmed claim becomes a precedent for the next ones. The queue updates through a Change Stream, with no polling.

![Human review queue fed live by a Change Stream](docs/screenshots/03-review.png)

```mermaid
flowchart LR
    A[order + checklist + description + photo] --> B[normalize to JPEG]
    B --> C[Voyage multimodal 1024d]
    B --> D{{"identity (image only): best match in the catalog?"}}
    C --> E["precedents: $vectorSearch / $rankFusion + $rerank"]
    E --> F[Claude · forced tool use]
    F --> G[(cases · under review)]
    G --> H[human review] --> I[(resolved → becomes a precedent)]
```

> The screenshots run against a real cluster with a demonstration catalog; the retailer's name was replaced with a neutral one.

## MongoDB behind every layer

| Layer | Where it lives |
|---|---|
| Order lookup | `pedidos` |
| Defect checklist | `catalogo` |
| Claims + verdict + embedding | `chamados` |
| Catalog reference photos | `catalogo_fotos` |
| Semantic search | Vector Search (`defeitos_vector_index`) |
| Hybrid search | `$rankFusion` + Atlas Search (`chamados_text_index`) |
| Reranking | `$rerank` (Voyage `rerank-2.5-lite`, called by Atlas) over the top 5 precedents |
| Live review queue | Change Streams over SSE |
| Analytics | Aggregation Pipeline (ready for Atlas Charts) |
| Schema governance | `$jsonSchema` validators |

Image blobs stay **outside** MongoDB, the correct pattern for blobs. In the PoV they live on local disk (`backend/media/`); in production you reimplement `storage.py` with S3 + CDN and the `(uri, url)` interface does not change.

**Stack:** FastAPI + Motor · Voyage `voyage-multimodal-3.5` (1024d) · Claude with forced tool use through the Grove gateway (`pov-shared`) · React + Vite + LeafyGreen. Everything (database, collections, indexes, models) is parameterized in `.env`; see `.env.example`, and never commit a real `.env`.

## Setup

Requirements: Python 3.12+ (CI and the Docker image use 3.12; local development also runs on 3.14), Node 22, an Atlas cluster (Vector Search + Atlas Search), a Voyage key and access to the Grove gateway. Copy `.env.example` to `.env` and fill it in (placeholders only in the example; never commit the real `.env`).

```bash
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
# Every LLM call goes through the Grove gateway via pov-shared (_shared/grove_client).
# It is not on PyPI: install it from the sibling workspace folder.
uv pip install --python .venv/bin/python -e "../../_shared[llm]"
```

Seed photos: the demo-scenario photos in `frontend/public/demo/` are public catalog images. The seed reads `SEED_IMAGES_DIR` (default `seed_images/`, layout `cad_01.jpg …` and `catalogo/<sku>/1.jpg … N.jpg`) and falls back to the copies a previous seed left in `backend/media/{seed,catalogo}/`. No photos at all? `./.venv/bin/python generate_placeholders.py && ./.venv/bin/python generate_catalogo_placeholders.py`.

### Reset: one command rebuilds all demo data

```bash
# from the repo root. Takes 1-3 min (Voyage embeddings + Atlas index build).
MONGODB_DB=analise_garantia_test backend/.venv/bin/python scripts/reset_demo.py   # *_test databases: free
ALLOW_DEMO_DB_WRITE=1 backend/.venv/bin/python scripts/reset_demo.py              # the demo database
```

It is idempotent and touches only this PoV's collections (`pedidos`, `catalogo`, `chamados`, `catalogo_fotos`, `idempotencia`): orders + checklist, removes cases created during demos (their image files in `backend/media/chamados/` are kept), reseeds the 15 resolved precedents and the catalog reference photos with embeddings, recreates regular/TTL/Vector Search/Atlas Search indexes and `$jsonSchema`, then waits for the search indexes to be `READY` and validates with a real `$vectorSearch`. Every writing script (`seed*.py`, `setup_indexes.py`, `reset_demo.py`) refuses any database whose name does not end in `_test` unless `ALLOW_DEMO_DB_WRITE=1`.

## Run

```bash
./start.sh                                  # backend 127.0.0.1:8100 + frontend :5190
cd backend && ./.venv/bin/python test_http.py   # full-pipeline smoke test against the running backend
```

To test against a backend on another port without touching the demo ports: `POV_API_URL=http://127.0.0.1:18100 node_modules/.bin/vite preview --port 18190` in `frontend/` (the proxy target defaults to `:8100`).

By default the launcher serves the optimized frontend build without a watcher. For HMR editing run `POV_DEV=1 ./start.sh`; the build is only redone when sources or configuration change.

## Tests

```bash
cd backend
./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/pytest -q        # unit + adversarial suite, no Atlas or network (gateway mocked)
./.venv/bin/ruff check . ../scripts
cd ../frontend && node --test tests/*.test.mjs   # HTTP deadline + display rules (src/lib/triagem.js)

# live adversarial suite: real Atlas + Voyage + Grove, only against a *_test database
LIVE_API_URL=http://127.0.0.1:8100 backend/.venv/bin/pytest -q backend/tests/adversarial/test_live_adversarial.py
```

`backend/tests/adversarial/` covers hostile uploads (text/SVG/PDF/GIF/WebP disguised as JPEG, decompression bombs, truncated files, EXIF with GPS, traversal in names and checklist ids), NoSQL operator injection, prompt injection in the report and written inside the photo, dilution of the injection signal in a long report, PII in prompts/traces, Grove timeout/429/5xx/slow gateway, Langfuse down, parallel identical submissions and concurrent reviews. In the public CI the tests that need the private `pov-shared` package are skipped.

Docker: `docker build --build-context shared=../_shared -t warranty-triage . && docker run --env-file .env -p 18081:8080 warranty-triage`.

## Quality evaluation

`eval/run_quality.py` measures quality, not just regressions, against a small answer key (`eval/gabarito_qualidade.json`, derived from the seed; its `_status` field records the user's validation on 2026-11-12). It runs the real backend path (Voyage query embedding, `rag.vector_search` and `rag.hybrid_search` with the same `$rerank` as `/api/analisar`, `rag.verificar_identidade`) and only reads the database (search aggregations). It always exits 0 and writes a JSON report.

```bash
backend/.venv/bin/python eval/run_quality.py --out /tmp/warranty_quality.json                   # search + identity, no LLM
backend/.venv/bin/python eval/run_quality.py --secoes veredito --out /tmp/warranty_llm.json     # + 4 Claude verdicts via the gateway
```

- **Similar resolved claims:** 20 new claims (versioned photos in `frontend/public/demo/`, rewritten descriptions; 5 without checklist) whose known neighbor is a seed precedent. Recall@1, recall@3 and MRR for vector and `$rankFusion`. Each category has 5 precedents, so recall@5 is trivially 1.0. Measured on 2026-11-12 on the seed corpus: recall@1 0.95 → 1.0 and MRR 0.975 → 1.0 for both modes after adding `$rerank` (one case moved from 2nd to 1st; small sample), at about +190 ms p50 per search. Cases reviewed during demos also become precedents and are reported as `corpus_fora_do_seed`; run the eval after `scripts/reset_demo.py` for comparable numbers.
- **Does the photo match the product?** The full matrix of the 5 demo photos × 6 order SKUs (30 cases: 5 correct, 4 close variant of the same category, 16 other category, 5 SKU without a catalog photo): accuracy, false rejection and false acceptance of `rag.decidir_identidade`. The check embeds the image only (the case text names the claimed SKU and biased the score) and compares the order's SKU with the best other SKU in the whole catalog: margin ≤ −0.02 → `divergente`; |margin| < 0.02 → `inconclusivo` (review; a tie between variants is never approved); otherwise score < 0.80 → `inconclusivo`; otherwise `aprovado`. A SKU with no reference photo returns `sem_referencia` (human review), not `divergente`. Measured on 2026-11-12: accuracy 1.0, false acceptance 0, false rejection 0 (the previous rule: 0.767 / 0.08 / 0 on the same 30 cases). Small sample: changing a threshold requires re-running the eval.
- **Suggested cause (optional, LLM):** the verdict is valid (not the manual-review fallback) and its cause is the precedent's or `inconclusivo`.

### Verdict and extended-search evals (draft answer keys)

Two more evals use answer keys marked **RASCUNHO** (draft: not yet labeled by a human, so they have no floor in the weekly eval). The validated key above is unchanged.

```bash
backend/.venv/bin/python eval/run_veredito.py --rodadas 2 --juiz --out /tmp/warranty_veredito.json   # 24 verdicts x 2 via the gateway (+ judge)
backend/.venv/bin/python eval/run_veredito.py --reavaliar /tmp/warranty_veredito.json                # re-run only the deterministic checks
backend/.venv/bin/python eval/run_busca_ampliada.py --out /tmp/warranty_busca_ampliada.json          # 21 extra search queries, no LLM
```

- **Verdict** (`eval/gabarito_veredito.draft.json`, 24 cases): the Portal path (`$rankFusion` + `$rerank`, injection heuristic, Claude with forced tool use). The decision follows the warranty policy shown to reviewers (factory or shipping defect → approved, misuse → denied, inconclusive → human review). Deterministic checks first: valid verdict, acceptable and strict decision, approved-vs-denied flips, claims about precedents/scores/case numbers that were not retrieved, rationale consistent with the cause, injection flagged where expected. A second model through the gateway acts as a judge (no image) and its agreement is reported. Retrieval runs once, so the round-to-round spread is the model's. Measured on 2026-11-13 (`claude-sonnet-4-6`, 2 rounds): valid 1.0, acceptable decision 1.0, strict decision 0.625 / 0.583 (demo photos show no visible defect, so ~10 cases go to human review), 0 flips, 0 unsupported claims, rationale consistent 1.0, injection flagged 2/2, judge agreement 1.0; same cause and decision in 23/24 cases (max confidence spread 0.27). Details in `docs/adr/0005-eval-veredito.md`.
- **Extended search** (`eval/gabarito_busca_ampliada.draft.json`, 21 queries): photo only, photo of another variant, vague report, checklist only, product outside the catalog, English, typos, checklist contradicting the report, noisy report. Recall@1 and MRR 1.0 on the 19 queries with a relevant precedent; an unknown category returns no precedents and an unknown SKU gets identity `sem_referencia`. Vague and photo-only queries are technical ties (top-1/top-2 rerank gap 0.002–0.098 vs ≥ 0.17 for specific queries).

## Resilience and observability (on by default)

- **Reranking:** if MongoDB rejects the aggregation with `$rerank` (stage unavailable, Voyage down, quota), the same search runs without it and the UI shows the reason; timeouts, missing indexes and connection errors still surface without re-running the query. The query text sent to the reranker is the PII-masked phrase. `RERANK_MODEL` (default `rerank-2.5-lite`; empty disables) selects the model.

- **LLM:** `_shared/grove_client.AsyncGroveClient` (Bearer + real key in `x-api-key`), retries with jitter on 429/5xx/timeouts, circuit breaker and optional model fallback, plus a total deadline (`LLM_DEADLINE_SECONDS`, 90 s). If the gateway still fails, the case is kept with an `inconclusivo` manual-review verdict instead of an error. There is no direct-provider fallback.
- **Voyage:** 30 s timeout, 3 attempts with exponential backoff, total deadline per embedding.
- **MongoDB:** server-selection/connect/socket timeouts, retryable reads and writes, `maxTimeMS` on reads; every driver error becomes a readable `{error: {kind, message}}` (input errors 4xx, infrastructure 503).
- **Prompt safety:** the customer report and precedents are sent as delimited data with PII masked; an offline heuristic scores the report as a whole and per clause (no dilution); the model flags instructions it sees in the report or written in the photo. On any alert the confidence is capped at 50% and the reviewer sees why.
- **Langfuse** (optional): set `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_HOST`. Fail-open, one trace per analysis created after PII masking, no image bytes or vectors.

## Why one document per case (measured)

Metadata, the 1024-float vector, the identity check, the verdict and the photo reference live in a single `chamados` document, written with one insert plus one update. The portal shows the document size and the real insert/update time of every analysis.

`scripts/bench_documento_unico.py` is a data-modeling comparison inside MongoDB, not a competitive benchmark: it writes and reads the same case as one document and as three collections (metadata, vector, verdict) on the same cluster, with the same driver, to show the round-trip cost of splitting the case and the extra cost of making the split atomic with a multi-document transaction. It does not measure any other database and is not a floor or ceiling for other architectures.

```bash
MONGODB_DB=<db>_test backend/.venv/bin/python scripts/bench_documento_unico.py 30
```

Measured on 2026-10-09, N=30, demo cluster from a laptop (results depend on schema, cluster and network):

| Model | Operation | p50 | p95 |
|---|---|---|---|
| One document | write, 1 op | 386.8 ms | 391.6 ms |
| One document | read, 1 op | 379.2 ms | 385.6 ms |
| Three collections | write, 3 ops (not atomic) | 854.6 ms | 893.7 ms |
| Three collections | write, 3 ops in a transaction | 1075.1 ms | 1097.6 ms |
| Three collections | read, 3 ops | 701.8 ms | 733.3 ms |

## Architecture decisions

Short ADRs in [`docs/adr/`](docs/adr/README.md): one document per case, image-only relative identity check, application-side multimodal embeddings (no autoEmbed), and `$rerank` on precedents without vector quantization for now (with the measurements behind each).

## Endpoints

| Method | Route | What |
|---|---|---|
| POST | `/api/lookup` | order → products |
| GET | `/api/checklist/{categoria}` | checklist items |
| POST | `/api/analisar` | full pipeline; `modo=vector` or `hybrid` |
| GET | `/api/chamados/pendentes` | review queue |
| POST | `/api/revisar` | human review → resolved |
| GET | `/api/analytics` | aggregations |
| GET | `/api/chamados/stream` | Change Stream (SSE) |
| GET | `/api/health` · `/api/metrics` | ping + counts · latency, tokens |

## Production boundary

Uploads are limited by bytes, pixel count, number of images, and description length; the real file format (not the declared MIME type) must be JPEG or PNG, EXIF metadata is stripped, the uploaded file name is never used, and checklist IDs and storage paths go through an allowlist. The image runs as UID 10001 behind an nginx configuration with security headers. Authentication is intentionally outside this PoV: expose it only behind an IdP/API gateway with TLS, request quotas, and object storage in place of the local media directory.

## License

MIT, see [LICENSE](LICENSE).

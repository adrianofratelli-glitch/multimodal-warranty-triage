#!/usr/bin/env python3
"""Eval de qualidade da triagem: busca de precedentes, checagem de identidade e (opcional) veredito.

Mede o caminho real do backend (`voyage.embed_multimodal` com input_type="query", `rag.vector_search`,
`rag.hybrid_search` com o mesmo `$rerank` do /api/analisar (texto com PII mascarada) e `rag.verificar_identidade`) contra o gabarito `eval/gabarito_qualidade.json`
(validado pelo usuário em 2026-11-12, derivado do seed). Só LÊ o banco configurado no `.env` (agregações de busca); não grava nada.

    backend/.venv/bin/python eval/run_quality.py --out /tmp/warranty_quality.json
    backend/.venv/bin/python eval/run_quality.py --secoes veredito --out /tmp/warranty_llm.json  # Claude via Grove

Seções:
- busca: recall@1, recall@3 e MRR do chamado do seed esperado (vector e hybrid/$rankFusion).
- identidade: regra de rag.decidir_identidade com o vetor só da imagem (foto confere com o SKU do
  pedido?): acerto (status entre os aceitáveis do caso), falsa rejeição (foto certa não aprovada) e falsa
  aceitação (foto errada ou sem referência aprovada).
- veredito (tier llm, poucos casos): o Claude devolve veredito válido (não caiu no fallback) e a causa
  está entre as aceitáveis do gabarito (a do precedente ou "inconclusivo").

Custo: busca+identidade = ~25 embeddings Voyage (20 frase+foto, 5 só-imagem) (centavos) + agregações no Atlas; veredito = 4 chamadas
ao Claude via Grove. Exit 0 sempre: quem decide é o piso do eval semanal.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
GABARITO = Path(__file__).resolve().parent / "gabarito_qualidade.json"
SECOES = ("busca", "identidade", "veredito")


# --------------------------------------------------------------------------- funções puras (testadas)


def rank_of(ranking: list[str], relevantes: list[str]) -> int | None:
    """Posição (1-based) do primeiro relevante no ranking, ou None."""
    for i, nc in enumerate(ranking, 1):
        if nc in relevantes:
            return i
    return None


def retrieval_metrics(ranks: list[int | None]) -> dict:
    n = len(ranks)
    if not n:
        return {"n": 0, "recall_at_1": 0.0, "recall_at_3": 0.0, "mrr": 0.0}
    return {
        "n": n,
        "recall_at_1": round(sum(1 for r in ranks if r is not None and r <= 1) / n, 4),
        "recall_at_3": round(sum(1 for r in ranks if r is not None and r <= 3) / n, 4),
        "mrr": round(sum(1 / r for r in ranks if r) / n, 4),
    }


STATUS_IDENTIDADE = ("aprovado", "inconclusivo", "divergente", "sem_referencia")


def identity_metrics(casos: list[tuple]) -> dict:
    """casos = [(esperado, obtido)] ou [(esperado, obtido, aceitaveis)].

    esperado/obtido em aprovado | inconclusivo | divergente | sem_referencia (ou "erro").
    - accuracy: obtido está entre os aceitáveis do caso (padrão: só o esperado);
    - falsa_rejeicao: foto legítima (esperado aprovado) que não saiu aprovada;
    - falsa_aceitacao: foto que não deveria ser aprovada (qualquer outro esperado) e saiu aprovada.
    """
    norm = [(c[0], c[1], list(c[2]) if len(c) > 2 and c[2] else [c[0]]) for c in casos]
    n = len(norm)
    legit = [o for e, o, _ in norm if e == "aprovado"]
    outros = [o for e, o, _ in norm if e != "aprovado"]
    return {
        "n": n,
        "accuracy": round(sum(1 for _, o, a in norm if o in a) / n, 4) if n else 0.0,
        "falsa_rejeicao": round(sum(1 for o in legit if o != "aprovado") / len(legit), 4) if legit else 0.0,
        "falsa_aceitacao": round(sum(1 for o in outros if o == "aprovado") / len(outros), 4) if outros else 0.0,
        "inconclusivo": sum(1 for _, o, _ in norm if o == "inconclusivo"),
        "sem_referencia": sum(1 for _, o, _ in norm if o == "sem_referencia"),
    }


def validar_gabarito(gab: dict, produtos: dict[str, dict], catalogo: dict[str, dict], seed_ids: set[str]) -> list[str]:
    """Erros estruturais do gabarito (SKU, checklist, relevantes e imagem existentes)."""
    erros = []
    ids = [c["id"] for c in gab.get("busca", []) + gab.get("identidade", [])]
    if len(ids) != len(set(ids)):
        erros.append("ids duplicados")
    for c in gab.get("busca", []):
        p = produtos.get(c["sku"])
        if not p:
            erros.append(f"{c['id']}: sku desconhecido {c['sku']}")
            continue
        itens = catalogo.get(p["categoria"], {})
        erros += [f"{c['id']}: item {i} fora do checklist de {p['categoria']}" for i in c["checklist"] if i not in itens]
        erros += [f"{c['id']}: relevante {r} fora do seed" for r in c["relevantes"] if r not in seed_ids]
        if not (ROOT / c["imagem"]).exists():
            erros.append(f"{c['id']}: imagem ausente {c['imagem']}")
    for c in gab.get("identidade", []):
        p = produtos.get(c["sku_pedido"])
        if not p:
            erros.append(f"{c['id']}: sku desconhecido {c['sku_pedido']}")
            continue
        itens = catalogo.get(p["categoria"], {})
        erros += [f"{c['id']}: item {i} fora do checklist de {p['categoria']}" for i in c.get("checklist", []) if i not in itens]
        if c["esperado"] not in STATUS_IDENTIDADE:
            erros.append(f"{c['id']}: esperado invalido {c['esperado']}")
        aceitaveis = c.get("aceitaveis", [c["esperado"]])
        if c["esperado"] not in aceitaveis or not set(aceitaveis) <= set(STATUS_IDENTIDADE):
            erros.append(f"{c['id']}: aceitaveis invalidos {aceitaveis}")
        if c["esperado"] != "aprovado" and "aprovado" in aceitaveis:
            erros.append(f"{c['id']}: caso nao legitimo nao pode aceitar 'aprovado'")
        if not (ROOT / c["imagem"]).exists():
            erros.append(f"{c['id']}: imagem ausente {c['imagem']}")
    return erros


def _r4(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


def veredito_ok(veredito: dict, aceitaveis: list[str]) -> tuple[bool, bool]:
    """(válido, causa aceitável). Válido = veio do modelo (não do fallback) e respeita o contrato."""
    meta = veredito.get("_meta", {})
    valido = (
        meta.get("mode") != "manual_review_fallback"
        and veredito.get("classificacao") in {"defeito_fabrica", "defeito_transporte", "mau_uso", "inconclusivo"}
        and veredito.get("revisao_humana") is True
        and bool(str(veredito.get("racional", "")).strip())
    )
    return valido, valido and veredito.get("classificacao") in aceitaveis


# --------------------------------------------------------------------------- execução real


def _carregar_backend():
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    import config  # noqa: F401
    from defeitos_catalog import CATALOGO_DEFEITOS
    from pedidos_data import PEDIDOS_SEED
    from seed_data import CHAMADOS_SEED

    produtos = {it["sku"]: it for itens in PEDIDOS_SEED.values() for it in itens}
    return produtos, CATALOGO_DEFEITOS, {c["numero_chamado"] for c in CHAMADOS_SEED}


def _imagem(rel: str):
    """Mesmo contrato do upload: EXIF aplicado, RGB, JPEG; os mesmos bytes vão para Voyage e Claude."""
    from PIL import Image, ImageOps

    with Image.open(ROOT / rel) as src:
        pil = ImageOps.exif_transpose(src).convert("RGB")
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=90)
    jpeg = buf.getvalue()
    return Image.open(io.BytesIO(jpeg)).convert("RGB"), jpeg


async def _run(secoes: list[str], gab: dict) -> dict:
    produtos, catalogo, seed_ids = _carregar_backend()
    import rag
    from db import chamados
    from defeitos_catalog import compor_frase
    from guardrails_triagem import mascarar_pii
    from voyage import embed_multimodal

    out: dict = {"erros_gabarito": validar_gabarito(gab, produtos, catalogo, seed_ids), "casos": []}
    erros = 0
    cache: dict[tuple[str, str], list[float]] = {}

    async def embed(frase: str, img_rel: str) -> list[float]:
        key = (frase, img_rel)
        if key not in cache:
            pil, _ = _imagem(img_rel)
            cache[key] = await asyncio.to_thread(embed_multimodal, frase, pil, "query")
        return cache[key]

    def frase_de(sku: str, checklist: list[str], descricao: str) -> tuple[str, str]:
        p = produtos[sku]
        return compor_frase({"categoria": p["categoria"], "produto": {"sku": sku, "nome": p["nome"]},
                             "checklist": checklist, "descricao_cliente": descricao}), p["categoria"]

    # corpus: quantos precedentes resolvidos existem e quantos não são do seed (demos revisadas)
    resolvidos = await chamados().distinct("numero_chamado", {"status": "resolvido"})
    out["corpus"] = {"resolvidos": len(resolvidos), "fora_do_seed": len(set(resolvidos) - seed_ids),
                     "seed_ausente": len(seed_ids - set(resolvidos))}

    if "busca" in secoes:
        ranks: dict[str, list] = {"vector": [], "hybrid": []}
        fallback_hibrido = 0
        rerank_aplicado = 0
        for c in gab["busca"]:
            frase, cat = frase_de(c["sku"], c["checklist"], c["descricao"])
            row = {"secao": "busca", "id": c["id"], "relevantes": c["relevantes"]}
            try:
                qv = await embed(frase, c["imagem"])
                # mesmo caminho do /api/analisar: $rerank com a frase mascarada
                docs_v, funnel_v = await rag.vector_search(qv, cat, texto_rerank=mascarar_pii(frase))
                docs_h, funnel_h = await rag.hybrid_search(qv, frase, cat, texto_rerank=mascarar_pii(frase))
                if funnel_h.get("modo") != "hybrid":
                    fallback_hibrido += 1
                rerank_aplicado += sum(1 for f in (funnel_v, funnel_h) if f.get("rerank", {}).get("aplicado"))
                for modo, docs in (("vector", docs_v), ("hybrid", docs_h)):
                    ranking = [d["numero_chamado"] for d in docs]
                    r = rank_of(ranking, c["relevantes"])
                    ranks[modo].append(r)
                    row[modo] = {"rank": r, "top3": ranking[:3]}
            except Exception as exc:  # noqa: BLE001 — caso com erro conta como miss
                erros += 1
                ranks["vector"].append(None)
                ranks["hybrid"].append(None)
                row["erro"] = f"{type(exc).__name__}: {exc}"[:200]
            out["casos"].append(row)
        out["busca"] = {m: retrieval_metrics(v) for m, v in ranks.items()}
        out["busca"]["hybrid_fallback"] = fallback_hibrido
        out["busca"]["rerank_aplicado"] = rerank_aplicado  # de 2 x n buscas

    if "identidade" in secoes:
        from voyage import embed_imagem

        cache_img: dict[str, list[float]] = {}
        pares = []
        for c in gab["identidade"]:
            cat = produtos[c["sku_pedido"]]["categoria"]
            aceitaveis = c.get("aceitaveis", [c["esperado"]])
            row = {"secao": "identidade", "id": c["id"], "esperado": c["esperado"], "aceitaveis": aceitaveis}
            try:
                # Mesmo caminho do /api/analisar: identidade com o vetor só da imagem.
                if c["imagem"] not in cache_img:
                    pil, _ = _imagem(c["imagem"])
                    cache_img[c["imagem"]] = await asyncio.to_thread(embed_imagem, pil, "query")
                ident = await rag.verificar_identidade(cache_img[c["imagem"]], c["sku_pedido"], cat)
                obtido = ident["status"]
                row.update(obtido=obtido, score=_r4(ident["score"]), concorrente_sku=ident["concorrente_sku"],
                           concorrente_score=_r4(ident["concorrente_score"]), margem=_r4(ident["margem"]),
                           top_sku=ident["top_sku"])
            except Exception as exc:  # noqa: BLE001
                erros += 1
                obtido = "erro"
                row.update(obtido=obtido, erro=f"{type(exc).__name__}: {exc}"[:200])
            pares.append((c["esperado"], obtido, aceitaveis))
            out["casos"].append(row)
        out["identidade"] = identity_metrics(pares)
        out["embeddings_voyage_imagem"] = len(cache_img)

    if "veredito" in secoes:
        from llm import MODEL, analisar_veredito

        validos = aceitos = 0
        llm_cases = [c for c in gab["busca"] if c.get("llm")]
        for c in llm_cases:
            frase, cat = frase_de(c["sku"], c["checklist"], c["descricao"])
            row = {"secao": "veredito", "id": c["id"], "aceitaveis": c["llm"]["aceitaveis"]}
            try:
                qv = await embed(frase, c["imagem"])
                precedentes, _ = await rag.vector_search(qv, cat, texto_rerank=mascarar_pii(frase))
                _, jpeg = _imagem(c["imagem"])
                v = await analisar_veredito(jpeg, "image/jpeg", mascarar_pii(frase), precedentes)
                ok, aceito = veredito_ok(v, c["llm"]["aceitaveis"])
                validos += ok
                aceitos += aceito
                row.update(classificacao=v.get("classificacao"), confianca=v.get("confianca"),
                           modo=v.get("_meta", {}).get("mode"), valido=ok, aceito=aceito)
            except Exception as exc:  # noqa: BLE001
                erros += 1
                row["erro"] = f"{type(exc).__name__}: {exc}"[:200]
            out["casos"].append(row)
        n = len(llm_cases)
        out["veredito"] = {"n": n, "model": MODEL,
                           "valido_rate": round(validos / n, 4) if n else 0.0,
                           "causa_aceitavel_rate": round(aceitos / n, 4) if n else 0.0}

    out["erros"] = erros
    out["embeddings_voyage"] = len(cache)
    return out


def summarize(res: dict) -> dict:
    s: dict = {"errors": res.get("erros", 0), "gabarito_erros": len(res.get("erros_gabarito", []))}
    if "busca" in res:
        for modo in ("vector", "hybrid"):
            for k in ("recall_at_1", "recall_at_3", "mrr"):
                s[f"{modo}_{k}"] = res["busca"][modo][k]
        s["busca_n"] = res["busca"]["vector"]["n"]
        s["hybrid_fallback"] = res["busca"]["hybrid_fallback"]
        s["rerank_aplicado"] = res["busca"].get("rerank_aplicado", 0)
    if "identidade" in res:
        for k in ("accuracy", "falsa_rejeicao", "falsa_aceitacao", "inconclusivo", "sem_referencia"):
            s[f"identidade_{k}"] = res["identidade"].get(k, 0)
        s["identidade_n"] = res["identidade"]["n"]
    if "veredito" in res:
        s["veredito_valido_rate"] = res["veredito"]["valido_rate"]
        s["veredito_causa_aceitavel_rate"] = res["veredito"]["causa_aceitavel_rate"]
        s["veredito_n"] = res["veredito"]["n"]
    if "corpus" in res:
        s["corpus_fora_do_seed"] = res["corpus"]["fora_do_seed"]
        s["corpus_seed_ausente"] = res["corpus"]["seed_ausente"]
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "eval" / "reports" / "quality_latest.json"))
    ap.add_argument("--secoes", default="busca,identidade", help="subconjunto de busca,identidade,veredito")
    ap.add_argument("--gabarito", default=str(GABARITO))
    args = ap.parse_args(argv)
    secoes = [s.strip() for s in args.secoes.split(",") if s.strip()]
    if not set(secoes) <= set(SECOES):
        print(f"secoes invalidas: {args.secoes}", file=sys.stderr)
        return 0
    gab = json.loads(Path(args.gabarito).read_text(encoding="utf-8"))
    t0 = time.time()
    try:
        res = asyncio.run(_run(secoes, gab))
    except Exception as exc:  # noqa: BLE001 — falha geral (Atlas fora, .env ausente): JSON com erro, exit 0
        res = {"erros": 1, "falha": f"{type(exc).__name__}: {exc}"[:300]}
    res["summary"] = summarize(res)
    res["meta"] = {"secoes": secoes, "gabarito": Path(args.gabarito).name, "status_gabarito": gab.get("_status"),
                   "elapsed_s": round(time.time() - t0, 1), "gerado_em": datetime.now(UTC).isoformat()}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False))
    for e in res.get("erros_gabarito", []):
        print(f"gabarito: {e}", file=sys.stderr)
    if res.get("falha"):
        print(f"falha: {res['falha']}", file=sys.stderr)
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

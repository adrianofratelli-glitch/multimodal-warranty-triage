#!/usr/bin/env python3
"""Eval ampliado da busca de precedentes (gabarito RASCUNHO, separado do validado).

Cobre o que as 20 consultas de `eval/gabarito_qualidade.json` não cobrem: só foto (sem relato nem
checklist), foto de outra variante da mesma categoria, relato vago, só checklist, produto fora do catálogo
(categoria inexistente e SKU inexistente), relato em inglês, com erros de digitação, contraditório com o
checklist e com ruído. Mesmo caminho do /api/analisar (`embed_multimodal` com input_type="query",
`vector_search` e `hybrid_search` com `$rerank` sobre a frase mascarada; identidade com o vetor só da
imagem). Só LÊ o banco. Métricas por tipo de consulta; o gabarito validado continua em `run_quality.py`.

    backend/.venv/bin/python eval/run_busca_ampliada.py --out /tmp/warranty_busca_ampliada.json

Custo: ~21 embeddings multimodais + ~5 só-imagem (Voyage) e as agregações no Atlas. Exit 0 sempre.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_quality as rq  # noqa: E402

GABARITO = Path(__file__).resolve().parent / "gabarito_busca_ampliada.draft.json"
# Diferença de score ($rerank) entre o 1º e o 2º precedente abaixo da qual o top-1 é um empate técnico.
# Medido em 2026-11-13: consultas vagas/só foto <= 0,098; específicas >= 0,17 (exceto a contraditória).
GAP_AMBIGUO = 0.1


def validar(gab: dict, produtos: dict, catalogo: dict, seed_ids: set[str]) -> list[str]:
    """Erros estruturais: ids únicos, imagem existe, relevante no seed, item no checklist da categoria."""
    erros = []
    ids = [c["id"] for c in gab.get("casos", [])]
    if len(ids) != len(set(ids)):
        erros.append("ids duplicados")
    for c in gab.get("casos", []):
        cat = produtos.get(c["sku"], {}).get("categoria") or c.get("categoria")
        if not cat:
            erros.append(f"{c['id']}: sem categoria para {c['sku']}")
            continue
        if c.get("esperado_vazio"):
            if cat in catalogo:
                erros.append(f"{c['id']}: esperado_vazio exige categoria fora do catalogo ({cat})")
            if c["relevantes"]:
                erros.append(f"{c['id']}: esperado_vazio nao tem relevantes")
        elif not c["relevantes"]:
            erros.append(f"{c['id']}: sem relevantes")
        itens = catalogo.get(cat, {})
        erros += [f"{c['id']}: item {i} fora do checklist de {cat}" for i in c["checklist"] if i not in itens]
        erros += [f"{c['id']}: relevante {r} fora do seed" for r in c["relevantes"] if r not in seed_ids]
        if not (ROOT / c["imagem"]).exists():
            erros.append(f"{c['id']}: imagem ausente {c['imagem']}")
    return erros


def agregar(linhas: list[dict]) -> dict:
    """Por modo: recall@1/@3 e MRR nos casos com relevantes; acerto do vazio; erros."""
    out: dict = {"n": len(linhas)}
    com_rel = [x for x in linhas if not x.get("esperado_vazio")]
    vazios = [x for x in linhas if x.get("esperado_vazio")]
    for modo in ("vector", "hybrid"):
        out[modo] = rq.retrieval_metrics([x.get(modo, {}).get("rank") for x in com_rel])
        if vazios:
            out[modo]["vazio_ok_rate"] = round(
                sum(1 for x in vazios if x.get(modo, {}).get("retrieved") == 0) / len(vazios), 4)
        gaps = [x[modo]["gap_top1_top2"] for x in com_rel
                if isinstance(x.get(modo), dict) and x[modo].get("gap_top1_top2") is not None]
        if gaps:  # diagnóstico: consulta específica separa o top-1; vaga empata (gap pequeno)
            out[modo]["gap_top1_top2_min"] = round(min(gaps), 4)
            out[modo]["gap_top1_top2_medio"] = round(sum(gaps) / len(gaps), 4)
            out[modo]["ambiguas"] = sum(1 for g in gaps if g < GAP_AMBIGUO)
    ident = [x for x in linhas if "identidade_esperada" in x]
    if ident:
        out["identidade_ok_rate"] = round(sum(1 for x in ident if x.get("identidade") == x["identidade_esperada"]) / len(ident), 4)
    out["erros"] = sum(1 for x in linhas if x.get("erro"))
    return out


async def _run(gab: dict) -> dict:
    produtos, catalogo, seed_ids = rq._carregar_backend()
    import rag
    from defeitos_catalog import compor_frase
    from guardrails_triagem import mascarar_pii
    from voyage import embed_imagem, embed_multimodal

    linhas = []
    for c in gab["casos"]:
        p = produtos.get(c["sku"]) or {"categoria": c.get("categoria"), "nome": c.get("nome", c["sku"])}
        cat = p["categoria"]
        frase = compor_frase({"categoria": cat, "produto": {"sku": c["sku"], "nome": p["nome"]},
                              "checklist": c["checklist"], "descricao_cliente": c["descricao"]})
        row = {"id": c["id"], "tipo": c["tipo"], "relevantes": c["relevantes"]}
        if c.get("esperado_vazio"):
            row["esperado_vazio"] = True
        if c.get("identidade_esperada"):
            row["identidade_esperada"] = c["identidade_esperada"]
        try:
            pil, _ = rq._imagem(c["imagem"])
            qv = await asyncio.to_thread(embed_multimodal, frase, pil, "query")
            docs_v, f_v = await rag.vector_search(qv, cat, texto_rerank=mascarar_pii(frase))
            docs_h, f_h = await rag.hybrid_search(qv, frase, cat, texto_rerank=mascarar_pii(frase))
            for modo, docs, f in (("vector", docs_v, f_v), ("hybrid", docs_h, f_h)):
                ranking = [d["numero_chamado"] for d in docs]
                scores = [round(float(d.get("score") or 0.0), 4) for d in docs]
                row[modo] = {"rank": rq.rank_of(ranking, c["relevantes"]) if c["relevantes"] else None,
                             "retrieved": len(docs), "top3": ranking[:3], "scores_top3": scores[:3],
                             "gap_top1_top2": round(scores[0] - scores[1], 4) if len(scores) > 1 else None,
                             "modo": f.get("modo"), "rerank": f.get("rerank", {}).get("aplicado")}
            if c.get("identidade_esperada"):
                iv = await asyncio.to_thread(embed_imagem, pil, "query")
                ident = await rag.verificar_identidade(iv, c["sku"], cat)
                row["identidade"] = ident["status"]
        except Exception as exc:  # noqa: BLE001 — caso com erro conta como miss
            row["erro"] = f"{type(exc).__name__}: {exc}"[:200]
        linhas.append(row)

    por_tipo = {t: agregar([x for x in linhas if x["tipo"] == t]) for t in sorted({x["tipo"] for x in linhas})}
    return {"erros_gabarito": validar(gab, produtos, catalogo, seed_ids), "total": agregar(linhas),
            "por_tipo": por_tipo, "casos": linhas}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "eval" / "reports" / "busca_ampliada_latest.json"))
    ap.add_argument("--gabarito", default=str(GABARITO))
    args = ap.parse_args(argv)
    gab = json.loads(Path(args.gabarito).read_text(encoding="utf-8"))
    t0 = time.time()
    try:
        res = asyncio.run(_run(gab))
    except Exception as exc:  # noqa: BLE001
        res = {"falha": f"{type(exc).__name__}: {exc}"[:300]}
    res["meta"] = {"gabarito": Path(args.gabarito).name, "status_gabarito": gab.get("_status"),
                   "elapsed_s": round(time.time() - t0, 1), "gerado_em": datetime.now(UTC).isoformat()}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if "total" in res:
        print("total:", json.dumps(res["total"], ensure_ascii=False))
        for t, m in res["por_tipo"].items():
            print(f"{t}:", json.dumps(m, ensure_ascii=False))
    for e in res.get("erros_gabarito", []):
        print(f"gabarito: {e}", file=sys.stderr)
    if res.get("falha"):
        print(f"falha: {res['falha']}", file=sys.stderr)
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

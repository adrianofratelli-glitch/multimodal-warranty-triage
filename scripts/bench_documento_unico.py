#!/usr/bin/env python3
"""Mede, no cluster real, o custo de persistir/ler um chamado como UM documento
versus o mesmo chamado modelado em três coleções (metadados, vetor, veredito).

    MONGODB_DB=<banco>_test backend/.venv/bin/python scripts/bench_documento_unico.py [N]

É uma comparação de MODELAGEM dentro do MongoDB, no mesmo cluster e com o mesmo
driver: quantos round trips cada desenho exige e quanto custa tornar o desenho
em três coleções atômico (transação multi-documento). Não mede nenhum outro
produto e não serve de piso nem de teto para outra arquitetura: um banco
relacional com extensão vetorial, por exemplo, também guarda vetor, metadados e
veredito juntos. Os números valem para este esquema, este cluster e esta rede.

Grava só em coleções `bench_*` do banco *_test e as remove no fim.
"""

import random
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import config  # noqa: E402
from demo_guard import exigir_permissao_de_escrita  # noqa: E402


def _doc(i: int) -> dict:
    return {
        "numero_chamado": f"BENCH-{i:05d}",
        "numero_pedido": "PED-90001",
        "produto": {"sku": "CAD-OFF-PRO", "nome": "Cadeira Office Pro"},
        "categoria": "cadeira",
        "checklist": ["perna_quebrada"],
        "descricao_cliente": "Perna traseira trincada, caixa amassada num canto.",
        "embedding": [random.random() for _ in range(config.EMBEDDING_DIM)],
        "identidade_produto": {"sku": "CAD-OFF-PRO", "score": 0.93, "top_sku": "CAD-OFF-PRO", "abaixo_threshold": False},
        "veredito": {"classificacao": "defeito_transporte", "confianca": 0.7, "racional": "trinca", "revisao_humana": True},
        "status": "em_analise",
        "created_at": datetime.now(UTC),
    }


def _ms(fn) -> float:
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


def _stats(xs: list[float]) -> str:
    xs = sorted(xs)
    p95 = xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]
    return f"p50 {statistics.median(xs):6.1f} ms · p95 {p95:6.1f} ms"


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    if not config.DB_NAME.endswith("_test"):
        sys.exit("bench grava dados: rode com MONGODB_DB=<banco>_test")
    exigir_permissao_de_escrita("bench_documento_unico.py")
    from pymongo import MongoClient

    client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=10_000)
    db = client[config.DB_NAME]
    unico, meta, vet, ver = db.bench_unico, db.bench_meta, db.bench_vetor, db.bench_veredito
    for c in (unico, meta, vet, ver):
        c.drop()
        c.create_index("numero_chamado", unique=True)

    w1, r1, w3, w3tx, r3 = [], [], [], [], []
    for i in range(n):
        d = _doc(i)
        w1.append(_ms(lambda d=d: unico.insert_one(dict(d))))
        r1.append(_ms(lambda d=d: unico.find_one({"numero_chamado": d["numero_chamado"]})))

        m = {k: v for k, v in d.items() if k not in ("embedding", "veredito", "identidade_produto")}
        v = {"numero_chamado": d["numero_chamado"], "embedding": d["embedding"]}
        e = {"numero_chamado": d["numero_chamado"], "veredito": d["veredito"], "identidade": d["identidade_produto"]}
        w3.append(_ms(lambda m=m, v=v, e=e: (meta.insert_one(dict(m)), vet.insert_one(dict(v)), ver.insert_one(dict(e)))))

        num = f"BENCH-TX-{i:05d}"

        def tx(m=m, v=v, e=e, num=num):
            with client.start_session() as s, s.start_transaction():
                meta.insert_one({**m, "numero_chamado": num}, session=s)
                vet.insert_one({**v, "numero_chamado": num}, session=s)
                ver.insert_one({**e, "numero_chamado": num}, session=s)
        w3tx.append(_ms(tx))
        r3.append(_ms(lambda d=d: [c.find_one({"numero_chamado": d["numero_chamado"]}) for c in (meta, vet, ver)]))

    print(f"N={n} chamados · banco {config.DB_NAME} · vetor {config.EMBEDDING_DIM}d")
    print(f"documento único   escrita 1 op         {_stats(w1)}")
    print(f"documento único   leitura 1 op         {_stats(r1)}")
    print(f"3 coleções        escrita 3 ops        {_stats(w3)}  (sem atomicidade)")
    print(f"3 coleções        escrita 3 ops + tx   {_stats(w3tx)}  (atômica)")
    print(f"3 coleções        leitura 3 ops        {_stats(r3)}")
    for c in (unico, meta, vet, ver):
        c.drop()


if __name__ == "__main__":
    main()

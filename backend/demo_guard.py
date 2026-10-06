"""Guarda de escrita: scripts que gravam dado só rodam livres em banco `*_test`.

Qualquer outro nome de banco é tratado como o banco da demo e exige
`ALLOW_DEMO_DB_WRITE=1` explícito. Vale para seed.py, seed_meta.py,
seed_catalogo_fotos.py, setup_indexes.py e scripts/reset_demo.py.
"""

import os
import sys

import config

# Fallback das fotos de seed: as cópias já normalizadas que um seed anterior gravou
# em backend/media/{seed,catalogo}/ (independe de MEDIA_ROOT, que pode apontar para
# outra pasta num banco de teste).
REPO_MEDIA = config.Path(__file__).resolve().parent / "media"


def is_test_db(name: str) -> bool:
    return name.endswith("_test")


def exigir_permissao_de_escrita(script: str) -> None:
    db_name = config.DB_NAME
    if db_name.endswith("_test_test"):
        print(f"⚠ {script}: banco '{db_name}' tem sufixo _test duplicado; confira MONGODB_DB.", file=sys.stderr)
    if is_test_db(db_name) or os.getenv("ALLOW_DEMO_DB_WRITE") == "1":
        return
    sys.exit(
        f"{script}: recusado escrever no banco da demo '{db_name}'.\n"
        f"Use um banco de teste (MONGODB_DB={db_name}_test) ou confirme com ALLOW_DEMO_DB_WRITE=1."
    )

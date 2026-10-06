"""Scripts que escrevem dado recusam o banco da demo sem ALLOW_DEMO_DB_WRITE=1 (sem tocar no Atlas)."""

import pytest

import config
import demo_guard


@pytest.mark.parametrize("db_name", ["madeira_madeira", "analise_garantia", "prod", "test", "x_testing"])
def test_refuses_demo_db_without_flag(monkeypatch, db_name):
    monkeypatch.setattr(config, "DB_NAME", db_name)
    monkeypatch.delenv("ALLOW_DEMO_DB_WRITE", raising=False)
    with pytest.raises(SystemExit) as exc:
        demo_guard.exigir_permissao_de_escrita("reset_demo.py")
    assert "ALLOW_DEMO_DB_WRITE=1" in str(exc.value)


@pytest.mark.parametrize("flag", ["0", "true", "yes", ""])
def test_flag_must_be_exactly_1(monkeypatch, flag):
    monkeypatch.setattr(config, "DB_NAME", "madeira_madeira")
    monkeypatch.setenv("ALLOW_DEMO_DB_WRITE", flag)
    with pytest.raises(SystemExit):
        demo_guard.exigir_permissao_de_escrita("seed.py")


def test_allows_test_db_and_explicit_flag(monkeypatch):
    monkeypatch.delenv("ALLOW_DEMO_DB_WRITE", raising=False)
    monkeypatch.setattr(config, "DB_NAME", "madeira_madeira_test")
    demo_guard.exigir_permissao_de_escrita("seed.py")
    monkeypatch.setattr(config, "DB_NAME", "madeira_madeira")
    monkeypatch.setenv("ALLOW_DEMO_DB_WRITE", "1")
    demo_guard.exigir_permissao_de_escrita("seed.py")


def test_every_writing_script_calls_the_guard():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for script in ["seed.py", "seed_meta.py", "seed_catalogo_fotos.py", "setup_indexes.py", "../scripts/reset_demo.py"]:
        assert "exigir_permissao_de_escrita(" in (root / script).read_text(), script

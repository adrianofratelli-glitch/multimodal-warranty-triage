"""Localiza o pacote `pov-shared` (grove_client, guardrails).

O caminho normal é tê-lo instalado no venv (`uv pip install -e "../../_shared[llm]"`).
Como atalho para quem clona o workspace inteiro, também aceitamos a pasta irmã
`../../_shared` sem instalar. Se nenhum dos dois existir, os módulos ficam `None`
e quem depende deles degrada de forma explícita (o veredito vira revisão manual,
os guardrails viram no-op com log), sem derrubar o import do app.
"""

import importlib
import logging
import sys
from pathlib import Path

logger = logging.getLogger("mm_garantia.shared")

_SIBLING = Path(__file__).resolve().parents[2] / "_shared"


def _load(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        pass
    if (_SIBLING / f"{name}.py").exists():
        if str(_SIBLING) not in sys.path:
            sys.path.append(str(_SIBLING))
        try:
            return importlib.import_module(name)
        except ImportError:
            logger.warning("pov-shared encontrado em %s mas %s não importou", _SIBLING, name, exc_info=True)
            return None
    logger.warning("pov-shared (%s) não instalado: instale com uv pip install -e ../../_shared[llm]", name)
    return None


grove_client = _load("grove_client")
guardrails = _load("guardrails")

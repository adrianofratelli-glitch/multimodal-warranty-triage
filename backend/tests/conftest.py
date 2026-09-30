import sys
from pathlib import Path

# backend/ isn't a package (no __init__.py, by design — it's a flat FastAPI app),
# so pytest's rootdir-based import doesn't put it on sys.path automatically.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

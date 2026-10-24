import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.main import app  # noqa: E402,F401  (Vercel serves the ASGI `app`)

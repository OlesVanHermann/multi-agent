"""Point d'entrée uvicorn (`multi_agent.backend:app`), ciblé par
web/start.sh et scripts/web.sh — ré-exporte l'app assemblée par server.py."""
from server import app  # noqa: F401

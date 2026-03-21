# Re-export app from server.py for uvicorn multi_agent.backend:app
import sys
import os

# Ensure parent directory (web/backend/) is in path so server.py can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app  # noqa: E402, F401

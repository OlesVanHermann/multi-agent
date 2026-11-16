"""Dépendances FastAPI communes : validation d'ID agent (B1)."""

from fastapi import Depends, HTTPException

from .config import AGENT_ID_RE


def _validated_agent_id(agent_id: str) -> str:
    """Validate agent_id format. Reject path traversal and injection attempts."""
    if not AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="Invalid agent_id format")
    return agent_id


ValidAgentId = Depends(lambda agent_id: _validated_agent_id(agent_id))

"""Routes /api/chat : chat développeurs via Redis stream (B1)."""

import time

from fastapi import APIRouter, HTTPException, Request

from .. import config as cfg
from .. import state
from ..auth import _get_jwt_username
from ..models import ChatMessage

router = APIRouter()

_CHAT_MAX_LENGTH = 2000


@router.get("/api/chat")
async def get_chat(last: int = 50):
    """Read last N dev chat messages from Redis stream."""
    last = max(1, min(last, 200))
    if not state.redis_pool:
        return {"lines": []}
    try:
        raw = await state.redis_pool.xrevrange(cfg.CHAT_STREAM, count=last)
        lines = []
        for msg_id, data in reversed(raw):
            lines.append(data.get("line", ""))
        return {"lines": lines}
    except Exception:
        return {"lines": []}


@router.post("/api/chat")
async def post_chat(msg: ChatMessage, request: Request):
    """Post a dev chat message to Redis stream."""
    if not state.redis_pool:
        raise HTTPException(status_code=503, detail="Redis not available")
    if len(msg.text) > _CHAT_MAX_LENGTH:
        raise HTTPException(status_code=400, detail=f"Message too long (max {_CHAT_MAX_LENGTH})")
    jwt_user = _get_jwt_username(request)
    ts = time.strftime("%H:%M")
    line = f"{ts} {jwt_user}: {msg.text.replace(chr(10), ' ').replace(chr(13), '')}"
    await state.redis_pool.xadd(cfg.CHAT_STREAM, {"line": line}, maxlen=200)
    return {"status": "ok"}

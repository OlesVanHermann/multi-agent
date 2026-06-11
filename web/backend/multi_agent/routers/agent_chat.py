"""Routes /api/agent-chat : proxy vers le shim Robeke (B1)."""

import json
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .. import config as cfg
from ..auth import _extract_username_from_jwt, _get_freemium_token

router = APIRouter()


@router.get("/api/agent-chat/health")
async def agent_chat_health():
    """Proxy to shim /health — public, wraps 'ok' text in JSON."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{cfg.AGENT_SHIM_URL}/health", timeout=5.0)
            text = resp.text.strip()
            if text == "ok":
                return {"status": "ok"}
            return {"status": text}
    except Exception:
        return Response(
            content=json.dumps({"status": "error", "detail": "shim unreachable"}),
            status_code=503,
            media_type="application/json",
        )


@router.get("/api/agent-chat/spec")
async def agent_chat_spec():
    """Proxy to shim /spec — public."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{cfg.AGENT_SHIM_URL}/spec", timeout=5.0)
            return Response(content=resp.content, status_code=resp.status_code,
                            media_type=resp.headers.get("content-type", "application/json"))
    except Exception:
        return Response(
            content=json.dumps({"error": "shim unreachable"}),
            status_code=503,
            media_type="application/json",
        )


@router.post("/api/agent-chat/rpc")
async def agent_chat_rpc(request: Request):
    """Proxy to shim /rpc — auth bridge: dashboard JWT -> freemium JWT."""
    auth_header = request.headers.get("authorization", "")
    username = _extract_username_from_jwt(auth_header)
    if not username:
        return Response(
            content=json.dumps({"error": "cannot extract username from token"}),
            status_code=401,
            media_type="application/json",
        )

    freemium_token = await _get_freemium_token(username)
    if not freemium_token:
        return Response(
            content=json.dumps({"error": "failed to obtain freemium token"}),
            status_code=502,
            media_type="application/json",
        )

    body = await request.body()
    if len(body) > 1_000_000:
        return Response(content=json.dumps({"error": "request too large"}), status_code=413,
                        media_type="application/json")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{cfg.AGENT_SHIM_URL}/rpc",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {freemium_token}",
                },
                timeout=120.0,  # MCP calls can be long
            )
            return Response(content=resp.content, status_code=resp.status_code,
                            media_type=resp.headers.get("content-type", "application/json"))
    except httpx.TimeoutException:
        return Response(
            content=json.dumps({"error": "shim timeout"}),
            status_code=504,
            media_type="application/json",
        )
    except Exception:
        return Response(
            content=json.dumps({"error": "shim unreachable"}),
            status_code=503,
            media_type="application/json",
        )


@router.get("/api/agent-chat/facts")
async def agent_chat_facts(request: Request):
    """Proxy to shim /api/facts — requires auth."""
    auth_header = request.headers.get("authorization", "")
    username = _extract_username_from_jwt(auth_header)
    if not username:
        return Response(content=json.dumps({"error": "unauthorized"}), status_code=401,
                        media_type="application/json")
    freemium_token = await _get_freemium_token(username)
    if not freemium_token:
        return Response(content=json.dumps({"error": "failed to obtain freemium token"}), status_code=502,
                        media_type="application/json")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{cfg.AGENT_SHIM_URL}/api/facts",
                headers={"Authorization": f"Bearer {freemium_token}"},
                timeout=10.0,
            )
            return Response(content=resp.content, status_code=resp.status_code,
                            media_type=resp.headers.get("content-type", "application/json"))
    except Exception:
        return Response(content=json.dumps({"error": "shim unreachable"}), status_code=503,
                        media_type="application/json")


@router.get("/api/agent-chat/events")
async def agent_chat_events(request: Request):
    """SSE proxy to shim /events/progress — requires auth with user isolation."""
    auth_header = request.headers.get("authorization", "")
    username = _extract_username_from_jwt(auth_header)
    if not username:
        return Response(content=json.dumps({"error": "unauthorized"}), status_code=401,
                        media_type="application/json")
    freemium_token = await _get_freemium_token(username)
    if not freemium_token:
        return Response(content=json.dumps({"error": "failed to obtain freemium token"}), status_code=502,
                        media_type="application/json")
    async def stream():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"{cfg.AGENT_SHIM_URL}/events/progress",
                                     headers={"Authorization": f"Bearer {freemium_token}"},
                                     timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk
    try:
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except Exception:
        return Response(content=json.dumps({"error": "shim unreachable"}), status_code=503,
                        media_type="application/json")


@router.get("/api/agent-chat/conversations")
async def agent_chat_conversations(request: Request):
    """Proxy to shim /api/conversations — requires auth."""
    auth_header = request.headers.get("authorization", "")
    username = _extract_username_from_jwt(auth_header)
    if not username:
        return Response(content=json.dumps({"error": "unauthorized"}), status_code=401,
                        media_type="application/json")
    freemium_token = await _get_freemium_token(username)
    if not freemium_token:
        return Response(content=json.dumps({"error": "failed to obtain freemium token"}), status_code=502,
                        media_type="application/json")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{cfg.AGENT_SHIM_URL}/api/conversations",
                headers={"Authorization": f"Bearer {freemium_token}"},
                timeout=10.0,
            )
            return Response(content=resp.content, status_code=resp.status_code,
                            media_type=resp.headers.get("content-type", "application/json"))
    except Exception:
        return Response(content=json.dumps({"error": "shim unreachable"}), status_code=503,
                        media_type="application/json")


@router.get("/api/agent-chat/conversations/{conv_id}/messages")
async def agent_chat_conversation_messages(conv_id: str, request: Request):
    """Proxy to shim /api/conversations/{id}/messages — requires auth."""
    if not re.match(r'^[a-zA-Z0-9_-]+$', conv_id):
        raise HTTPException(status_code=400, detail="Invalid conversation ID format")
    auth_header = request.headers.get("authorization", "")
    username = _extract_username_from_jwt(auth_header)
    if not username:
        return Response(content=json.dumps({"error": "unauthorized"}), status_code=401,
                        media_type="application/json")
    freemium_token = await _get_freemium_token(username)
    if not freemium_token:
        return Response(content=json.dumps({"error": "failed to obtain freemium token"}), status_code=502,
                        media_type="application/json")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{cfg.AGENT_SHIM_URL}/api/conversations/{conv_id}/messages",
                headers={"Authorization": f"Bearer {freemium_token}"},
                timeout=10.0,
            )
            return Response(content=resp.content, status_code=resp.status_code,
                            media_type=resp.headers.get("content-type", "application/json"))
    except Exception:
        return Response(content=json.dumps({"error": "shim unreachable"}), status_code=503,
                        media_type="application/json")

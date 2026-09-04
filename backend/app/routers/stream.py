# FILE: backend/app/routers/stream.py
"""Server-Sent Events for real-time dashboard updates (spec 15/16).

The frontend opens GET /api/stream?token=<jwt> and receives recovery.* events as
they happen. We accept the token via query string because EventSource cannot set
Authorization headers.
"""
from __future__ import annotations

import asyncio
import queue

import jwt
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ..config import get_settings
from ..events import broker

router = APIRouter(prefix="/api", tags=["stream"])
settings = get_settings()


@router.get("/stream")
async def stream(token: str = Query(...)):
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        merchant_id = data["merchant_id"]
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc

    q = broker.subscribe(merchant_id)

    async def event_gen():
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                try:
                    msg = q.get_nowait()
                    yield msg
                except queue.Empty:
                    await asyncio.sleep(0.4)
                    yield ": keepalive\n\n"  # comment frame keeps the connection open
        finally:
            broker.unsubscribe(merchant_id, q)

    return StreamingResponse(event_gen(), media_type="text/event-stream")

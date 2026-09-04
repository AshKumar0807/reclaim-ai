"""Small MCP stdio client used by the synchronous recovery worker."""
from __future__ import annotations

import json
import base64
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def call_tool(name: str, arguments: dict) -> dict:
    key = os.environ.get("RAZORPAY_KEY_ID", "")
    secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key or not secret:
        raise RuntimeError("Razorpay credentials are not configured")
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    url = os.environ.get("RAZORPAY_MCP_URL", "https://mcp.razorpay.com/mcp")
    async with streamablehttp_client(url, headers={"Authorization": f"Basic {token}"}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments=arguments)
    if getattr(result, "isError", False):
        raise RuntimeError(str(result.content))
    for item in result.content:
        text = getattr(item, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"status": "issued", "message": text}
    return {}
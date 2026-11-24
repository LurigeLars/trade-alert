from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client


class MCPToolError(RuntimeError):
    pass


def _json_from_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def dtv_auth_headers() -> dict[str, str]:
    """Bearer token the local DTV HTTP server requires; written by that server on first start."""
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    try:
        token = (root / "tradingview-mcp" / "http-token").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return {}
    return {"Authorization": f"Bearer {token}"} if token else {}


async def call_json_tool(url: str, name: str, arguments: dict[str, Any]) -> Any:
    """Call one local MCP tool and decode its outer text envelope.

    Some provider tools return another MCP CallToolResult serialized inside that JSON. The news
    normalizer intentionally handles that nested shape rather than rebuilding provider payloads here.
    """
    try:
        http = httpx2.AsyncClient(headers=dtv_auth_headers(), timeout=httpx2.Timeout(30.0, read=300.0))
        async with http, Client(streamable_http_client(url, http_client=http)) as client:
            result = await client.call_tool(name, arguments)
    except Exception as exc:
        raise MCPToolError(f"{name}: transport unavailable") from exc

    if getattr(result, "is_error", False):
        message = "tool returned an error"
        for block in getattr(result, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                message = text
                break
        raise MCPToolError(f"{name}: {message}")

    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured

    blocks = getattr(result, "content", []) or []
    for block in blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return _json_from_text(text)
    raise MCPToolError(f"{name}: empty response")

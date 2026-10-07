from __future__ import annotations

import json
from typing import Any

from mcp.client import Client


class MCPToolError(RuntimeError):
    pass


def _json_from_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def call_json_tool(url: str, name: str, arguments: dict[str, Any]) -> Any:
    """Call one local MCP tool and decode its outer text envelope.

    Some provider tools return another MCP CallToolResult serialized inside that JSON. The news
    normalizer intentionally handles that nested shape rather than rebuilding provider payloads here.
    """
    try:
        async with Client(url) as client:
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

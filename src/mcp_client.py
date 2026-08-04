from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_MCP_URL = "https://mcp.skiplagged.com/mcp"


@dataclass
class McpResponse:
    ok: bool
    text: str
    raw: dict[str, Any] | None = None
    is_error: bool = False


class SkiplaggedMcpClient:
    def __init__(self, url: str = DEFAULT_MCP_URL, timeout_seconds: int = 60) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._request_id = 0
        self._initialized = False

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                return {"error": {"message": "HTTP 429 rate limited"}}
            raise RuntimeError(
                f"MCP HTTP error {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
            ) from exc

        if not body.strip():
            return None

        for line in body.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])

        return json.loads(body)

    def initialize(self) -> None:
        if self._initialized:
            return

        init = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "flightchange-tracker", "version": "0.1.0"},
                },
            }
        )
        if not init or "error" in init:
            raise RuntimeError(f"MCP initialize failed: {init}")

        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        self._initialized = True

    def call_tool(self, name: str, arguments: dict[str, Any]) -> McpResponse:
        self.initialize()

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        result = self._post(payload)
        if not result:
            raise RuntimeError(f"No response for tool call: {name}")

        if "error" in result:
            message = result["error"].get("message", "unknown MCP error")
            return McpResponse(ok=False, text=message, raw=result, is_error=True)

        tool_result = result.get("result", {})
        content = tool_result.get("content") or []
        text_parts = [item.get("text", "") for item in content if item.get("type") == "text"]
        text = "\n".join(part for part in text_parts if part).strip()
        is_error = bool(tool_result.get("isError"))

        return McpResponse(
            ok=not is_error,
            text=text or "(empty response)",
            raw=result,
            is_error=is_error,
        )

    def search_flights(self, arguments: dict[str, Any]) -> McpResponse:
        args = {"renderMode": "text", **arguments}
        return self.call_tool("sk_flights_search", args)

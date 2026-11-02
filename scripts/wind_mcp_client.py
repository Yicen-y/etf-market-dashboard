"""Small synchronous client for Wind Alice's Streamable HTTP MCP endpoint."""

from __future__ import annotations

import json
import re
from typing import Any

import requests


class WindMcpError(RuntimeError):
    """An MCP transport, protocol, or remote-tool error with secrets removed."""


class WindMcpClient:
    def __init__(self, endpoint: str, authorization: str, timeout: float = 30.0):
        if not endpoint.startswith(("https://", "http://")):
            raise ValueError("MCP endpoint must use HTTP or HTTPS")
        if not authorization or not authorization.strip():
            raise ValueError("Wind MCP Authorization is required")
        self.endpoint = endpoint
        self._authorization = authorization.strip()
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": self._authorization,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        })
        self._session_id: str | None = None
        self._request_id = 0
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        result = self._request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "etf-market-dashboard", "version": "1.0"},
        })
        self._initialized = True
        self._notification("notifications/initialized")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        self._require_initialized()
        result = self._request("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise WindMcpError("MCP tools/list response did not contain a tools array")
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_initialized()
        if not name or not isinstance(arguments, dict):
            raise ValueError("Tool name and object arguments are required")
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            raise WindMcpError("MCP tools/call returned a non-object result")
        if result.get("isError"):
            detail = " ".join(item.get("text", "") for item in result.get("content", []) if isinstance(item, dict))
            raise WindMcpError(self._redact(detail or "Wind MCP tool call failed"))
        return result

    def close(self) -> None:
        self._session.close()
        self._session_id = None
        self._initialized = False

    def __enter__(self) -> "WindMcpClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        self._request_id += 1
        request_id = self._request_id
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        headers = self._session.headers.copy()
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            response = self._session.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise WindMcpError(f"Wind MCP request failed ({type(exc).__name__})") from None
        self._capture_session(response)
        if response.status_code >= 400:
            raise WindMcpError(f"Wind MCP HTTP error {response.status_code}")
        try:
            message = self._parse_response(response)
        except (ValueError, json.JSONDecodeError) as exc:
            raise WindMcpError(f"Invalid Wind MCP response: {self._redact(str(exc))}") from None
        if not isinstance(message, dict):
            raise WindMcpError("Wind MCP response was not a JSON-RPC object")
        if message.get("id") not in (None, request_id):
            raise WindMcpError("Wind MCP response ID did not match request")
        if "error" in message:
            error = message["error"]
            text = error.get("message", "MCP remote error") if isinstance(error, dict) else "MCP remote error"
            raise WindMcpError(self._redact(str(text)))
        if "result" not in message:
            raise WindMcpError("Wind MCP response did not contain a result")
        return message["result"]

    def _notification(self, method: str) -> None:
        payload = {"jsonrpc": "2.0", "method": method}
        headers = self._session.headers.copy()
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            response = self._session.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise WindMcpError(f"Wind MCP notification failed ({type(exc).__name__})") from None
        self._capture_session(response)
        if response.status_code >= 400:
            raise WindMcpError(f"Wind MCP notification HTTP error {response.status_code}")

    def _capture_session(self, response: requests.Response) -> None:
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id

    @staticmethod
    def _parse_response(response: requests.Response) -> dict[str, Any]:
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/event-stream" not in content_type:
            return response.json()
        events = []
        for block in re.split(r"\r?\n\r?\n", response.text):
            data_lines = [line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")]
            if data_lines:
                events.append(json.loads("\n".join(data_lines)))
        if not events:
            raise ValueError("empty SSE event stream")
        return events[-1]

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise WindMcpError("Call initialize() before using MCP tools")

    def _redact(self, text: str) -> str:
        result = text.replace(self._authorization, "[REDACTED]")
        if self._session_id:
            result = result.replace(self._session_id, "[SESSION]")
        return result

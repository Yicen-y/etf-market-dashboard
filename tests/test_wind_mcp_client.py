import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts.wind_mcp_client import WindMcpClient, WindMcpError


@pytest.fixture
def mcp_server():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            received.append((body, dict(self.headers)))
            method = body.get("method")
            if method == "initialize":
                response = {"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "mock", "version": "1"}}}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Mcp-Session-Id", "secret-session")
                payload = json.dumps(response).encode()
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif method == "notifications/initialized":
                self.send_response(202)
                self.end_headers()
            elif method == "tools/list":
                response = {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [{"name": "history", "inputSchema": {"type": "object"}}]}}
                self._json(response)
            elif method == "tools/call":
                if body["params"].get("name") == "bad":
                    self._json({"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32601, "message": "unknown tool"}})
                else:
                    self._json({"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": json.dumps({"rows": []})}]}})
            else:
                self._json({"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": "unknown method"}})

        def _json(self, response):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            payload = json.dumps(response).encode()
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp", received
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_initialize_captures_session_and_lists_tools_with_auth_header(mcp_server):
    endpoint, received = mcp_server
    client = WindMcpClient(endpoint, "Bearer test-secret")
    assert client.initialize()["serverInfo"]["name"] == "mock"
    tools = client.list_tools()
    assert tools[0]["name"] == "history"
    assert any(body["method"] == "notifications/initialized" for body, _ in received)
    assert all(headers["Authorization"] == "Bearer test-secret" for _, headers in received)
    assert all(headers.get("Mcp-Session-Id") == "secret-session" for body, headers in received if body["method"] == "tools/list")


def test_call_tool_returns_result_and_surfaces_mcp_error(mcp_server):
    endpoint, _ = mcp_server
    client = WindMcpClient(endpoint, "secret")
    client.initialize()
    result = client.call_tool("history", {"code": "TEST"})
    assert result["content"]
    with pytest.raises(WindMcpError, match="unknown tool"):
        client.call_tool("bad", {})


def test_call_before_initialize_is_rejected(mcp_server):
    endpoint, _ = mcp_server
    client = WindMcpClient(endpoint, "secret")
    with pytest.raises(WindMcpError, match="initialize"):
        client.list_tools()


def test_errors_do_not_leak_authorization_or_session(mcp_server):
    endpoint, _ = mcp_server
    client = WindMcpClient(endpoint, "Bearer do-not-leak")
    client.initialize()
    with pytest.raises(WindMcpError) as exc:
        client.call_tool("bad", {})
    assert "do-not-leak" not in str(exc.value)
    assert "secret-session" not in str(exc.value)

"""One MCP session per server for the life of a card: the handshake is paid once, a session
the server no longer knows is replaced transparently, and sessions are dropped on exit."""

from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from orchestrator_client import orchestrator_session


class _Response(io.BytesIO):
    def __init__(self, body: bytes, session_id: str) -> None:
        super().__init__(body)
        self.headers = {"mcp-session-id": session_id}


def _ok(request_id: int = 1) -> bytes:
    payload = {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps({"ok": True})}]}}
    return f"data: {json.dumps(payload)}\n".encode()


class _FakeServer:
    """Hands out sessions s1, s2, ...; forgets one when told to (as a restarted spoke would)."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str | None, str | None]] = []  # (http method, rpc method, session)
        self.known: set[str] = set()
        self.next_session = 1

    def urlopen(self, request, timeout):
        session = request.get_header("Mcp-session-id")
        if request.get_method() == "DELETE":
            self.requests.append(("DELETE", None, session))
            return io.BytesIO(b"")
        body = json.loads(request.data)
        self.requests.append(("POST", body.get("method"), session))
        if body.get("method") == "initialize":
            sid = f"s{self.next_session}"
            self.next_session += 1
            self.known.add(sid)
            return _Response(b"", sid)
        if session not in self.known:
            raise urllib.error.HTTPError(request.full_url, 404, "Session not found", {}, None)
        return _Response(_ok(body.get("id", 1)) if body.get("method") == "tools/call" else b"", session)


class ConnectionReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        orchestrator_session._mcp_sessions.clear()
        self.server = _FakeServer()
        patcher = mock.patch.object(orchestrator_session.urllib.request, "urlopen", self.server.urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(orchestrator_session._mcp_sessions.clear)

    def rpc_methods(self) -> list[str | None]:
        return [rpc for http, rpc, _ in self.server.requests if http == "POST"]

    def test_the_handshake_happens_once_per_server(self) -> None:
        for _ in range(3):
            orchestrator_session.status("http://spoke/mcp")
        self.assertEqual(self.rpc_methods(), ["initialize", "notifications/initialized", "tools/call", "tools/call", "tools/call"])
        self.assertEqual({s for _, rpc, s in self.server.requests if rpc == "tools/call"}, {"s1"})

    def test_each_server_gets_its_own_session(self) -> None:
        orchestrator_session.status("http://spoke-a/mcp")
        orchestrator_session.status("http://spoke-b/mcp")
        orchestrator_session.status("http://spoke-a/mcp")
        sessions = [s for _, rpc, s in self.server.requests if rpc == "tools/call"]
        self.assertEqual(sessions, ["s1", "s2", "s1"])

    def test_a_forgotten_session_is_replaced_and_the_call_sent_again(self) -> None:
        orchestrator_session.status("http://spoke/mcp")
        self.server.known.clear()  # the spoke restarted
        self.assertEqual(orchestrator_session.status("http://spoke/mcp"), {"ok": True})
        self.assertEqual(
            self.rpc_methods(),
            ["initialize", "notifications/initialized", "tools/call", "tools/call", "initialize", "notifications/initialized", "tools/call"],
        )
        self.assertEqual(orchestrator_session._mcp_sessions["http://spoke/mcp"], "s2")

    def test_close_connections_drops_every_session(self) -> None:
        orchestrator_session.status("http://spoke-a/mcp")
        orchestrator_session.status("http://spoke-b/mcp")
        orchestrator_session.close_connections()
        deletes = sorted(s for http, _, s in self.server.requests if http == "DELETE")
        self.assertEqual(deletes, ["s1", "s2"])
        self.assertEqual(orchestrator_session._mcp_sessions, {})
        orchestrator_session.close_connections()  # nothing left: no-op


if __name__ == "__main__":
    unittest.main()

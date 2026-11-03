"""The orchestrator client sends a bearer token to a spoke or hub started with
HAMILTON_MCP_AUTH_TOKEN, and explains a 401 instead of a bare HTTP error."""

from __future__ import annotations

import io
import os
import unittest
import urllib.error
from unittest import mock

from orchestrator_client import Instrument, OrchestratorCallError, orchestrator_session


class _Response(io.BytesIO):
    headers = {"mcp-session-id": "sid"}


def _capture(seen: list[dict[str, str]]):
    def _urlopen(request, timeout):
        seen.append({k.lower(): v for k, v in request.header_items()})
        return _Response(b'data: {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "{}"}]}}\n')

    return _urlopen


class ClientAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        orchestrator_session._mcp_sessions.clear()

    def tearDown(self) -> None:
        orchestrator_session._auth_tokens.clear()
        orchestrator_session._mcp_sessions.clear()

    def test_no_token_no_header(self) -> None:
        seen: list[dict[str, str]] = []
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(orchestrator_session.urllib.request, "urlopen", _capture(seen)):
            orchestrator_session.status("http://spoke/mcp")
        self.assertTrue(seen)
        self.assertTrue(all("authorization" not in h for h in seen))

    def test_instrument_token_is_sent_on_every_request_to_its_url(self) -> None:
        seen: list[dict[str, str]] = []
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(orchestrator_session.urllib.request, "urlopen", _capture(seen)):
            Instrument("http://spoke/mcp", token="s3cret").status()
            orchestrator_session.status("http://other/mcp")
        spoke_calls, other_call = seen[:-3], seen[-3:]
        self.assertTrue(all(h["authorization"] == "Bearer s3cret" for h in spoke_calls))
        self.assertTrue(all("authorization" not in h for h in other_call))

    def test_environment_token_is_the_fallback(self) -> None:
        seen: list[dict[str, str]] = []
        with mock.patch.dict(os.environ, {orchestrator_session.AUTH_TOKEN_ENV: "env-tok"}), mock.patch.object(
            orchestrator_session.urllib.request, "urlopen", _capture(seen)
        ):
            orchestrator_session.status("http://spoke/mcp")
        self.assertEqual(seen[0]["authorization"], "Bearer env-tok")

    def test_a_401_says_a_token_is_needed(self) -> None:
        def _refuse(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(orchestrator_session.urllib.request, "urlopen", _refuse):
            with self.assertRaisesRegex(OrchestratorCallError, "requires a bearer token"):
                orchestrator_session.status("http://spoke/mcp")


if __name__ == "__main__":
    unittest.main()

"""Instrument.local() and the local-spoke helpers, against a stand-in spoke: a tiny HTTP
server answering /ping, started as a real detached process -- so starting, finding,
health-checking and stopping a process are exercised for real, without VENUS."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from orchestrator_client import Instrument, OrchestratorCallError, local_spoke, orchestrator_session

FAKE_SPOKE = textwrap.dedent(
    """
    import json, os
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"service": os.environ.get("FAKE_SERVICE", "hamilton-venus-mcp"),
                               "name": "fake-spoke", "auth_required": False}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    if os.environ.get("FAKE_CRASH"):
        raise SystemExit("boom: bad config")
    assert os.environ["HAMILTON_MCP_HOST"] == "127.0.0.1"
    HTTPServer(("127.0.0.1", int(os.environ["HAMILTON_MCP_PORT"])), Handler).serve_forever()
    """
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalSpokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        script = Path(self.tmp.name) / "fake_spoke.py"
        script.write_text(FAKE_SPOKE, encoding="utf-8")
        self.command = [sys.executable, str(script)]
        self.port = _free_port()
        self.addCleanup(self._kill_leftover)

    def _kill_leftover(self) -> None:
        status = local_spoke.local_spoke_status(self.port)
        if status["running"] and status["pid"]:
            local_spoke._terminate(status["pid"])

    def _no_session(self):
        return mock.patch.object(orchestrator_session, "_dispatch", return_value={"session_active": False, "run": None})

    def test_nothing_running(self) -> None:
        status = local_spoke.local_spoke_status(self.port)
        self.assertFalse(status["running"])
        self.assertIsNone(status["pid"])
        self.assertEqual(status["url"], f"http://127.0.0.1:{self.port}/mcp")

    def test_local_starts_once_reports_status_and_stops(self) -> None:
        inst = Instrument.local(self.port, exe=self.command, startup_timeout_s=20)
        self.assertEqual(inst.url, f"http://127.0.0.1:{self.port}/mcp")

        status = Instrument.local_status(self.port)
        self.assertTrue(status["running"])
        self.assertTrue(status["started_by_client"])
        self.assertTrue(local_spoke._pid_alive(status["pid"]))
        self.assertEqual(status["name"], "fake-spoke")
        self.assertGreaterEqual(status["uptime_s"], 0)

        # A second card finds it running and does not start another.
        again = local_spoke.start_local_spoke(self.port, exe=self.command)
        self.assertEqual(again["pid"], status["pid"])

        with self._no_session():
            result = Instrument.stop_local(self.port)
        self.assertEqual((result["stopped"], result["was_running"], result["pid"]), (True, True, status["pid"]))
        time.sleep(0.3)
        self.assertFalse(local_spoke._pid_alive(status["pid"]))
        self.assertFalse(local_spoke.local_spoke_status(self.port)["running"])

    def test_stop_closes_an_open_session_first(self) -> None:
        local_spoke.start_local_spoke(self.port, exe=self.command, startup_timeout_s=20)
        with mock.patch.object(orchestrator_session, "_dispatch", return_value={"session_active": True, "run": None}), \
                mock.patch.object(orchestrator_session, "finish") as finish:
            result = local_spoke.stop_local_spoke(self.port)
        finish.assert_called_once()
        self.assertTrue(result["closed_session"])

    def test_stop_refuses_an_open_session_or_script_run_unless_told(self) -> None:
        local_spoke.start_local_spoke(self.port, exe=self.command, startup_timeout_s=20)
        with mock.patch.object(orchestrator_session, "_dispatch", return_value={"session_active": True, "run": None}):
            with self.assertRaisesRegex(OrchestratorCallError, "session is open"):
                local_spoke.stop_local_spoke(self.port, close_session=False)
        with mock.patch.object(orchestrator_session, "_dispatch", return_value={"session_active": False, "run": {"script": "a.py"}}):
            with self.assertRaisesRegex(OrchestratorCallError, "script run"):
                local_spoke.stop_local_spoke(self.port)
            self.assertTrue(local_spoke.stop_local_spoke(self.port, force=True)["stopped"])

    def test_stopping_when_nothing_runs_is_a_no_op(self) -> None:
        self.assertEqual(local_spoke.stop_local_spoke(self.port)["was_running"], False)

    def test_health(self) -> None:
        local_spoke.start_local_spoke(self.port, exe=self.command, startup_timeout_s=20)
        spoke_state = {
            "venus_run_state": {"state": "idle"},
            "status": {"status": "idle", "detail": None},
            "session_active": True,
            "connection_id": "c1",
            "command_control": {"state": "running", "hold": None},
            "pending_prompts": [],
        }
        with mock.patch.object(orchestrator_session, "_dispatch", return_value=spoke_state):
            health = Instrument.local_health(self.port)
        self.assertTrue(health["healthy"], health["checks"])
        self.assertEqual(set(health["checks"]), {"process", "ping", "mcp", "venus"})
        self.assertEqual((health["status"], health["session_active"]), ("idle", True))

        with mock.patch.object(orchestrator_session, "_dispatch", return_value={**spoke_state, "venus_run_state": {"error": "refused"}}):
            health = local_spoke.local_spoke_health(self.port)
        self.assertFalse(health["healthy"])
        self.assertFalse(health["checks"]["venus"]["ok"])

    def test_health_of_a_stopped_spoke(self) -> None:
        health = local_spoke.local_spoke_health(self.port)
        self.assertFalse(health["healthy"])
        self.assertFalse(health["checks"]["ping"]["ok"])
        self.assertIn("skipped", health["checks"]["mcp"]["detail"])

    def test_a_spoke_that_dies_on_startup_reports_its_log(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_CRASH": "1"}):
            with self.assertRaisesRegex(OrchestratorCallError, "boom: bad config"):
                local_spoke.start_local_spoke(self.port, exe=self.command, startup_timeout_s=20)

    def test_a_port_held_by_something_else_is_refused(self) -> None:
        env = {**os.environ, "FAKE_SERVICE": "something-else", "HAMILTON_MCP_HOST": "127.0.0.1", "HAMILTON_MCP_PORT": str(self.port)}
        other = subprocess.Popen(self.command, env=env)
        self.addCleanup(other.kill)
        for _ in range(80):
            if local_spoke._port_open(self.port):
                break
            time.sleep(0.1)
        self.assertFalse(local_spoke.local_spoke_status(self.port)["running"])
        with self.assertRaisesRegex(OrchestratorCallError, "not a spoke"):
            local_spoke.start_local_spoke(self.port, exe=self.command, startup_timeout_s=5)

    def test_spoke_command_resolution(self) -> None:
        self.assertEqual(local_spoke.spoke_command(["x", "-y"]), ["x", "-y"])
        self.assertEqual(local_spoke.spoke_command("C:/a/spoke.exe"), ["C:/a/spoke.exe"])
        with mock.patch.dict(os.environ, {local_spoke.SPOKE_EXE_ENV: "D:/b/spoke.exe"}):
            self.assertEqual(local_spoke.spoke_command(), ["D:/b/spoke.exe"])


if __name__ == "__main__":
    unittest.main()

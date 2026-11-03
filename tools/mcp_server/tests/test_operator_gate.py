"""Tests for the human-only path: script_runs.operator_gate and the operator web app."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from starlette.testclient import TestClient

from hamilton_venus_mcp.script_runs.consumables_config import ConsumablesConfigStore
from hamilton_venus_mcp.script_runs.consumables_ledger import ConsumablesLedger
from hamilton_venus_mcp.script_runs.manager import OPERATOR_TOKEN_ENV, RunManager
from hamilton_venus_mcp.script_runs.operator_gate import (
    FAILURE_WINDOW_S,
    LOCKOUT_S,
    MAX_FAILURES,
    OperatorAuthError,
    OperatorGate,
)
from hamilton_venus_mcp.script_runs.operator_http import TOKEN_HEADER, create_app
from hamilton_venus_mcp.scripts_store import ScriptStore

FAKE_CHILD = Path(__file__).with_name("fake_child.py")
TOKEN = "s3cret-token"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class GateTestCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {OPERATOR_TOKEN_ENV: TOKEN})
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ScriptStore(Path(self._tmp.name) / "scripts")
        self.consumables_config = ConsumablesConfigStore(Path(self._tmp.name) / "consumables" / "config.json")
        self.ledger = ConsumablesLedger(Path(self._tmp.name) / "consumables" / "ledger.sqlite")
        self.addCleanup(self.ledger.close)
        self.manager = RunManager(
            self.store, child_script=FAKE_CHILD, consumables_config=self.consumables_config, ledger=self.ledger
        )
        self.clock = FakeClock()
        self.gate = OperatorGate(self.manager, clock=self.clock)


class VerifyTests(GateTestCase):
    def test_right_token_passes(self):
        self.gate.verify(TOKEN)

    def test_wrong_missing_and_empty_tokens_fail(self):
        for token in ("wrong", "", None, TOKEN + "x", TOKEN[:-1]):
            with self.subTest(token=token), self.assertRaisesRegex(OperatorAuthError, "Wrong operator token"):
                self.gate.verify(token)

    def test_unconfigured_gate_refuses_everything(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(OPERATOR_TOKEN_ENV, None)
            self.assertFalse(self.gate.configured)
            with self.assertRaisesRegex(OperatorAuthError, "not set"):
                self.gate.verify("anything")
            with self.assertRaisesRegex(OperatorAuthError, "not set"):
                self.gate.verify("")

    def test_repeated_wrong_tokens_lock_the_gate_even_for_the_right_one(self):
        for _ in range(MAX_FAILURES):
            with self.assertRaises(OperatorAuthError):
                self.gate.verify("guess")
        with self.assertRaisesRegex(OperatorAuthError, "Too many wrong tokens"):
            self.gate.verify(TOKEN)
        self.clock.advance(LOCKOUT_S + 1)
        self.gate.verify(TOKEN)

    def test_slow_guessing_does_not_lock(self):
        for _ in range(MAX_FAILURES * 2):
            with self.assertRaises(OperatorAuthError):
                self.gate.verify("guess")
            self.clock.advance(FAILURE_WINDOW_S / (MAX_FAILURES - 1) + 1)
        self.gate.verify(TOKEN)

    def test_a_success_forgets_earlier_failures(self):
        for _ in range(MAX_FAILURES - 1):
            with self.assertRaises(OperatorAuthError):
                self.gate.verify("guess")
        self.gate.verify(TOKEN)
        for _ in range(MAX_FAILURES - 1):
            with self.assertRaises(OperatorAuthError):
                self.gate.verify("guess")
        self.gate.verify(TOKEN)


class ResolveThroughTheGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {OPERATOR_TOKEN_ENV: TOKEN})
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ScriptStore(Path(self._tmp.name) / "scripts")
        self.consumables_config = ConsumablesConfigStore(Path(self._tmp.name) / "consumables" / "config.json")
        self.ledger = ConsumablesLedger(Path(self._tmp.name) / "consumables" / "ledger.sqlite")
        self.addCleanup(self.ledger.close)
        self.manager = RunManager(
            self.store, child_script=FAKE_CHILD, consumables_config=self.consumables_config, ledger=self.ledger
        )
        self.gate = OperatorGate(self.manager)

    async def until(self, condition, timeout=20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            await asyncio.sleep(0.05)
        self.fail("timed out")

    async def test_only_the_right_token_answers_a_prompt(self):
        self.store.write("prompt.py", "# mode: prompt\nprint('x')\n")
        run = await self.manager.start_run("prompt.py")
        await self.until(lambda: run.pending_prompts())

        with self.assertRaises(OperatorAuthError):
            self.gate.resolve("wrong", run.run_id, "err-1", action="retry")
        self.assertEqual(len(run.pending_prompts()), 1)  # untouched

        result = self.gate.resolve(TOKEN, run.run_id, "err-1", action="retry", operator="Sam", source="test")
        self.assertTrue(result["resolved"])
        await self.until(lambda: run.status == "completed")
        (done,) = self.manager.get_run(run.run_id)["prompt_history"]
        self.assertEqual(done["resolution"]["operator"], "Sam")


class OperatorAppTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {OPERATOR_TOKEN_ENV: TOKEN})
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ScriptStore(Path(self._tmp.name) / "scripts")
        self.consumables_config = ConsumablesConfigStore(Path(self._tmp.name) / "consumables" / "config.json")
        self.ledger = ConsumablesLedger(Path(self._tmp.name) / "consumables" / "ledger.sqlite")
        self.addCleanup(self.ledger.close)
        self.manager = RunManager(
            self.store, child_script=FAKE_CHILD, consumables_config=self.consumables_config, ledger=self.ledger
        )
        self.client = TestClient(create_app(self.manager, OperatorGate(self.manager)))
        self.addCleanup(self.client.close)

    async def until(self, condition, timeout=20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            await asyncio.sleep(0.05)
        self.fail("timed out")

    def test_page_is_served_and_shows_no_token(self):
        response = self.client.get("/operator")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Operator", response.text)
        self.assertNotIn(TOKEN, response.text)

    def test_state_is_readable_without_a_token_and_never_contains_it(self):
        response = self.client.get("/api/operator/state.json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "idle")
        self.assertNotIn(TOKEN, response.text)

    def test_resolve_rejects_bad_requests_and_bad_tokens(self):
        url = "/api/operator/resolve"
        self.assertEqual(self.client.post(url, content="not json").status_code, 400)
        self.assertEqual(self.client.post(url, json={"action": "retry"}).status_code, 400)
        no_token = self.client.post(url, json={"prompt_id": "p", "action": "retry"})
        self.assertEqual(no_token.status_code, 403)
        wrong = self.client.post(url, json={"prompt_id": "p", "action": "retry"}, headers={TOKEN_HEADER: "nope"})
        self.assertEqual(wrong.status_code, 403)
        self.assertNotIn(TOKEN, wrong.text)

    def test_right_token_but_nothing_pending_is_a_400(self):
        response = self.client.post(
            "/api/operator/resolve", json={"prompt_id": "p", "action": "retry"}, headers={TOKEN_HEADER: TOKEN}
        )
        self.assertEqual(response.status_code, 400)

    async def test_full_round_trip_through_the_web_api(self):
        self.store.write("prompt.py", "# mode: prompt\nprint('x')\n")
        run = await self.manager.start_run("prompt.py")
        await self.until(lambda: run.pending_prompts())

        state = self.client.get("/api/operator/state.json").json()
        self.assertEqual((state["state"], state["error_kind"]), ("error", "prompt_pending"))
        (prompt,) = state["pending_prompts"]
        self.assertEqual(prompt["options"], ["retry", "abort"])

        bad_option = self.client.post(
            "/api/operator/resolve",
            json={"run_id": prompt["run_id"], "prompt_id": prompt["prompt_id"], "action": "explode"},
            headers={TOKEN_HEADER: TOKEN},
        )
        self.assertEqual(bad_option.status_code, 400)

        ok = self.client.post(
            "/api/operator/resolve",
            json={"run_id": prompt["run_id"], "prompt_id": prompt["prompt_id"], "action": "retry", "operator": "Sam"},
            headers={TOKEN_HEADER: TOKEN},
        )
        self.assertEqual(ok.status_code, 200)
        await self.until(lambda: run.status == "completed")
        (done,) = self.manager.get_run(run.run_id)["prompt_history"]
        self.assertEqual(done["resolution"], {"action": "retry", "operator": "Sam", "source": "operator_page"})

    async def test_operator_name_is_length_limited(self):
        self.store.write("prompt.py", "# mode: prompt\nprint('x')\n")
        run = await self.manager.start_run("prompt.py")
        await self.until(lambda: run.pending_prompts())
        self.client.post(
            "/api/operator/resolve",
            json={"run_id": run.run_id, "prompt_id": "err-1", "action": "retry", "operator": "x" * 500},
            headers={TOKEN_HEADER: TOKEN},
        )
        await self.until(lambda: run.status == "completed")
        (done,) = self.manager.get_run(run.run_id)["prompt_history"]
        self.assertEqual(len(done["resolution"]["operator"]), 80)


if __name__ == "__main__":
    unittest.main()

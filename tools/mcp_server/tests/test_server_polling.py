"""Regression tests for server.py's lock-scoping split and the poll_sdk_command_until tool.

LockScopeConcurrencyTests proves standalone device commands (hhc_*/odtc_*) no longer wait
on the same _lock as an unrelated, slower STAR/Vantage command -- the whole point of
splitting the lock in _dispatch_sdk_command (see call_sdk_command's helper).

PollSdkCommandUntilTests exercises the new polling tool's own loop logic (numeric-tolerance
convergence, exact-equality convergence, timeout, and error short-circuit) against a
scripted fake of _dispatch_sdk_command, independent of any real device or client -- the
lock-scoping and dispatch behavior it builds on is already covered above and in
test_server_instrument_selection.py.
"""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

import hamilton_venus_mcp.server as srv


class _FakeClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self._session_id = "fake-session"

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeStarClient(_FakeClient):
    pass


class _FakeVantageClient(_FakeClient):
    pass


def _patch_clients(star_cls: type = _FakeStarClient):
    return (
        patch("hamilton_workflow_framework.session.StarClient", star_cls),
        patch("hamilton_workflow_framework.session.VantageClient", _FakeVantageClient),
    )


class LockScopeConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await srv.close_session()

    async def test_standalone_device_command_does_not_wait_on_a_slow_star_command(self) -> None:
        order: list[str] = []

        class _SlowFakeStarClient(_FakeStarClient):
            def instrument_is_idle(self) -> bool:
                time.sleep(0.5)
                order.append("star")
                return True

        p1, p2 = _patch_clients(_SlowFakeStarClient)
        with p1, p2:
            await srv.start_session(simulate=True, blank_deck=True)

        async def _fast_standalone_call() -> None:
            await srv.call_sdk_command("odtc_connect", {"device_ip": "127.0.0.1"})
            order.append("odtc")

        star_task = asyncio.create_task(srv.call_sdk_command("instrument_is_idle"))
        await asyncio.sleep(0.05)  # let the slow star call actually start (and take the lock) first
        await _fast_standalone_call()
        await star_task

        # Under the old single global lock, "odtc" would have had to wait for "star" to
        # release the lock first -- it finishes first here because standalone commands no
        # longer take that lock at all.
        self.assertEqual(order, ["odtc", "star"])


class PollSdkCommandUntilTests(unittest.IsolatedAsyncioTestCase):
    async def test_stops_once_stable_reads_consecutive_matches_within_tolerance(self) -> None:
        values = iter([30.0, 34.0, 38.0, 36.8, 37.1, 36.9])

        async def fake_dispatch(name: str, kwargs: dict | None) -> dict:
            return {
                "command": name,
                "status": "success",
                "timestamp": time.time(),
                "result": {"blockTemperature": next(values)},
            }

        with patch("hamilton_venus_mcp.server._dispatch_sdk_command", fake_dispatch):
            result = await srv.poll_sdk_command_until(
                "odtc_get_temperature",
                target=37.0,
                field="blockTemperature",
                tolerance=0.5,
                stable_reads=3,
                interval_s=0,
                timeout_s=5,
            )

        self.assertTrue(result["reached"])
        self.assertEqual([s["value"] for s in result["samples"]], [30.0, 34.0, 38.0, 36.8, 37.1, 36.9])

    async def test_exact_equality_path_for_a_bare_scalar_result(self) -> None:
        values = iter([False, False, True, True, True])

        async def fake_dispatch(name: str, kwargs: dict | None) -> dict:
            return {"command": name, "status": "success", "timestamp": time.time(), "result": next(values)}

        with patch("hamilton_venus_mcp.server._dispatch_sdk_command", fake_dispatch):
            result = await srv.poll_sdk_command_until(
                "instrument_is_idle", target=True, stable_reads=3, interval_s=0, timeout_s=5
            )

        self.assertTrue(result["reached"])
        self.assertEqual(len(result["samples"]), 5)

    async def test_times_out_without_reaching_target(self) -> None:
        async def fake_dispatch(name: str, kwargs: dict | None) -> dict:
            return {"command": name, "status": "success", "timestamp": time.time(), "result": {"blockTemperature": 0.0}}

        with patch("hamilton_venus_mcp.server._dispatch_sdk_command", fake_dispatch):
            result = await srv.poll_sdk_command_until(
                "odtc_get_temperature",
                target=37.0,
                field="blockTemperature",
                tolerance=0.5,
                stable_reads=3,
                interval_s=0.01,
                timeout_s=0.05,
            )

        self.assertFalse(result["reached"])
        self.assertGreater(len(result["samples"]), 0)

    async def test_stops_immediately_on_command_error_without_retrying(self) -> None:
        calls = 0

        async def fake_dispatch(name: str, kwargs: dict | None) -> dict:
            nonlocal calls
            calls += 1
            return {
                "command": name,
                "status": "error",
                "timestamp": time.time(),
                "error_type": "VenusCommandFailedError",
                "message": "boom",
            }

        with patch("hamilton_venus_mcp.server._dispatch_sdk_command", fake_dispatch):
            result = await srv.poll_sdk_command_until("odtc_get_temperature", target=37.0, field="blockTemperature")

        self.assertEqual(calls, 1)
        self.assertFalse(result["reached"])
        self.assertEqual(result["samples"], [])
        self.assertIn("error", result)
        self.assertEqual(result["error"]["message"], "boom")


if __name__ == "__main__":
    unittest.main()

"""When the stdio client goes (stdin closed: its conversation or app ended), the spoke closes the
session it left open, so VENUS's method doesn't keep running with nobody to drive it."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import hamilton_venus_mcp.__main__ as entry
import hamilton_venus_mcp.server as srv


class StdioExitTests(unittest.TestCase):
    def test_an_open_session_is_closed(self) -> None:
        with patch.object(srv, "_session_active", return_value=True), \
                patch.object(srv._session, "close", AsyncMock()) as close, \
                patch.object(srv._status_light, "off", AsyncMock()) as light_off:
            asyncio.run(srv.close_session_on_exit())
        close.assert_awaited_once()
        light_off.assert_awaited_once()

    def test_nothing_open_nothing_done(self) -> None:
        with patch.object(srv, "_session_active", return_value=False), \
                patch.object(srv._session, "close", AsyncMock()) as close:
            asyncio.run(srv.close_session_on_exit())
        close.assert_not_awaited()

    def test_stdio_run_closes_on_the_way_out_even_after_an_error(self) -> None:
        with patch.object(entry.mcp, "run_stdio_async", AsyncMock(side_effect=RuntimeError("pipe broke"))), \
                patch.object(entry, "close_session_on_exit", AsyncMock()) as on_exit:
            with self.assertRaises(RuntimeError):
                asyncio.run(entry._run_stdio())
        on_exit.assert_awaited_once()

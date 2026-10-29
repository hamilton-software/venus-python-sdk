from __future__ import annotations

import pytest

from hamilton_venus._internal._operator_prompts import (
    LiquidReloadPromptCallback,
    LiquidReloadPromptContext,
    TipReloadPromptCallback,
    TipReloadPromptContext,
    _invoke_callback,
)


def _ctx(attempt: int = 1) -> TipReloadPromptContext:
    return TipReloadPromptContext(
        tip_pool="Tips300",
        required=96,
        available=10,
        command="add_reagent",
        attempt=attempt,
    )


def _liquid_ctx(attempt: int = 1) -> LiquidReloadPromptContext:
    return LiquidReloadPromptContext(
        sources=("Buffer1", "Buffer2"),
        active_source="Buffer1",
        required=250.0,
        available=40.0,
        command="serial_dilution",
        attempt=attempt,
    )


class TestTipReloadPromptContext:
    def test_fields(self):
        ctx = _ctx(attempt=2)
        assert ctx.tip_pool == "Tips300"
        assert ctx.required == 96
        assert ctx.available == 10
        assert ctx.command == "add_reagent"
        assert ctx.attempt == 2

    def test_frozen(self):
        ctx = _ctx()
        with pytest.raises((AttributeError, TypeError)):
            ctx.attempt = 5  # type: ignore[misc]


class TestInvokeCallback:
    def test_sync_true(self):
        cb: TipReloadPromptCallback = lambda ctx: True  # noqa: E731
        assert _invoke_callback(cb, _ctx()) is True

    def test_sync_false(self):
        cb: TipReloadPromptCallback = lambda ctx: False  # noqa: E731
        assert _invoke_callback(cb, _ctx()) is False

    def test_sync_none_normalised_to_false(self):
        cb: TipReloadPromptCallback = lambda ctx: None  # type: ignore[return-value,assignment]  # noqa: E731
        assert _invoke_callback(cb, _ctx()) is False

    def test_async_true(self):
        async def cb(ctx: TipReloadPromptContext) -> bool:
            return True

        assert _invoke_callback(cb, _ctx()) is True

    def test_async_false(self):
        async def cb(ctx: TipReloadPromptContext) -> bool:
            return False

        assert _invoke_callback(cb, _ctx()) is False

    def test_sync_returning_awaitable(self):
        async def inner() -> bool:
            return True

        def cb(ctx: TipReloadPromptContext) -> object:
            return inner()

        assert _invoke_callback(cb, _ctx()) is True  # type: ignore[arg-type]

    def test_callback_receives_context(self):
        received: list[TipReloadPromptContext] = []

        def cb(ctx: TipReloadPromptContext) -> bool:
            received.append(ctx)
            return True

        ctx = _ctx(attempt=3)
        _invoke_callback(cb, ctx)
        assert received == [ctx]


class TestLiquidReloadPromptContext:
    def test_fields(self):
        ctx = _liquid_ctx(attempt=2)
        assert ctx.sources == ("Buffer1", "Buffer2")
        assert ctx.active_source == "Buffer1"
        assert ctx.required == 250.0
        assert ctx.available == 40.0
        assert ctx.command == "serial_dilution"
        assert ctx.attempt == 2

    def test_frozen(self):
        ctx = _liquid_ctx()
        with pytest.raises((AttributeError, TypeError)):
            ctx.attempt = 5  # type: ignore[misc]


class TestInvokeCallbackLiquidContext:
    def test_sync_true(self):
        cb: LiquidReloadPromptCallback = lambda ctx: True  # noqa: E731
        assert _invoke_callback(cb, _liquid_ctx()) is True

    def test_sync_none_normalised_to_false(self):
        cb: LiquidReloadPromptCallback = lambda ctx: None  # type: ignore[return-value,assignment]  # noqa: E731
        assert _invoke_callback(cb, _liquid_ctx()) is False

    def test_async_true(self):
        async def cb(ctx: LiquidReloadPromptContext) -> bool:
            return True

        assert _invoke_callback(cb, _liquid_ctx()) is True

    def test_callback_receives_context(self):
        received: list[LiquidReloadPromptContext] = []

        def cb(ctx: LiquidReloadPromptContext) -> bool:
            received.append(ctx)
            return True

        ctx = _liquid_ctx(attempt=3)
        _invoke_callback(cb, ctx)
        assert received == [ctx]

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hamilton_venus._internal._operator_prompts import TipReloadPromptContext
from hamilton_venus.compound_commands._helpers._tip_manager import (
    eject_tips,
    ensure_tips_available,
    pickup_tips,
    validate_tip_availability,
)
from hamilton_venus.exceptions import OperatorCancelledError


def _client_with_available_tips(*counts: int) -> MagicMock:
    """Build a mock client that returns the given total_available_tips on each call."""
    client = MagicMock()
    responses = []
    for n in counts:
        resp = MagicMock()
        resp.return_parameters.total_available_tips = n
        responses.append(resp)
    client.tip_pool_get_available_tips.side_effect = responses
    return client


class TestValidateTipAvailability:
    def test_sufficient_tips(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.return_parameters.total_available_tips = 96
        mock_client.tip_pool_get_available_tips.return_value = mock_resp

        validate_tip_availability(mock_client, "Tips300", 96)
        mock_client.tip_pool_get_available_tips.assert_called_once_with("Tips300")

    def test_insufficient_tips_raises(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.return_parameters.total_available_tips = 5
        mock_client.tip_pool_get_available_tips.return_value = mock_resp

        with pytest.raises(ValueError, match=r"5 tips available.*10 are required"):
            validate_tip_availability(mock_client, "Tips300", 10)

    def test_exact_tips_available(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.return_parameters.total_available_tips = 8
        mock_client.tip_pool_get_available_tips.return_value = mock_resp

        validate_tip_availability(mock_client, "Tips300", 8)


class TestPickupTips:
    def test_delegates_to_client(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_client.tip_pickup.return_value = mock_resp

        result = pickup_tips(mock_client, [1, 2, 3], "Tips300", optimized=True)

        mock_client.tip_pickup.assert_called_once_with(channels=[1, 2, 3], tip_pool="Tips300", optimized_pickup=True)
        assert result is mock_resp

    def test_optimized_false(self):
        mock_client = MagicMock()
        pickup_tips(mock_client, [1], "Tips300", optimized=False)
        mock_client.tip_pickup.assert_called_once_with(channels=[1], tip_pool="Tips300", optimized_pickup=False)


class TestEjectTips:
    def test_delegates_to_client(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_client.tip_eject.return_value = mock_resp

        result = eject_tips(mock_client, [1, 2, 3])

        mock_client.tip_eject.assert_called_once_with(channels=[1, 2, 3])
        assert result is mock_resp


class TestEnsureTipsAvailable:
    def test_sufficient_returns_immediately(self):
        client = _client_with_available_tips(96)
        client.on_tip_reload_prompt = None

        ensure_tips_available(client, "Tips300", 96, command_name="add_reagent")

        client.tip_pool_get_available_tips.assert_called_once_with("Tips300")
        client.tip_pool_reset_tip_counter.assert_not_called()

    def test_insufficient_no_callback_raises(self):
        client = _client_with_available_tips(5)
        client.on_tip_reload_prompt = None

        with pytest.raises(ValueError, match=r"5 tips available.*10 are required"):
            ensure_tips_available(client, "Tips300", 10, command_name="add_reagent")

    def test_single_reload_succeeds(self):
        client = _client_with_available_tips(5, 96)
        contexts: list[TipReloadPromptContext] = []

        def cb(ctx: TipReloadPromptContext) -> bool:
            contexts.append(ctx)
            return True

        client.on_tip_reload_prompt = cb
        ensure_tips_available(client, "Tips300", 10, command_name="add_reagent")

        assert len(contexts) == 1
        assert contexts[0].tip_pool == "Tips300"
        assert contexts[0].required == 10
        assert contexts[0].available == 5
        assert contexts[0].command == "add_reagent"
        assert contexts[0].attempt == 1
        client.tip_pool_reset_tip_counter.assert_called_once_with("Tips300")

    def test_multi_attempt_eventually_succeeds(self):
        client = _client_with_available_tips(2, 4, 96)
        attempts: list[int] = []

        def cb(ctx: TipReloadPromptContext) -> bool:
            attempts.append(ctx.attempt)
            return True

        client.on_tip_reload_prompt = cb
        ensure_tips_available(client, "Tips300", 10, command_name="add_reagent")

        assert attempts == [1, 2]
        assert client.tip_pool_reset_tip_counter.call_count == 2

    def test_operator_can_reload_many_times(self):
        client = _client_with_available_tips(2, 3, 4, 5, 6, 96)
        attempts: list[int] = []

        def cb(ctx: TipReloadPromptContext) -> bool:
            attempts.append(ctx.attempt)
            return True

        client.on_tip_reload_prompt = cb
        ensure_tips_available(client, "Tips300", 10, command_name="add_reagent")

        assert attempts == [1, 2, 3, 4, 5]
        assert client.tip_pool_reset_tip_counter.call_count == 5

    def test_operator_cancels(self):
        client = _client_with_available_tips(2)
        client.on_tip_reload_prompt = lambda ctx: False

        with pytest.raises(OperatorCancelledError, match=r"cancelled tip reload"):
            ensure_tips_available(client, "Tips300", 10, command_name="add_reagent")

        client.tip_pool_reset_tip_counter.assert_not_called()

    def test_operator_returns_none_cancels(self):
        client = _client_with_available_tips(2)
        client.on_tip_reload_prompt = lambda ctx: None

        with pytest.raises(OperatorCancelledError):
            ensure_tips_available(client, "Tips300", 10, command_name="add_reagent")

    def test_async_callback(self):
        client = _client_with_available_tips(2, 96)
        calls: list[TipReloadPromptContext] = []

        async def cb(ctx: TipReloadPromptContext) -> bool:
            calls.append(ctx)
            return True

        client.on_tip_reload_prompt = cb
        ensure_tips_available(client, "Tips300", 10, command_name="add_reagent")

        assert len(calls) == 1
        assert calls[0].attempt == 1

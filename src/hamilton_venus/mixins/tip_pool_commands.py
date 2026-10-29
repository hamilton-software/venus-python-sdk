"""Tip pool management methods for StarClient (System category)."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.models import (
    CommandResponse,
    SetTipCounterParameters,
    ShowTipCountersParameters,
    ShowTipCountersResponse,
    TipPoolAvailableTipsResponse,
    TipPoolCounterResponse,
    TipPoolCountersResponse,
    TipPoolEmptyTipsResponse,
    TipPoolMissingRacksResponse,
    TipPoolParameters,
    TipRackState,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

_ResponseT = TypeVar("_ResponseT", bound=CommandResponse)


class TipPoolCommandsMixin:
    """Mixin providing tip pool management commands."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    def _run_untimed(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Run a tip pool command with the command timeout disabled.

        Tip pool commands run in VENUS's tip management library, which can take
        arbitrarily long (it re-parses the deck layout, and the show dialogs wait
        on the user), so none of them are bound by the command timeout.
        """
        with self._connected_instrument.override_command_timeout(None):
            return self._run(coro)

    @staticmethod
    def _parse_response(model_type: type[_ResponseT], response: CommandResponse) -> _ResponseT:
        return model_type.model_validate(response.model_dump(by_alias=True))

    def tip_pool_get_tip_counters(self) -> TipPoolCountersResponse:
        """Return all tip counter states."""
        response = self._run_untimed(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="tipPool.getTipCounters",
            )
        )
        return self._parse_response(TipPoolCountersResponse, response)

    def tip_pool_get_tip_counter(self, tip_pool: str) -> TipPoolCounterResponse:
        """Return the tip counter state for the specified tip pool."""
        parameters = TipPoolParameters(tip_pool=tip_pool)
        response = self._run_untimed(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="tipPool.getTipCounter",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(TipPoolCounterResponse, response)

    def tip_pool_get_available_tips(self, tip_pool: str) -> TipPoolAvailableTipsResponse:
        """Return the number of available tips in the specified tip pool."""
        parameters = TipPoolParameters(tip_pool=tip_pool)
        response = self._run_untimed(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="tipPool.getAvailableTips",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(TipPoolAvailableTipsResponse, response)

    def tip_pool_get_empty_tips(self, tip_pool: str) -> TipPoolEmptyTipsResponse:
        """Return empty tip information for the specified tip pool."""
        parameters = TipPoolParameters(tip_pool=tip_pool)
        response = self._run_untimed(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="tipPool.getEmptyTips",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(TipPoolEmptyTipsResponse, response)

    def tip_pool_get_missing_racks(self, tip_pool: str) -> TipPoolMissingRacksResponse:
        """Return the missing rack indices for the specified tip pool."""
        parameters = TipPoolParameters(tip_pool=tip_pool)
        response = self._run_untimed(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="tipPool.getMissingRacks",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return self._parse_response(TipPoolMissingRacksResponse, response)

    def tip_pool_initialize_tip_counter(self, tip_pool: str) -> CommandResponse:
        """Initialize the tip counter for the specified tip pool."""
        parameters = TipPoolParameters(tip_pool=tip_pool)
        return self._run_untimed(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="tipPool.initializeTipCounter",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def tip_pool_reset_tip_counter(self, tip_pool: str) -> CommandResponse:
        """Reset the tip counter for the specified tip pool."""
        parameters = TipPoolParameters(tip_pool=tip_pool)
        return self._run_untimed(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="tipPool.resetTipCounter",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def tip_pool_set_tip_counter(
        self,
        tip_pool: str,
        available_tips: list[dict[str, TipRackState]],
    ) -> CommandResponse:
        """Set the tip counter state for the specified tip pool.

        Replaces the pool's whole state. Each entry names a rack (its labware id)
        and lists the positions that hold a tip; a listed rack holds exactly those
        tips, and one listed with no positions is on the deck but empty (an empty
        top NTR rack is moved to the NTR waste at the next pickup). A rack left out
        is marked missing (not on the deck) and reported by ``missing_racks``.
        ``count`` is not used.
        """
        parameters = SetTipCounterParameters(
            tip_pool=tip_pool,
            available_tips=available_tips,
        )
        return self._run_untimed(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="tipPool.setTipCounter",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def tip_pool_show_tip_counter(self, tip_pool: str) -> CommandResponse:
        """Show the tip counter dialog for the specified tip pool.

        This blocks on user interaction with the dialog, so like every tip pool
        command it runs with the command timeout disabled.

        The dialog is drawn by VENUS on the instrument PC's own console -- it is
        **not** visible over a network connection (an MCP spoke/hub, a remote
        WorkflowSession, etc.). A caller with no console session on that machine
        only ever sees this call block until *someone at the instrument* closes
        the dialog, then receives whatever the return value is; it has no way to
        read or drive the dialog's contents itself. For remote/automated tip
        counter updates, use ``tip_pool_initialize_tip_counter``,
        ``tip_pool_reset_tip_counter``, ``tip_pool_set_tip_counter``, and
        ``tip_pool_get_tip_counter``/``tip_pool_get_tip_counters`` instead --
        none of those open a dialog.
        """
        parameters = TipPoolParameters(tip_pool=tip_pool)
        return self._run_untimed(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="tipPool.showTipCounter",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def tip_pool_show_tip_counters(self, tip_pools: list[str] | None = None) -> ShowTipCountersResponse:
        """Show the tip counter dialog for the specified tip pools, or every tip
        pool if *tip_pools* is omitted.

        This blocks on user interaction with the dialog, so like every tip pool
        command it runs with the command timeout disabled.

        Same caveat as ``tip_pool_show_tip_counter``: the dialog is local to the
        instrument PC's own console and is invisible to a remote/network caller
        (an MCP spoke/hub included) -- only the eventual return value is seen.
        Use ``tip_pool_initialize_tip_counter``/``tip_pool_reset_tip_counter``/
        ``tip_pool_set_tip_counter``/``tip_pool_get_tip_counter(s)`` for
        automated, dialog-free tip counter updates.
        """
        parameters = ShowTipCountersParameters(tip_pools=tip_pools)
        response = self._run_untimed(
            self._connected_instrument.venus.send_command(
                category="System",
                action_name="tipPool.showTipCounters",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return self._parse_response(ShowTipCountersResponse, response)


from __future__ import annotations

from typing import TYPE_CHECKING

from hamilton_venus._internal._operator_prompts import (
    TipReloadPromptContext,
    _invoke_callback,
)
from hamilton_venus.exceptions import OperatorCancelledError
from hamilton_venus.models.commands import CommandResponse

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient


def validate_tip_availability(client: InstrumentClient, tip_pool: str, required: int) -> None:
    """Raise ``ValueError`` if *tip_pool* has fewer than *required* tips available."""
    resp = client.tip_pool_get_available_tips(tip_pool)
    available = resp.return_parameters.total_available_tips
    if available < required:
        raise ValueError(f"Tip pool '{tip_pool}' has {available} tips available, but {required} are required.")


def ensure_tips_available(
    client: InstrumentClient,
    tip_pool: str,
    required: int,
    *,
    command_name: str,
) -> None:
    """Ensure *tip_pool* has at least *required* tips, prompting the operator if needed.

    If the pool already has enough tips this returns immediately.  Otherwise
    behaviour depends on ``client.on_tip_reload_prompt``:

    * If no callback is configured, ``ValueError`` is raised (strict behaviour,
      matches :func:`validate_tip_availability`).
    * If a callback is configured, it is invoked with a
      :class:`~hamilton_venus._internal._operator_prompts.TipReloadPromptContext`.
      The operator is prompted repeatedly until enough tips are available or the
      operator cancels. A truthy return means the operator has reloaded the rack —
      the tip counter is reset via ``tip_pool_reset_tip_counter`` and the
      availability is re-checked. A falsy return raises
      :class:`~hamilton_venus.exceptions.OperatorCancelledError`.

    Args:
        client: Connected instrument client used for tip-pool queries and reset.
        tip_pool: Name of the tip pool to check.
        required: Minimum number of tips the caller needs.
        command_name: Name of the compound command issuing the prompt; surfaced
            to the callback for UI labelling.

    Raises:
        ValueError: No callback is configured and tips are insufficient.
        OperatorCancelledError: The operator cancelled the reload prompt.
    """
    available = client.tip_pool_get_available_tips(tip_pool).return_parameters.total_available_tips
    if available >= required:
        return

    callback = client.on_tip_reload_prompt
    if callback is None:
        raise ValueError(f"Tip pool '{tip_pool}' has {available} tips available, but {required} are required.")

    attempt = 1
    while True:
        # A tip pool can span multiple physical racks on the deck. When the operator
        # reloads a rack, tip_pool_reset_tip_counter resets the counter and the
        # next availability check accumulates tips from all racks currently in the
        # pool. This loop allows unlimited reloads until sufficient tips are available.
        context = TipReloadPromptContext(
            tip_pool=tip_pool,
            required=required,
            available=available,
            command=command_name,
            attempt=attempt,
        )
        if not _invoke_callback(callback, context):
            raise OperatorCancelledError(
                f"Operator cancelled tip reload for '{tip_pool}' (required={required}, available={available})."
            )
        client.tip_pool_reset_tip_counter(tip_pool)
        available = client.tip_pool_get_available_tips(tip_pool).return_parameters.total_available_tips
        if available >= required:
            return
        attempt += 1


def pickup_tips(
    client: InstrumentClient,
    channels: list[int],
    tip_pool: str,
    optimized: bool = True,
) -> CommandResponse:
    """Pick up tips from *tip_pool* on the given *channels* and return the raw response."""
    return client.tip_pickup(channels=channels, tip_pool=tip_pool, optimized_pickup=optimized)


def eject_tips(client: InstrumentClient, channels: list[int]) -> CommandResponse:
    """Eject tips on the given *channels* and return the raw response."""
    return client.tip_eject(channels=channels)

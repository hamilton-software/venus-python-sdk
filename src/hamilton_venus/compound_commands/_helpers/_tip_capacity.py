"""Tip-capacity resolution helper shared by compound commands.

Provides :func:`_resolve_tip_capacity`, used by compound commands that need to
know the maximum aspiratable volume for the tips currently assigned to a tip
pool (e.g. ``add_reagent``, ``hit_picking``, ``copy_plate``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient


def _resolve_tip_capacity(client: InstrumentClient, tip_pool: str) -> float:
    """Return the maximum aspiratable volume (µL) for the tips in *tip_pool*.

    Calls :meth:`~hamilton_venus.star_client.StarClient.tip_pool_get_tip_counter`
    to identify the tip-type id currently assigned to the pool, then looks up
    ``"Max Liquid Volume"`` in the tip-type catalogue returned by
    :meth:`~hamilton_venus.star_client.StarClient.get_tip_types`.

    Args:
        client: Connected :class:`~hamilton_venus.star_client.StarClient`.
        tip_pool: Name of the tip pool whose capacity should be queried.

    Returns:
        Maximum liquid volume in µL for the tip type assigned to *tip_pool*.

    Raises:
        ValueError: If the tip-pool counter has no tip-type assigned (counter
            uninitialized) or the resolved tip-type id is not present in the
            instrument's tip-type catalogue.
        KeyError: If the catalogue entry is missing the
            ``"Max Liquid Volume"`` key (instrument configuration mismatch).
    """
    counter = client.tip_pool_get_tip_counter(tip_pool)
    params = counter.return_parameters
    tip_type_id = params.tip_type_id or (str(params.tip_type) if params.tip_type >= 0 else "")
    tip_types = client.get_tip_types()
    tip_types_map: dict[str, dict[str, Any]] = tip_types.return_parameters.tip_types
    if not tip_type_id:
        raise ValueError(
            f"Could not determine tip type for pool '{tip_pool}': "
            "tip_pool_get_tip_counter returned no tip type information. "
            "Ensure the tip counter is initialized before running the compound command."
        )
    if tip_type_id not in tip_types_map:
        known = sorted(tip_types_map)
        raise ValueError(
            f"Tip type id '{tip_type_id}' assigned to pool '{tip_pool}' is not "
            f"present in the instrument tip-type catalogue (known ids: {known}). "
            "Check that the deck layout and tip-type catalogue are in sync."
        )
    return float(tip_types_map[tip_type_id]["Max Liquid Volume"])

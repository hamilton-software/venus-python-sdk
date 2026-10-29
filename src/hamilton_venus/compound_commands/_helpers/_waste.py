from __future__ import annotations

from typing import TYPE_CHECKING

from hamilton_venus.compound_commands._helpers._base import resolve_selector_positions
from hamilton_venus.exceptions import VenusCommandFailedError
from hamilton_venus.models.position import Position

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient

DEFAULT_WASTE_LABWARE = "liquid_waste"


def resolve_waste_position(client: InstrumentClient, selector: str | None = None) -> Position:
    """Resolve a waste position, falling back to the deck's fixed ``liquid_waste`` labware.

    When *selector* is provided it is treated as an explicit selector override
    (any ``Labware@expression`` accepted by :func:`resolve_selector_positions`).
    When *selector* is ``None`` the established SDK convention applies and the
    fixed ``liquid_waste`` deck labware is used.  In both cases the first
    resolved position is returned.  The labware definition is looked up via the
    client's labware-definition cache, so repeated calls during a single client
    session do not incur additional deck queries.

    Args:
        client: Connected :class:`~hamilton_venus.star_client.StarClient`.
        selector: Optional explicit waste selector string.  When ``None``,
            defaults to the fixed ``liquid_waste`` labware.

    Returns:
        The first :class:`~hamilton_venus.models.position.Position` resolved
        from *selector* (or from ``liquid_waste`` when *selector* is ``None``).

    Raises:
        ValueError: If the waste labware is not present on the deck, or the
            selector resolves to no positions.  Callers that only need waste
            optionally (e.g. ``pre_aliquot_disposal`` / ``discard_last_excess``)
            should surface this as a configuration error.
    """
    target = selector if selector is not None else DEFAULT_WASTE_LABWARE
    try:
        positions = resolve_selector_positions(client, target)
    except VenusCommandFailedError as exc:
        if selector is None:
            message = (
                f"waste disposal requires a labware named {DEFAULT_WASTE_LABWARE!r} on the "
                "deck. Add it to the deck layout or provide an explicit waste location."
            )
        else:
            message = f"waste location {selector!r} could not be resolved on the deck."
        raise ValueError(message) from exc

    if not positions:
        raise ValueError(f"waste location {target!r} resolved to no positions.")

    return positions[0]

"""Multi-plate selector helpers shared by compound commands.

These helpers let parameter-driven compound commands accept either a single
selector string or a list of selectors that span multiple labware ids.
Multi-channel strokes still execute one plate at a time; the chunking helpers
enforce that invariant.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from hamilton_venus.models.enums import WellOrder
from hamilton_venus.models.position import Position

from ._base import resolve_selector_positions

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient


def extract_labware_id(selector: str | Position) -> str:
    """Return the labware id referenced by *selector*.

    Accepts a raw ``Labware`` / ``Labware@expression`` selector string (the
    labware id is the substring before ``@``) or an already-resolved
    :class:`Position` (whose ``.labware`` field is returned directly).
    """
    if isinstance(selector, Position):
        return selector.labware
    return selector.split("@", 1)[0]


def normalize_selector_list(
    selector: str | list[str] | Position | list[Position],
) -> list[str | Position]:
    """Wrap a single selector/``Position`` into a one-element list; pass lists through.

    Mirrors the ``[x] if isinstance(x, str) else list(x)`` idiom used across
    the compound commands, extended to treat a single :class:`Position` the
    same as a single selector string rather than attempting ``list(x)`` on
    it (``Position`` is a pydantic model, not a real sequence of selectors).
    """
    if isinstance(selector, (str, Position)):
        return [selector]
    return list(selector)


def resolve_multi_selector(
    client: InstrumentClient,
    selector: str | list[str] | Position | list[Position],
    *,
    well_order: WellOrder | None = None,
) -> list[Position]:
    """Resolve one selector or a list of selectors into a flat ordered position list.

    Passing a ``str`` or a pre-resolved ``Position`` is equivalent to calling
    :func:`resolve_selector_positions` directly. Passing a ``list`` of either
    (mixed lists are allowed) resolves each element in order and concatenates
    the resulting position lists; plate order follows list order, and
    ``well_order`` applies within each plate independently. A bare
    ``Position`` entry is not re-expanded through the selector DSL: it is
    already a concrete well and is returned as-is (mirroring
    :func:`~hamilton_venus.models.position.normalize_positions`'s existing
    ``Position`` pass-through).

    Args:
        client: Connected instrument client for deck queries.
        selector: A single ``Labware@expression`` selector, a single
            ``Position``, or a list mixing either.
        well_order: Optional traversal order applied within each plate.

    Returns:
        A flat list of :class:`Position` objects. The list may span multiple
        labware ids; downstream consumers must use
        :func:`split_positions_by_plate` or
        :func:`chunk_positions_per_plate` before issuing multi-channel
        commands.

    Raises:
        TypeError: If ``selector`` (or a list entry) is not a ``str``,
            ``Position``, or ``list``.
        ValueError: If ``selector`` is an empty list, or a ``str`` entry is
            empty.
    """
    if isinstance(selector, (str, Position)):
        return resolve_selector_positions(client, selector, well_order=well_order)

    if not isinstance(selector, list):
        raise TypeError(f"selector must be a str, Position, or list, got {type(selector).__name__}")
    if not selector:
        raise ValueError("selector list must contain at least one entry")
    # Two passes are intentional: validate every entry before resolving any of
    # them so a malformed entry late in the list does not produce a partial
    # resolution (or trigger hardware-touching lookups) for earlier entries.
    # Selector lists are expected to be short, so the extra loop is negligible.
    for entry in selector:
        if not isinstance(entry, (str, Position)):
            raise TypeError(f"selector list entries must be str or Position, got {type(entry).__name__}")
        if isinstance(entry, str) and not entry:
            raise ValueError("selector list entries must be non-empty strings")

    out: list[Position] = []
    for entry in selector:
        out.extend(resolve_selector_positions(client, entry, well_order=well_order))
    return out


def split_positions_by_plate(
    positions: list[Position],
) -> list[tuple[str, list[Position]]]:
    """Group consecutive same-plate runs in ``positions``.

    Returns ``[(plate_id, sub_positions), ...]`` preserving the input order.
    A plate that appears non-contiguously (e.g. A, B, A) yields three
    entries; the helper does not re-sort.
    """
    if not positions:
        return []
    groups: list[tuple[str, list[Position]]] = []
    current_plate = positions[0].labware
    current: list[Position] = [positions[0]]
    for pos in positions[1:]:
        if pos.labware == current_plate:
            current.append(pos)
        else:
            groups.append((current_plate, current))
            current_plate = pos.labware
            current = [pos]
    groups.append((current_plate, current))
    return groups


def chunk_positions_per_plate(
    positions: list[Position],
    chunk_size: int,
) -> Iterator[list[Position]]:
    """Yield chunks of up to ``chunk_size`` consecutive positions.

    A chunk never crosses a plate boundary: if the next position is on a
    different labware, the current chunk is emitted early and a new chunk
    starts.

    Args:
        positions: Flat position list (may span multiple plates).
        chunk_size: Maximum chunk length. Must be at least 1.

    Yields:
        Lists of positions, all from the same labware, of length ≤
        ``chunk_size``.

    Raises:
        ValueError: If ``chunk_size`` < 1.
    """
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    if not positions:
        return
    current: list[Position] = [positions[0]]
    for pos in positions[1:]:
        if pos.labware != current[0].labware or len(current) >= chunk_size:
            yield current
            current = [pos]
        else:
            current.append(pos)
    yield current

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from hamilton_venus.constants import CHANNEL_PITCH_MM_1ML, MAX_CHANNELS
from hamilton_venus.models.enums import WellOrder
from hamilton_venus.models.position import Position, normalize_positions

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.models.command_types import ChannelDispenseResponse
    from hamilton_venus.models.liquid_handling_settings import DispenseSettings

_T = TypeVar("_T")

DEFAULT_CHANNELS: list[int] = [1, 2, 3, 4, 5, 6, 7, 8]


def validate_channels(channels: list[int]) -> None:
    """Raise ``ValueError`` if *channels* is empty, too long, out of range, or contains duplicates."""
    if not channels:
        raise ValueError("channels must not be empty")
    if len(channels) > MAX_CHANNELS:
        raise ValueError(f"channels must have at most {MAX_CHANNELS} entries, got {len(channels)}")
    for ch in channels:
        if ch < 1 or ch > MAX_CHANNELS:
            raise ValueError(f"channel values must be between 1 and {MAX_CHANNELS}, got {ch}")
    if len(set(channels)) != len(channels):
        raise ValueError(f"channels must not contain duplicates, got {channels}")


def resolve_plate_wells(
    client: InstrumentClient,
    plate_name: str,
) -> list[Position]:
    """Resolve every well of *plate_name* in the order required for 8-channel transfer.

    Looks up the labware definition via the client's cache (fetching from
    the deck on first access).  For plates with well spacing information
    (e.g., 384-well at 4.5 mm) the returned positions are reordered using
    the spacing-aware interleaving engine so they can be processed by
    8-channel commands correctly.
    """
    return normalize_positions(
        f"{plate_name}@all",
        get_spec=client.get_labware_spec,
        channel_pitch_mm=CHANNEL_PITCH_MM_1ML,
    )


def resolve_selector_positions(
    client: InstrumentClient,
    selector: str | Position,
    *,
    well_order: WellOrder | None = None,
) -> list[Position]:
    """Resolve a ``Labware@expression`` selector to ordered well positions.

    Mirrors :func:`resolve_plate_wells` but honours the full selector DSL
    (``@A1``, ``@A1:C3``, ``@col:1,3:5``, ``@row:A,C:E``, ``@wells:...``,
    ``@all``, and a bare labware id -- equivalent to ``@all`` in
    :func:`normalize_positions` itself).

    Args:
        client: Connected instrument client for deck queries.
        selector: Selector string in the form ``"Labware"`` or
            ``"Labware@expression"``, or an already-resolved ``Position``,
            which is returned as-is (still passed through the spacing-aware
            interleaving reorder -- see ``normalize_positions``).
        well_order: Optional traversal order. When ``None`` (default), the order
            implied by the selector itself is used (typically ``COL_ASC``). When
            provided, overrides the default traversal of positions returned by
            the selector. Ignored for selectors with an explicit wells list
            (``@wells:``, ``@A1,B2,...``) where order is user-defined.

    Returns:
        List of Position objects in the order implied by the selector, with
        spacing-aware interleaving applied for high-density plates.
    """
    kwargs: dict[str, Any] = {
        "get_spec": client.get_labware_spec,
        "channel_pitch_mm": CHANNEL_PITCH_MM_1ML,
    }
    if well_order is not None:
        kwargs["well_order"] = well_order

    return normalize_positions(selector, **kwargs)


def slice_settings(settings: Any, n: int) -> Any:
    """Truncate any per-channel list fields in *settings* to length *n*.

    If *settings* is a Pydantic model, each field whose value is a list longer
    than *n* is sliced to ``[:n]``.  Returns the original object unchanged if
    no truncation is needed or if *settings* is not a Pydantic model.
    """
    if settings is None:
        return None
    if not isinstance(settings, BaseModel):
        return settings
    updates: dict[str, Any] = {}
    for field_name in type(settings).model_fields:
        value = getattr(settings, field_name)
        if isinstance(value, list) and len(value) > n:
            updates[field_name] = value[:n]
    if updates:
        return settings.model_copy(update=updates)
    return settings


def override_mix_cycles(settings: DispenseSettings | None, value: int = 0) -> DispenseSettings | None:
    """Return a copy of *settings* with ``mix_cycles`` overridden to *value*.

    Preserves per-channel list shape when the input is a list; collapses to a
    scalar otherwise.  ``None`` in, ``None`` out.
    """
    if settings is None:
        return None
    current = settings.mix_cycles
    if isinstance(current, list):
        new_value: int | list[int] = [value] * len(current)
    else:
        new_value = value
    return settings.model_copy(update={"mix_cycles": new_value})


def mix_cycles_active(settings: DispenseSettings | None) -> bool:
    """Return ``True`` iff *settings* requests at least one mix cycle on any channel."""
    if settings is None:
        return False
    cycles = settings.mix_cycles
    if isinstance(cycles, list):
        return any(c > 0 for c in cycles)
    return cycles > 0


def emit_final_mix(
    client: InstrumentClient,
    dest_pos: Position | list[Position],
    mix_channels: list[int],
    dispense_settings: DispenseSettings | None,
) -> ChannelDispenseResponse:
    """Issue a single zero-volume dispense that performs the caller's mix at the destination.

    Called only when a mix is requested and the caller's
    ``dispense_settings.mix_cycles`` is active.  The dispense uses the caller's
    full ``dispense_settings`` (so ``mix_cycles`` / ``mix_volume`` /
    ``mix_position`` are honoured) but with ``volume=0`` so no additional
    liquid is delivered.

    ``dest_pos`` may be a single :class:`Position` (broadcast across every
    channel in ``mix_channels``) or a list of positions (one per channel, so
    each channel mixes at its own well).  A list must match the length of
    ``mix_channels``.
    """
    if isinstance(dest_pos, list):
        if len(dest_pos) != len(mix_channels):
            raise ValueError(
                f"emit_final_mix received {len(dest_pos)} positions for "
                f"{len(mix_channels)} channels; counts must match."
            )
        positions = dest_pos
    else:
        positions = [dest_pos] * len(mix_channels)
    sliced = slice_settings(dispense_settings, len(mix_channels))
    kwargs: dict[str, Any] = {
        "channels": mix_channels,
        "positions": positions,
        "volumes": 0.0,
    }
    if sliced is not None:
        kwargs["settings"] = sliced
    return client.dispense(**kwargs)

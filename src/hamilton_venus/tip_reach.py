"""Can the tip reach where it is pipetting without the channel going in after it?

A tip only reaches ``length_below_channel`` below the channel's stop disk (its full length
minus the collar on the channel). When it pipettes deeper into a well or tube than that,
the channel itself goes inside the container and can touch
its wall: a contamination risk. A 50 µL tip in a 100 mm tube is the classic case; a 300 µL
tip is less likely to go that deep with liquid level detection, and a 1000 µL tip clears it.

Two cases:
- Pipetting at a fixed height without liquid level detection: checked exactly -- the channel
  goes inside when the fixed height plus the tip's length below the channel is under the rim.
- With liquid level detection the tip goes to the liquid, so only the last of the liquid
  takes it near the bottom. It warns when the tip reaches less than half the container's
  depth (LLD_MIN_REACH_FRACTION): in a 100 mm tube that flags a 50 µL tip (42.4 mm) but not a
  300 µL (51.9 mm) or 1000 µL tip.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from hamilton_venus.liquid_class_library import DEVICE_LABELS, TipTypeInfo

# How far the channel's lower end may go below a container's rim and still count as safe: it
# is narrow enough there not to reach the wall of a tube. A 1000 µL tip at a 5 mm fixed
# height in a 100 mm tube (98.9 mm deep) puts it 6.8 mm inside -- fine; a 300 µL tip there
# would put it 42 mm inside -- not.
CHANNEL_INSIDE_ALLOWANCE_MM = 10.0
# With liquid level detection, a tip must reach at least this fraction of the container depth.
LLD_MIN_REACH_FRACTION = 0.5


def container_depth(definition: dict[str, Any]) -> float | None:
    """The deepest container of a labware definition (``labware_get_params_from_id``), in mm."""
    depths = []
    for grid in (definition.get("containerGrids") or {}).values():
        container = (grid or {}).get("containerDefinition") or {}
        depth = container.get("totalDepth")
        if isinstance(depth, (int, float)) and depth > 0:
            depths.append(float(depth))
    return max(depths) if depths else None


def rack_tip_type(definition: dict[str, Any], device: str) -> int | None:
    """The tip type a tip rack holds, from its definition's Hamilton rack properties."""
    properties = ((definition.get("customAttributes") or {}).get("hamilton:rck_properties")) or {}
    key = "MlStarCore96TipRack" if device == "head_96" else "MlStarTipRack"
    value = properties.get(key)
    return int(value) if isinstance(value, (int, float)) else None


_SPECIAL_TIP_WORDS = ("piercing", "wide bore", "slim", "rocket", "needle", "tubetool", "tool")


def _is_special_tip(tip: TipTypeInfo) -> bool:
    name = tip.name.lower()
    return any(word in name for word in _SPECIAL_TIP_WORDS)


class TipReach(BaseModel):
    """Whether a tip reaches the bottom of a container without the channel going inside."""

    ok: bool
    labware: str
    container_depth: float
    tip_type_id: int
    tip_name: str
    tip_length_below_channel: float
    lowest_tip_height: float = Field(description="Lowest the tip end may go, in mm above the container bottom.")
    channel_inside_mm: float = Field(description="How far the channel would go below the rim (0 when clear).")
    message: str
    longer_tips: list[str] = Field(default_factory=list)


def assess_tip_reach(
    tip: TipTypeInfo,
    *,
    labware: str,
    depth: float,
    lowest_tip_height: float = 0.0,
    device: str = "channels_1000ul",
    registered: dict[int, TipTypeInfo] | None = None,
    fixed_height: bool = False,
) -> TipReach:
    """Compare a tip's length below the channel with how deep it pipettes into a container."""
    length = tip.length_below_channel or 0.0
    channel_height = lowest_tip_height + length  # above the container bottom
    inside = max(0.0, round(depth - channel_height, 1))
    needed = depth - CHANNEL_INSIDE_ALLOWANCE_MM - lowest_tip_height if fixed_height else depth * LLD_MIN_REACH_FRACTION
    ok = length >= needed
    longer = []
    if not ok and registered:
        fits = [
            t for t in registered.values()
            if t.tip_class == "tip" and t.visible and t.usable_on(device)
            and (t.length_below_channel or 0.0) >= needed
        ]
        # Standard tips first; piercing, wide-bore, slim and other special tips only after them.
        fits.sort(key=lambda t: (_is_special_tip(t), t.max_liquid_volume, t.length_below_channel or 0.0))
        longer = [f"{t.name} ({t.length_below_channel:g} mm)" for t in fits[:3]]
    if ok and fixed_height:
        message = (f"{tip.name} reaches {length:g} mm below the channel; at {lowest_tip_height:g} mm in {labware} "
                   f"({depth:g} mm deep) the channel stays clear of the container.")
    elif ok:
        message = (f"{tip.name} reaches {length:g} mm below the channel, at least half of {labware}'s "
                   f"{depth:g} mm depth, so with liquid level detection the channel stays out of the container.")
    else:
        if fixed_height:
            safe_height = round(depth - CHANNEL_INSIDE_ALLOWANCE_MM - length, 1)
            where = (f"At the fixed height of {lowest_tip_height:g} mm the channel itself would be "
                     f"{inside:g} mm inside the container, where it can touch the wall; with this tip, pipette "
                     f"at {safe_height:g} mm or higher.")
        else:
            safe_height = round(depth - CHANNEL_INSIDE_ALLOWANCE_MM - length, 1)
            where = (f"With liquid level detection, the channel itself goes far enough inside the container to "
                     f"touch the wall once the tip is lower than {safe_height:g} mm above the bottom -- "
                     f"when the liquid is that low, or the tip follows it down; at the bottom it would be "
                     f"{inside:g} mm inside.")
        message = (
            f"Contamination risk: {tip.name} reaches only {length:g} mm below the channel, but {labware} is "
            f"{depth:g} mm deep. {where}"
        )
        device_label = DEVICE_LABELS.get(device, device)
        message += f" Use a longer tip on the {device_label}: {', '.join(longer)}." if longer else (
            " No registered tip on this device is long enough; pipette higher (fixed height) instead.")
    return TipReach(
        ok=ok, labware=labware, container_depth=depth, tip_type_id=tip.id, tip_name=tip.name,
        tip_length_below_channel=length, lowest_tip_height=lowest_tip_height, channel_inside_mm=inside,
        message=message, longer_tips=longer,
    )


def lowest_tip_heights(parameters: dict[str, Any], count: int) -> list[tuple[float, bool]]:
    """Per channel of a wire-format aspirate / dispense / detect-liquid-level command: the
    lowest tip height to assume, and whether it is a fixed height (no liquid level detection)."""

    def per_channel(key: str, default: Any) -> list[Any]:
        value = parameters.get(key, default)
        return list(value) if isinstance(value, list) else [value] * count

    fixed = per_channel("fixedHeight", None)
    clld = per_channel("capacitiveLLD", 0)
    plld = per_channel("pressureLLD", 0)
    heights = []
    for i in range(count):
        lld = bool(clld[i] if i < len(clld) else 0) or bool(plld[i] if i < len(plld) else 0)
        height = fixed[i] if i < len(fixed) else None
        if not lld and isinstance(height, (int, float)):
            heights.append((max(0.0, float(height)), True))
        else:
            heights.append((0.0, False))
    return heights

"""Spacing-aware well sequencing engine.

Reorders expanded well lists to account for the mismatch between physical
channel pitch (distance between adjacent pipetting channels) and labware
well spacing.  When the channel pitch is larger than the well spacing, wells
must be interleaved so that each simultaneous channel group targets
physically reachable positions.

Traversal axis determines which spacing dimension is relevant:

- **Column traversal** (``COL_ASC`` / ``COL_DESC``): channels move along
  rows within each column → Y spacing.
- **Row traversal** (``ROW_ASC`` / ``ROW_DESC``): channels move along
  columns within each row → X spacing.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from hamilton_venus.models.enums import WellOrder

TraversalAxis = Literal["COLUMN", "ROW"]

_PLATE_WELL_RE = re.compile(r"^(?P<row>[A-Z]+)(?P<col>\d+)$")


def infer_traversal_axis(
    expression: str | None,
    well_order: WellOrder,
    pattern: Literal["COLUMN_MAJOR", "ROW_MAJOR"] = "COLUMN_MAJOR",
    pattern_applies: bool = True,
) -> TraversalAxis:
    """Infer the traversal axis from the selector expression and well order.

    Precedence:

    1. Explicit column or row selector prefix (``col:``, ``row:``).
    2. ``@all`` follows the labware indexing *pattern*, when ``pattern_applies``
       (numerically addressed labware; alphanumeric plates skip this and
       fall through to ``well_order``, matching how ``@all`` is expanded).
    3. ``well_order`` direction (column-oriented vs row-oriented).
    """
    if expression is not None:
        if expression.startswith("col:"):
            return "COLUMN"
        if expression.startswith("row:"):
            return "ROW"
        if expression == "all" and pattern_applies:
            return "COLUMN" if pattern == "COLUMN_MAJOR" else "ROW"
    if well_order in (WellOrder.ROW_ASC, WellOrder.ROW_DESC):
        return "ROW"
    return "COLUMN"


def get_axis_spacing(
    well_spacing_x_mm: float | None,
    well_spacing_y_mm: float | None,
    axis: TraversalAxis,
) -> float | None:
    """Return the well spacing relevant to the given traversal axis."""
    if axis == "COLUMN":
        return well_spacing_y_mm
    return well_spacing_x_mm


def compute_interleaved_sequence(
    wells: list[str],
    channel_pitch_mm: float,
    well_spacing_mm: float,
    axis: TraversalAxis,
    row_labels: tuple[str, ...],
) -> list[str]:
    """Reorder *wells* to account for channel-to-well spacing mismatch.

    When ``channel_pitch_mm`` exceeds ``well_spacing_mm``, wells within each
    traversal group are split into *lanes* so that each batch of channels
    targets physically reachable positions.

    Returns *wells* unchanged when no interleaving is necessary.
    """
    if well_spacing_mm <= 0 or channel_pitch_mm <= 0:
        return list(wells)

    # Compute skip_factor using ceil to ensure channels never overlap.
    # ceil ensures that for any ratio >= 1, we interleave appropriately.
    # For ratios < 1 (channel pitch smaller than well spacing), ceil returns 1
    # and no interleaving is needed.
    ratio = channel_pitch_mm / well_spacing_mm
    skip_factor = math.ceil(ratio)

    if skip_factor <= 1:
        return list(wells)

    if all(w.strip().isdigit() for w in wells):
        return _interleave_numeric(wells, skip_factor)

    if axis == "COLUMN":
        return _interleave_by_column(wells, skip_factor, row_labels)
    return _interleave_by_row(wells, skip_factor)


def _interleave_by_column(
    wells: list[str],
    skip_factor: int,
    row_labels: tuple[str, ...],
) -> list[str]:
    """Interleave plate wells within each column group by physical row index."""
    row_index_map = {label: idx for idx, label in enumerate(row_labels)}
    groups: dict[int, list[tuple[int, str]]] = {}
    group_order: list[int] = []

    for well in wells:
        row_idx, col = _parse_plate_components(well, row_index_map)
        if col not in groups:
            groups[col] = []
            group_order.append(col)
        groups[col].append((row_idx, well))

    result: list[str] = []
    for col in group_order:
        entries = groups[col]
        entries.sort(key=lambda x: x[0])
        lanes: dict[int, list[str]] = {}
        for row_idx, well in entries:
            lane = row_idx % skip_factor
            lanes.setdefault(lane, []).append(well)
        for lane_idx in sorted(lanes):
            result.extend(lanes[lane_idx])
    return result


def _interleave_by_row(
    wells: list[str],
    skip_factor: int,
) -> list[str]:
    """Interleave plate wells within each row group by physical column index."""
    groups: dict[str, list[tuple[int, str]]] = {}
    group_order: list[str] = []
    row_index_map: dict[str, int] = {}

    for well in wells:
        row_label, col = _parse_plate_label_and_column(well)
        if row_label not in row_index_map:
            row_index_map[row_label] = len(row_index_map)
        if row_label not in groups:
            groups[row_label] = []
            group_order.append(row_label)
        groups[row_label].append((col, well))

    result: list[str] = []
    for row_label in group_order:
        entries = groups[row_label]
        entries.sort(key=lambda x: x[0])
        lanes: dict[int, list[str]] = {}
        for col, well in entries:
            lane = (col - 1) % skip_factor
            lanes.setdefault(lane, []).append(well)
        for lane_idx in sorted(lanes):
            result.extend(lanes[lane_idx])
    return result


def _interleave_numeric(
    wells: list[str],
    skip_factor: int,
) -> list[str]:
    """Interleave numeric (tube rack) wells by their integer value."""
    lanes: dict[int, list[str]] = {}
    for well in wells:
        lane = (int(well) - 1) % skip_factor
        lanes.setdefault(lane, []).append(well)
    result: list[str] = []
    for lane_idx in sorted(lanes):
        result.extend(lanes[lane_idx])
    return result


def _parse_plate_label_and_column(well: str) -> tuple[str, int]:
    """Return ``(row_label, column_number)`` for a plate-format well."""
    normalized = well.strip().upper()
    match = _PLATE_WELL_RE.fullmatch(normalized)
    if not match:
        raise ValueError(f"cannot parse plate well: {well!r}")
    row_label = match.group("row")
    col = int(match.group("col"))
    return row_label, col


def _parse_plate_components(
    well: str,
    row_index_map: dict[str, int],
) -> tuple[int, int]:
    """Return ``(row_index, column_number)`` for a plate-format well."""
    row_label, col = _parse_plate_label_and_column(well)
    row_idx = row_index_map.get(row_label)
    if row_idx is None:
        raise ValueError(f"unknown row label {row_label!r} in well {well!r}")
    return row_idx, col


__all__ = [
    "TraversalAxis",
    "compute_interleaved_sequence",
    "get_axis_spacing",
    "infer_traversal_axis",
]

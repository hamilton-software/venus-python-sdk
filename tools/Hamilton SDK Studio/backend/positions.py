"""Position selectors for the wells wizard: compose `Plate1@A1:C3` from clicked wells, and read one back.

The grammar is the SDK's selector DSL (see docs/examples/position_and_well_selection.md): `@A1`, `@A1,B2`,
`@A1:C3` (a rectangle), `@col:1:3,5`, `@row:A:D,F`, `@all`. Reading uses the SDK's own parser, so what the
wizard shows for an existing value is exactly what the SDK would pick. Composing picks the shortest form
that selects the same wells: everything, whole columns, whole rows, then rectangles.
"""

from __future__ import annotations

import re
import string
from typing import Any

_WELL = re.compile(r"^([A-Za-z]+)(\d+)$")


def row_label(index: int) -> str:
    """0 -> A ... 25 -> Z, 26 -> AA ... (the VENUS convention used for 1536-well plates)."""
    label = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        label = string.ascii_uppercase[remainder] + label
    return label


def row_index(label: str) -> int:
    value = 0
    for char in label.upper():
        value = value * 26 + (ord(char) - 64)
    return value - 1


def parse_well(well: str) -> tuple[int, int]:
    """'B3' -> (row 1, column 3), zero-based row, one-based column."""
    match = _WELL.match(well.strip())
    if not match:
        raise ValueError(f"{well!r} is not a well name like A1")
    return row_index(match.group(1)), int(match.group(2))


def _runs(values: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for value in sorted(values):
        if runs and value == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], value)
        else:
            runs.append((value, value))
    return runs


def _joined(runs: list[tuple[int, int]], name: Any = str) -> str:
    return ",".join(name(a) if a == b else f"{name(a)}:{name(b)}" for a, b in runs)


def compose(labware: str, rows: int, cols: int, wells: list[str], compact: bool = True) -> str:
    """The selector for `wells` on a labware with `rows` x `cols` wells ('' when nothing is selected).

    With compact=False the wells are listed one by one in the order given (which is the order channels
    will take them); otherwise the shortest equivalent form is used and the wells come in plate order."""
    cells = {parse_well(w) for w in wells}
    for row, col in cells:
        if not (0 <= row < rows and 1 <= col <= cols):
            raise ValueError(f"{row_label(row)}{col} is outside a {rows} x {cols} labware")
    if not cells:
        return ""
    if not compact:
        seen: set[tuple[int, int]] = set()
        ordered = [parse_well(w) for w in wells if not ((p := parse_well(w)) in seen or seen.add(p))]
        return f"{labware}@" + ",".join(f"{row_label(r)}{c}" for r, c in ordered)
    if len(cells) == rows * cols:
        return f"{labware}@all"

    full_cols = [c for c in range(1, cols + 1) if all((r, c) in cells for r in range(rows))]
    if cells == {(r, c) for c in full_cols for r in range(rows)}:
        return f"{labware}@col:" + _joined(_runs(full_cols))
    full_rows = [r for r in range(rows) if all((r, c) in cells for c in range(1, cols + 1))]
    if cells == {(r, c) for r in full_rows for c in range(1, cols + 1)}:
        return f"{labware}@row:" + _joined(_runs(full_rows), lambda r: row_label(r))

    covered: set[tuple[int, int]] = set()
    parts: list[str] = []
    for col in range(1, cols + 1):  # rectangles, found in plate order: down a column, then across
        for row in range(rows):
            if (row, col) not in cells or (row, col) in covered:
                continue
            bottom = row
            while bottom + 1 < rows and (bottom + 1, col) in cells and (bottom + 1, col) not in covered:
                bottom += 1
            right = col
            while right + 1 <= cols and all((r, right + 1) in cells and (r, right + 1) not in covered for r in range(row, bottom + 1)):
                right += 1
            covered.update((r, c) for r in range(row, bottom + 1) for c in range(col, right + 1))
            start, end = f"{row_label(row)}{col}", f"{row_label(bottom)}{right}"
            parts.append(start if start == end else f"{start}:{end}")
    return f"{labware}@" + ",".join(parts)


def expand(selector: str, rows: int, cols: int) -> dict[str, Any]:
    """The wells a selector picks on a rows x cols labware, by the SDK's own parser: {"labware", "wells"}.
    Raises ValueError with the SDK's message for a selector it cannot read."""
    from hamilton_venus.models import LabwareLayoutSpec, normalize_positions

    positions = normalize_positions(selector.strip(), get_spec=lambda _labware: LabwareLayoutSpec(rows=rows, cols=cols))
    labware = selector.partition("@")[0].strip()
    return {"labware": labware, "wells": [getattr(p, "well", str(p)) for p in positions]}


def split_fragments(value: str) -> list[str]:
    """A positions field's text as its fragments: `Plate1@A1;Plate2@B2` -> two."""
    return [part.strip() for part in value.split(";") if part.strip()]

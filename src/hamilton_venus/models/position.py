"""Position models and Python-side selector domain-specific language (DSL) expansion helpers.

This module normalizes flexible SDK inputs such as selector strings,
``Position`` objects, and wire-format dictionaries into concrete
``labwareId``/``wellId`` pairs before command payloads are serialized.
The backend wire contract still uses explicit ``LabwareWell[]`` entries.

The selector domain-specific language (DSL) uses ``Labware@expression`` syntax. Supported expressions
include:

- ``Plate1``: no expression; equivalent to ``Plate1@all``
- ``Plate1@A1``: a single well -- repeated across all requested channels
  when more than one channel is used (e.g. every tip drawing from one
  reservoir well)
- ``Plate1@A1,B1,C1`` or ``Plate1@wells:A1,B1,C1``: explicit wells
- ``Plate1@A1:C3``: a rectangular well range
- ``Plate1@row:A,C:E``: one or more labware rows
- ``Plate1@col:1,3:5``: one or more labware columns
- ``Plate1@all``: all wells on the labware

Well addressing follows the labware definition, not a geometry heuristic.
Each definition's ``indexing.index`` field selects the addressing mode:
``index == 1`` (alphanumeric) labels wells ``<row><col>`` with rows ``A``-``Z``
for the first 26 rows and Excel-style two-letter labels ``AA``-``ZZ``
thereafter (e.g., row 27 is ``AA``, row 29 is ``AC``); ``index == 0`` (numeric)
labels wells by a single running number (``"1"``, ``"2"``, ...).  This lets
1536-well plates (32 rows: ``A``-``AF``) and numeric reservoirs/troughs/tube
racks each be addressed naturally.  When ``indexing.index`` is absent the SDK
assumes alphanumeric (the standard-plate default).

Numeric well numbers run in the definition's ``indexing.pattern`` order:
``COLUMN_MAJOR`` numbers down each column first, ``ROW_MAJOR`` numbers across
each row first.  The ``indexing.first``/``start``/``increment`` fields are
carrier-slot / orientation bookkeeping and do not shift well labels, so they
are ignored for addressing.

Input is forgiving: either form may be supplied regardless of the labware's
native mode (e.g., ``"A1"`` on a numeric labware or ``"1"`` on an alphanumeric
labware) and is translated to the labware's canonical form in the resulting
``Position.well`` values.  Ambiguous or out-of-range input raises a clear
``ValueError``.

Expanded wells are ordered using ``WellOrder``. ``WellOrder.CUSTOM``
preserves the input order for explicit well lists.

Labware geometry (rows, columns, well spacing, indexing pattern) is
discovered automatically by querying the connected deck.  Callers
upstream of :func:`normalize_positions` pass a ``get_spec`` callback
that resolves a labware id to a :class:`LabwareLayoutSpec`; the
:class:`~hamilton_venus.star_client.StarClient` exposes such a
callback via :meth:`~hamilton_venus.star_client.StarClient.get_labware_spec`,
which caches results for the lifetime of the client.

IMPORTANT -- labware id casing: VENUS stores every labware id on the deck layout
lower-cased, regardless of the case an ``add_*`` command was called with (e.g.
``add_reservoir(..., labware_id="Trough1")`` is later reported back by VENUS, and
by every SDK event/response that echoes it, as ``"trough1"``). The DSL's
``Labware@expression`` parsing above only lower-cases the well-selector keyword
(``row:``/``col:``/``wells:``); the ``Labware`` portion is passed through exactly
as typed and is matched against VENUS's own (lower-cased) storage server-side, so
a selector string itself does not need to be lower-cased by the caller. But any
code that compares a labware id it *typed* against one it *read back* from VENUS
(a tracking event's ``labwareName``, ``get_labware_spec``/``get_added_plates``
results, a cache keyed by labware id, etc.) must account for the mismatch --
normalize both sides (e.g. ``.lower()``) before comparing, rather than relying on
the caller's original casing surviving the round trip. ``taught_locations.py``'s
``_norm``/``carrier_site_key`` helpers are the one place in this SDK that already
does this; nothing else here normalizes automatically.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hamilton_venus.models.enums import WellOrder

if TYPE_CHECKING:
    from hamilton_venus.models.labware_definition import LabwareDefinition

WellSelector: TypeAlias = str
PositionDict: TypeAlias = dict[str, str]
SpecResolver: TypeAlias = Callable[[str], "LabwareLayoutSpec"]

_PLATE_WELL_RE = re.compile(r"^(?P<row>[A-Za-z]+)(?P<col>\d+)$")
_NUMERIC_WELL_RE = re.compile(r"^\d+$")
_ALPHA_RE = re.compile(r"^[A-Za-z]+$")
# Excel-style row labels run from A-Z (1..26) then AA-ZZ (27..702).
# 1536-well plates use 32 rows (A-Z, AA-AF); the SDK caps multi-column
# labware at ZZ (702 rows) which covers every plausible plate format.
_MAX_MULTI_COLUMN_ROWS = 26 + 26 * 26  # 702
_T = TypeVar("_T")


def _index_to_alpha_label(index: int) -> str:
    """Convert a 0-based row index to an Excel-style alphabetic label (A, B, ..., Z, AA, AB, ...)."""
    if index < 0:
        raise ValueError(f"row index must be >= 0, got {index}")
    label = ""
    n = index
    while True:
        label = chr(ord("A") + n % 26) + label
        n = n // 26 - 1
        if n < 0:
            return label


def _alpha_label_to_index(label: str) -> int:
    """Convert an Excel-style alphabetic label (A, B, ..., Z, AA, AB, ...) to a 0-based row index."""
    if not label or not _ALPHA_RE.fullmatch(label):
        raise ValueError(f"invalid alphabetic row label: {label!r}")
    n = 0
    for ch in label.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _row_labels(count: int) -> tuple[str, ...]:
    return tuple(_index_to_alpha_label(i) for i in range(count))


class LabwareLayoutSpec(BaseModel):
    """Describes labware grid dimensions, well spacing, and indexing pattern.

    The SDK builds these automatically via :meth:`from_definition` whenever
    it fetches a labware definition from the connected deck, and caches
    the result on the client.  Most users never need to construct one
    directly.

    Direct construction is supported for two cases:

    * Unit tests that exercise position-resolution logic without a deck
      connection.
    * Overriding the deck's reported geometry for a specific labware
      instance, by passing the spec to
      :meth:`~hamilton_venus.star_client.StarClient.register_labware_definition`.
    """

    model_config = ConfigDict(frozen=True)

    rows: int = 8
    cols: int = 12
    well_spacing_x_mm: float | None = None
    well_spacing_y_mm: float | None = None
    pattern: Literal["COLUMN_MAJOR", "ROW_MAJOR"] = "COLUMN_MAJOR"
    connected_container: bool = False
    """Whether the labware's positions all draw from one physically connected
    liquid (e.g. a reagent reservoir whose several row positions share a single
    trough).  When ``True`` multiple channels may access the container
    simultaneously, each at a distinct position, rather than draining the
    positions one at a time.  Derived from the definition's
    ``rack_layout.connected_container`` field; defaults to ``False``.
    """
    numeric_addressing: bool = False
    """Whether wells are addressed by numeric position (``"1"``, ``"2"``, ...)
    rather than alphanumeric plate coordinates (``"A1"``).

    Derived from the labware definition's ``indexing.index`` field
    (``0`` -> numeric, ``1`` -> alphanumeric).  Numeric labware includes
    troughs, single-container reservoirs, tube/sample carriers, and tip
    racks; alphanumeric labware includes standard micro-titre plates.
    Defaults to ``False`` (alphanumeric) so the deck-free 8x12 fallback
    behaves like a standard plate.
    """

    @field_validator("rows")
    @classmethod
    def _validate_rows(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"rows must be >= 1, got {v}")
        return v

    @field_validator("cols")
    @classmethod
    def _validate_cols(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"cols must be >= 1, got {v}")
        return v

    @model_validator(mode="after")
    def _validate_rows_cols_combination(self) -> LabwareLayoutSpec:
        # Multi-column labware uses Excel-style row labels (A-Z, then AA-ZZ),
        # capped at ZZ = 702 rows. This covers 1536-well plates (32 rows: A-AF)
        # and any plausible future plate format.
        if self.cols > 1 and self.rows > _MAX_MULTI_COLUMN_ROWS:
            raise ValueError(
                f"multi-column labware (cols > 1) is limited to {_MAX_MULTI_COLUMN_ROWS} rows "
                f"(A-Z, AA-ZZ), got {self.rows}"
            )
        return self

    @property
    def row_labels(self) -> tuple[str, ...]:
        # Geometric row labels are always Excel-style alphabetic labels
        # ("A".."Z", then "AA".."ZZ"), independent of the labware's
        # addressing mode.  They are used for the ``row:`` selector and for
        # spacing-aware interleaving.  Numeric labware still emits numeric
        # well IDs (see :attr:`numeric_addressing` and :meth:`cell_to_number`).
        return _row_labels(self.rows)

    @property
    def col_labels(self) -> tuple[int, ...]:
        return tuple(range(1, self.cols + 1))

    @property
    def well_count(self) -> int:
        """Total number of wells/positions on the labware."""
        return self.rows * self.cols

    def cell_to_number(self, row_index: int, col: int) -> int:
        """Map a ``(0-based row, 1-based column)`` cell to its 1-based well number.

        The traversal order follows the definition's ``pattern``:
        ``COLUMN_MAJOR`` numbers down each column first, ``ROW_MAJOR``
        numbers across each row first.
        """
        if self.pattern == "ROW_MAJOR":
            return row_index * self.cols + (col - 1) + 1
        return (col - 1) * self.rows + row_index + 1

    def number_to_cell(self, number: int) -> tuple[int, int]:
        """Inverse of :meth:`cell_to_number`; returns ``(0-based row, 1-based column)``."""
        index = number - 1
        if self.pattern == "ROW_MAJOR":
            return index // self.cols, index % self.cols + 1
        return index % self.rows, index // self.rows + 1

    def emit_well(self, row_index: int, col: int) -> str:
        """Emit a well ID for a ``(0-based row, 1-based column)`` cell in the labware's canonical addressing form."""
        if self.numeric_addressing:
            return str(self.cell_to_number(row_index, col))
        return f"{self.row_labels[row_index]}{col}"

    @classmethod
    def from_definition(cls, payload: LabwareDefinition | dict[str, Any]) -> LabwareLayoutSpec:
        """Parse a ``LabwareLayoutSpec`` from a VENUS labware definition payload.

        Accepts a :class:`~hamilton_venus.models.labware_definition.LabwareDefinition`
        instance **or** a raw dictionary in one of these shapes:

        1. A ``urn:hamilton:schemas:microlab:labware:v1`` definition (has ``containerGrids``).
        2. Full ``labware_get_definition()`` response (has ``returnParameters.definition.containerGrids``).
        3. The legacy ``rack_layout`` shape (has ``rows`` and ``columns``), retained for
           test doubles and any payload that predates the v1 schema.
        """
        from hamilton_venus.models.labware_definition import (
            LabwareDefinition as _LabwareDefinition,
        )

        if isinstance(payload, _LabwareDefinition):
            return cls._from_container_grids(payload.model_dump(by_alias=True))

        if isinstance(payload, dict):
            definition = _extract_labware_v1_definition(payload)
            if definition is not None:
                return cls._from_container_grids(definition)

        rack_layout = _extract_rack_layout(payload)
        rows = rack_layout.get("rows")
        cols = rack_layout.get("columns")
        if rows is None or cols is None:
            raise ValueError(
                "Could not find 'rows' and 'columns' in the provided labware definition payload. "
                "Expected a full labware_get_definition() response, a definition object, or a rack_layout object."
            )
        rows_invalid = not isinstance(rows, int) or rows <= 0
        cols_invalid = not isinstance(cols, int) or cols <= 0
        irregular_wells = rack_layout.get("irregular_wells")
        if rows_invalid and cols_invalid and isinstance(irregular_wells, list) and irregular_wells:
            # Single-container labware with no regular grid (e.g. a reagent
            # trough addressed as several virtual positions sharing one
            # physical container) -- irregular_wells is the real well count.
            rows, cols = 1, len(irregular_wells)
        else:
            # Apply sensible defaults if rows or cols are 0 or negative
            # (e.g., for waste containers with incomplete definitions)
            rows = 1 if rows_invalid else rows
            cols = 1 if cols_invalid else cols
        spacing_x = rack_layout.get("well_spacing_x_mm")
        spacing_y = rack_layout.get("well_spacing_y_mm")
        indexing = rack_layout.get("indexing", {})
        pattern_raw = indexing.get("pattern", "COLUMN_MAJOR")
        pattern: Literal["COLUMN_MAJOR", "ROW_MAJOR"] = "ROW_MAJOR" if pattern_raw == "ROW_MAJOR" else "COLUMN_MAJOR"
        # indexing.index: 0 -> numeric addressing, 1 -> alphanumeric.  When the
        # field is absent we assume alphanumeric (the standard-plate default)
        # rather than numeric so incomplete payloads behave like a plate.
        numeric_addressing = indexing.get("index", 1) == 0
        return cls(
            rows=rows,
            cols=cols,
            well_spacing_x_mm=spacing_x,
            well_spacing_y_mm=spacing_y,
            pattern=pattern,
            connected_container=bool(rack_layout.get("connected_container", False)),
            numeric_addressing=numeric_addressing,
        )

    @classmethod
    def _from_container_grids(cls, definition: dict[str, Any]) -> LabwareLayoutSpec:
        """Build a spec from a ``urn:hamilton:schemas:microlab:labware:v1`` definition.

        The v1 schema replaces the old flat ``rack_layout`` with a
        ``containerGrids`` map.  Regular labware exposes a single grid;
        irregular racks are decomposed into several uniform-pitch grids,
        which are flattened into a single row of positions the same way
        the legacy ``irregular_wells`` list was.
        """
        grids = [grid for grid in definition["containerGrids"].values() if isinstance(grid, dict)]
        if not grids:
            raise ValueError(
                "Labware definition has an empty 'containerGrids' map; cannot derive a layout."
            )
        connected = bool(definition.get("connectedContainerGroups"))

        if len(grids) > 1:
            # Irregular rack: no single regular grid, so address the
            # positions linearly (1..N) like the legacy irregular_wells path.
            total = sum(int(g.get("rows", 0)) * int(g.get("columns", 0)) for g in grids)
            first = grids[0]
            return cls(
                rows=1,
                cols=max(total, 1),
                well_spacing_x_mm=first.get("columnPitch"),
                well_spacing_y_mm=first.get("rowPitch"),
                pattern="ROW_MAJOR",
                connected_container=connected,
                numeric_addressing=True,
            )

        grid = grids[0]
        rows = int(grid.get("rows", 0))
        cols = int(grid.get("columns", 0))
        naming = grid.get("namingConvention", {})
        return cls(
            rows=rows if rows > 0 else 1,
            cols=cols if cols > 0 else 1,
            well_spacing_x_mm=grid.get("columnPitch"),
            well_spacing_y_mm=grid.get("rowPitch"),
            pattern="ROW_MAJOR" if grid.get("iterationOrder") == "row_major" else "COLUMN_MAJOR",
            connected_container=connected,
            numeric_addressing=naming.get("rowStyle") == "numeric",
        )


def _extract_labware_v1_definition(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return the v1-schema definition dict inside *payload*, or ``None``.

    Mirrors the shapes accepted by :func:`_extract_rack_layout`: the payload
    may be the definition itself or a full ``labware_get_definition()`` response.
    """
    if isinstance(payload.get("containerGrids"), dict):
        return payload

    defn = payload.get("returnParameters", {}).get("definition", {})
    if isinstance(defn, dict) and isinstance(defn.get("containerGrids"), dict):
        return defn

    return None


def _extract_rack_layout(payload: dict[str, Any]) -> dict[str, Any]:
    """Walk through possible payload shapes to find the rack_layout dict."""
    if "rows" in payload and "columns" in payload:
        return payload

    if "rack_layout" in payload:
        return dict(payload["rack_layout"])

    rp = payload.get("returnParameters", {})
    defn = rp.get("definition", {})
    if "rack_layout" in defn:
        return dict(defn["rack_layout"])

    raise ValueError(
        "Could not locate rack_layout in the provided payload. "
        "Expected a full labware_get_definition() response, a definition object, or a rack_layout object."
    )


class Position(BaseModel):
    """Concrete labware/well location used in command payloads."""

    model_config = ConfigDict(populate_by_name=True)

    labware: str = Field(..., alias="labwareId")
    well: str = Field(..., alias="wellId")

    def to_dict(self) -> dict[str, str]:
        """Return the wire-format representation for this position."""
        return {"labwareId": self.labware, "wellId": self.well}


# Defined here (after Position), not up near PositionDict, specifically so it can
# reference the real Position class directly instead of a quoted "Position" forward
# reference. A forward-referenced Union built at import time never gets a chance to
# resolve -- nothing in this module ever called .rebuild()/get_type_hints() on it
# afterward -- so any TypeAdapter built from it downstream (e.g.
# hamilton_venus_mcp's reflection-based catalog) stays permanently in pydantic's
# "not fully defined" state and fails on first use, regardless of the value passed.
# There's no real circularity here (Position doesn't need PositionInput to be
# defined), so defining this after Position avoids the forward reference entirely
# instead of papering over it with an explicit rebuild call.
PositionInput: TypeAlias = str | list[str] | PositionDict | list[PositionDict] | Position | list[Position]

_DEFAULT_SPEC = LabwareLayoutSpec()


def normalize_positions(
    positions: PositionInput,
    well_order: WellOrder = WellOrder.COL_ASC,
    channel_count: int | None = None,
    *,
    get_spec: SpecResolver | None = None,
    channel_pitch_mm: float | None = None,
    total_wells: int | None = None,
) -> list[Position]:
    """Normalize SDK position input into concrete ``Position`` entries.

    Accepted input forms include selector strings, lists of selector strings,
    wire-format dictionaries, and ``Position`` objects.

    Selector string forms:

    - ``Plate1``
    - ``Plate1@A1``
    - ``Plate1@A1,B1,C1``
    - ``Plate1@wells:A1,B1,C1``
    - ``Plate1@A1:C3``
    - ``Plate1@row:A,C:E``
    - ``Plate1@col:1,3:5``
    - ``Plate1@all``

    Selector expansions are ordered according to ``well_order``. When
    ``channel_count`` is provided, the first ``N`` expanded positions are used.
    A single expanded well is repeated to fill ``N`` channels; otherwise, if
    fewer than ``N`` positions are available, ``ValueError`` is raised.

    When ``get_spec`` is provided, the labware grid (rows/columns/spacing/
    indexing pattern) is resolved per-labware via the callback (typically
    backed by the SDK's labware-definition cache).  When ``get_spec`` is
    ``None``, a default 8x12 layout is assumed; this fallback exists so
    that pure-dict / pure-``Position`` inputs can be normalized without a
    deck connection.

    When ``channel_pitch_mm`` is available alongside well spacing data the
    expanded well list is reordered using the spacing-aware interleaving
    engine so that each simultaneous channel group targets physically
    reachable positions.

    Args:
        positions: One or more position selectors to normalize.
        well_order: Ordering applied to expanded wells.
        channel_count: Optional limit on the number of positions returned.
        get_spec: Optional callback resolving a labware id to a
            :class:`LabwareLayoutSpec`.  When provided, layout information
            is looked up per-labware.  When ``None``, a default 8x12
            layout is used (suitable for dict and ``Position`` inputs
            which need no DSL expansion).
        channel_pitch_mm: Physical distance between adjacent pipetting
            channels (mm).  When provided together with well spacing data the
            interleaving engine reorders wells automatically.
        total_wells: Optional cap on the number of positions returned.
            Applied as a final truncation after all expansion, ordering,
            interleaving, and ``channel_count`` logic. If fewer than
            ``total_wells`` positions are available, all available positions
            are returned with no error (unlike ``channel_count``, which
            raises in that case).

    Notes:

    - A bare labware selector such as ``Plate1`` is equivalent to
      ``Plate1@all``: it expands to every well on the labware.
    - A selector that resolves to exactly one well (e.g. ``Plate1@A1``) is
      repeated across all requested channels when ``channel_count > 1``,
      rather than being treated as a channel-count mismatch -- this is how
      "every channel draws from the same reservoir well" is expressed.
    - Lists of selector strings are flattened in order before any
      ``channel_count`` truncation is applied.
    - ``WellOrder.CUSTOM`` preserves the declared order of explicit wells.
    - ``total_wells`` truncates the final result and never raises, even when
      the available position count is smaller than ``total_wells`` -- this is
      intentionally simpler than ``channel_count``'s broadcast/raise behavior
      and is independent of it.

    Examples:

    - ``normalize_positions("Plate1@A1")`` -> ``[Position(labware="Plate1", well="A1")]``
    - ``normalize_positions("Plate1@A1", channel_count=8)`` -> eight ``Plate1/A1`` positions
    - ``normalize_positions("Plate1@A1,B1,C1")`` -> ``A1``, ``B1``, ``C1``
    - ``normalize_positions("Plate1@A1:C2", well_order=WellOrder.COL_ASC)``
      -> ``A1``, ``B1``, ``C1``, ``A2``, ``B2``, ``C2``
    - ``normalize_positions("Plate1@row:A,B", channel_count=4)``
      -> first 4 expanded positions from rows ``A`` and ``B``
    - ``normalize_positions("Plate1", channel_count=8)``
      -> first 8 wells of ``Plate1@all``
    - ``normalize_positions("Plate1@all", total_wells=17)`` -> the first 17
      of ``Plate1``'s 96 wells, in ``well_order`` (e.g. distributing 17
      samples across a 96-well plate without hand-writing a 17-well selector)
    """
    from hamilton_venus.models.well_sequencing import (
        compute_interleaved_sequence,
        get_axis_spacing,
        infer_traversal_axis,
    )

    def _resolve(labware_id: str) -> LabwareLayoutSpec:
        if get_spec is None:
            return _DEFAULT_SPEC
        return get_spec(labware_id)

    normalized: list[Position]
    # Spec of the first labware encountered.  Only consulted for
    # spacing-aware interleaving below, so resolution is deferred for
    # input shapes (Position / dict / Position-list / dict-list) that do
    # not require DSL expansion.  This keeps pure-Position inputs
    # deck-free even when ``get_spec`` is provided.
    primary_spec: LabwareLayoutSpec | None = None

    if isinstance(positions, Position):
        normalized = [positions]
    elif isinstance(positions, str):
        labware, _ = _split_selector(positions)
        primary_spec = _resolve(labware)
        normalized = _expand_selector(positions, well_order, primary_spec)
    elif isinstance(positions, dict):
        normalized = [Position.model_validate(positions)]
    elif isinstance(positions, list):
        if not positions:
            normalized = []
        elif all(isinstance(item, str) for item in positions):
            normalized = []
            for selector in positions:
                labware, _ = _split_selector(cast(str, selector))
                spec = _resolve(labware)
                if primary_spec is None:
                    primary_spec = spec
                normalized.extend(_expand_selector(cast(str, selector), well_order, spec))
        elif all(isinstance(item, (dict, Position)) for item in positions):
            normalized = [item if isinstance(item, Position) else Position.model_validate(item) for item in positions]
        else:
            raise ValueError("positions list must contain only strings, dicts, or Position objects")
    else:
        raise ValueError(
            "positions must be a string, list of strings, dict, list of dicts, Position, or list of Position"
        )

    # Apply spacing-aware interleaving when physically necessary.  The
    # spec lookup is deferred until here so that callers passing
    # pre-resolved Position/dict inputs without ``channel_pitch_mm`` do
    # not trigger a deck query.
    if channel_pitch_mm is not None and normalized:
        if primary_spec is None:
            primary_spec = _resolve(normalized[0].labware)
        expression = _extract_expression(positions)
        axis = infer_traversal_axis(
            expression,
            well_order,
            primary_spec.pattern,
            pattern_applies=primary_spec.numeric_addressing,
        )
        spacing = get_axis_spacing(primary_spec.well_spacing_x_mm, primary_spec.well_spacing_y_mm, axis)
        if spacing is not None and spacing > 0:
            well_ids = [p.well for p in normalized]
            labware_ids = [p.labware for p in normalized]
            reordered = compute_interleaved_sequence(well_ids, channel_pitch_mm, spacing, axis, primary_spec.row_labels)

            # Build a mapping from well to the list of labware IDs in original occurrence order.
            position_map: dict[str, list[str]] = {}
            for p in normalized:
                if p.well not in position_map:
                    position_map[p.well] = []
                position_map[p.well].append(p.labware)

            # Track per-well cursor for sequential consumption of labware assignments.
            well_cursor: dict[str, int] = {}

            if len(set(labware_ids)) <= 1:
                # Single labware: preserve labware ID
                single_labware = labware_ids[0] if labware_ids else ""
                normalized = [Position(labware=single_labware, well=w) for w in reordered]
            else:
                # Multiple labwares: consume sequentially from per-well list of labware IDs.
                # Raise if a well is requested more times than provided.
                result_positions: list[Position] = []
                for well in reordered:
                    labware_list = position_map.get(well, [])
                    if not labware_list:
                        result_positions.append(Position(labware="", well=well))
                    else:
                        cursor = well_cursor.get(well, 0)
                        if cursor >= len(labware_list):
                            raise ValueError(
                                f"well {well!r} requested {cursor + 1} times but only {len(labware_list)} "
                                f"labware(s) provided for it"
                            )
                        labware = labware_list[cursor]
                        well_cursor[well] = cursor + 1
                        result_positions.append(Position(labware=labware, well=well))
                normalized = result_positions

    if channel_count is not None:
        # A single resolved well (an explicit "Plate1@A1"-style selector, or a
        # single-well dict/Position) used across multiple channels means "the
        # same well for every channel" -- e.g. all 8 tips drawing from one
        # reservoir well -- so repeat it rather than treating it as a mismatch.
        if len(normalized) == 1 and channel_count > 1:
            normalized = normalized * channel_count
        elif len(normalized) < channel_count:
            raise ValueError(
                f"positions expanded to {len(normalized)} entries, but {channel_count} channel(s) were requested"
            )
        normalized = normalized[:channel_count]

    if total_wells is not None:
        normalized = normalized[:total_wells]

    return normalized


def _extract_expression(positions: PositionInput) -> str | None:
    """Extract the DSL expression from positions input for axis inference."""
    if isinstance(positions, str):
        _, expression = _split_selector(positions)
        return expression
    return None


def _expand_selector(
    selector: str,
    well_order: WellOrder,
    labware_layout_spec: LabwareLayoutSpec,
) -> list[Position]:
    """Expand a single selector string into concrete positions.

    A bare labware id with no ``@`` expression (e.g. ``"Plate1"``) is
    equivalent to ``"Plate1@all"``.

    Well IDs are emitted in the labware's canonical addressing form:
    numeric (``"1"``, ``"2"``, ...) when
    :attr:`LabwareLayoutSpec.numeric_addressing` is set, otherwise
    alphanumeric plate coordinates (``"A1"``).  Input given in the other
    form is translated automatically via the labware's ``pattern`` (see
    :func:`_parse_plate_well`).
    """
    labware, expression = _split_selector(selector)
    spec = labware_layout_spec

    cells = _select_cells(expression or "all", well_order, spec)
    return [Position(labware=labware, well=spec.emit_well(row_index, col)) for row_index, col in cells]


def _select_cells(
    expression: str,
    well_order: WellOrder,
    spec: LabwareLayoutSpec,
) -> list[tuple[int, int]]:
    """Resolve a selector expression into an ordered list of ``(row_index, col)`` cells."""
    if expression == "all":
        cells = [(row_index, col) for row_index in range(spec.rows) for col in spec.col_labels]
        # ``@all`` follows the labware's indexing pattern when the caller
        # leaves the (column-oriented) default well order in place -- but only
        # for numerically addressed labware, where the pattern defines the ID
        # numbering. Alphanumeric plates ("A1") keep the requested order: the
        # pattern doesn't change which well an ID names, and a row-wise order
        # would group wells along X, where the channels can't spread.
        order = well_order
        if well_order == WellOrder.COL_ASC and spec.pattern == "ROW_MAJOR" and spec.numeric_addressing:
            order = WellOrder.ROW_ASC
        return _order_cells(cells, order, spec)

    if expression.startswith("col:"):
        if spec.cols == 1:
            raise ValueError("column selection (col:) is not supported for single-column labware")
        selected_cols = _parse_column_selection(expression.removeprefix("col:"), spec)
        cells = [(row_index, col) for col in selected_cols for row_index in range(spec.rows)]
        return _order_cells(cells, well_order, spec)

    if expression.startswith("row:"):
        selected_rows = _parse_row_selection(expression.removeprefix("row:"), spec)
        cells = [(row_index, col) for row_index in selected_rows for col in spec.col_labels]
        return _order_cells(cells, well_order, spec)

    if expression.startswith("wells:"):
        return _parse_explicit_wells(expression.removeprefix("wells:"), well_order, spec)

    if "," in expression:
        return _parse_explicit_wells(expression, well_order, spec)

    if ":" in expression:
        return _expand_range(expression, well_order, spec)

    return [_parse_plate_well(expression, spec)]


def _order_cells(
    cells: list[tuple[int, int]],
    well_order: WellOrder,
    spec: LabwareLayoutSpec,
) -> list[tuple[int, int]]:
    """Order ``(row_index, col)`` cells according to *well_order*.

    Numeric labware orders by well number (its intrinsic pattern order);
    alphanumeric labware orders by column-then-row or row-then-column
    depending on the requested :class:`WellOrder`.
    """
    unique = _unique_preserve_order(cells)
    if well_order == WellOrder.CUSTOM:
        return unique

    reverse = well_order in {WellOrder.COL_DESC, WellOrder.ROW_DESC}
    if spec.numeric_addressing:
        return sorted(unique, key=lambda cell: spec.cell_to_number(cell[0], cell[1]), reverse=reverse)
    if well_order in {WellOrder.ROW_ASC, WellOrder.ROW_DESC}:
        return sorted(unique, key=lambda cell: (cell[0], cell[1]), reverse=reverse)
    return sorted(unique, key=lambda cell: (cell[1], cell[0]), reverse=reverse)


_SELECTOR_KEYWORD_PREFIXES = ("col:", "row:", "wells:")


def _canonical_expression(expression: str) -> str:
    """Lower-case the selector keyword (``all``, ``col:``, ``row:``, ``wells:``).

    Keywords are case-insensitive (``@All`` == ``@all``); everything after the
    keyword is left alone, since well and row labels are normalized where they
    are parsed.
    """
    lowered = expression.lower()
    if lowered == "all":
        return "all"
    for prefix in _SELECTOR_KEYWORD_PREFIXES:
        if lowered.startswith(prefix):
            return prefix + expression[len(prefix) :]
    return expression


def _split_selector(selector: str) -> tuple[str, str | None]:
    """Split ``Labware@expression`` selectors into their components."""
    labware, separator, expression = selector.partition("@")
    labware = labware.strip()
    if not labware:
        raise ValueError("position selector must include a labware ID")
    if not separator:
        return labware, None
    expression = expression.strip()
    if not expression:
        raise ValueError("position selector must include an expression after '@'")
    return labware, _canonical_expression(expression)


def _parse_column_selection(selection: str, labware_layout_spec: LabwareLayoutSpec) -> list[int]:
    cols: list[int] = []
    for part in _split_csv(selection):
        if ":" in part:
            start_str, end_str = part.split(":", 1)
            start = int(start_str)
            end = int(end_str)
            step = 1 if start <= end else -1
            cols.extend(range(start, end + step, step))
        else:
            cols.append(int(part))
    valid_cols = set(labware_layout_spec.col_labels)
    for col in cols:
        if col not in valid_cols:
            raise ValueError(f"invalid column selector: {col!r} (labware has columns 1-{labware_layout_spec.cols})")
    return _unique_preserve_order(cols)


def _parse_row_selection(selection: str, labware_layout_spec: LabwareLayoutSpec) -> list[int]:
    """Resolve a ``row:`` selection into a list of 0-based row indices."""
    rows: list[int] = []
    for part in _split_csv(selection):
        if ":" in part:
            start_str, end_str = part.split(":", 1)
            start = _parse_row_index(start_str, labware_layout_spec)
            end = _parse_row_index(end_str, labware_layout_spec)
            step = 1 if start <= end else -1
            rows.extend(range(start, end + step, step))
        else:
            rows.append(_parse_row_index(part, labware_layout_spec))
    return _unique_preserve_order(rows)


def _parse_explicit_wells(
    selection: str,
    well_order: WellOrder,
    labware_layout_spec: LabwareLayoutSpec,
) -> list[tuple[int, int]]:
    """Resolve an explicit ``wells:`` list (with optional ranges) into ordered cells."""
    cells: list[tuple[int, int]] = []
    for part in _split_csv(selection):
        if ":" in part:
            left, right = part.split(":", 1)
            cells.extend(_range_cells(left, right, labware_layout_spec))
        else:
            cells.append(_parse_plate_well(part, labware_layout_spec))
    return _order_cells(cells, well_order, labware_layout_spec)


def _expand_range(
    expression: str,
    well_order: WellOrder,
    labware_layout_spec: LabwareLayoutSpec,
) -> list[tuple[int, int]]:
    start_str, end_str = expression.split(":", 1)
    cells = _range_cells(start_str, end_str, labware_layout_spec)
    return _order_cells(cells, well_order, labware_layout_spec)


def _range_cells(start_str: str, end_str: str, spec: LabwareLayoutSpec) -> list[tuple[int, int]]:
    """Expand a ``start:end`` range into the cells it covers.

    A range whose endpoints are both numeric (e.g. ``"1:8"``) is interpreted
    as a sequential run of well *numbers*; a range with an alphanumeric
    endpoint (e.g. ``"A1:C3"``) is interpreted as a rectangular block of
    plate coordinates.
    """
    if _is_numeric_well(start_str) and _is_numeric_well(end_str):
        start = int(start_str)
        end = int(end_str)
        step = 1 if start <= end else -1
        return [_number_to_valid_cell(number, str(number), spec) for number in range(start, end + step, step)]

    row_start, col_start = _parse_plate_well(start_str, spec)
    row_end, col_end = _parse_plate_well(end_str, spec)
    return [
        (row_index, col)
        for col in range(min(col_start, col_end), max(col_start, col_end) + 1)
        for row_index in range(min(row_start, row_end), max(row_start, row_end) + 1)
    ]


def _parse_row_index(token: str, spec: LabwareLayoutSpec) -> int:
    """Resolve a row token (alphabetic ``"A"`` or numeric ``"1"``) to a 0-based row index."""
    normalized = token.strip().upper()
    if not normalized:
        raise ValueError(f"invalid row selector: {token!r}")
    if _NUMERIC_WELL_RE.fullmatch(normalized):
        index = int(normalized) - 1
    elif _ALPHA_RE.fullmatch(normalized):
        index = _alpha_label_to_index(normalized)
    else:
        raise ValueError(f"invalid row selector: {token!r}")
    if not 0 <= index < spec.rows:
        raise ValueError(f"invalid row selector: {token!r} (labware has rows 1-{spec.rows})")
    return index


def _number_to_valid_cell(number: int, token: str, spec: LabwareLayoutSpec) -> tuple[int, int]:
    """Validate a 1-based well *number* and map it to a ``(row_index, col)`` cell."""
    if number < 1 or number > spec.well_count:
        raise ValueError(f"invalid well selector: {token!r} (labware has wells 1-{spec.well_count})")
    return spec.number_to_cell(number)


def _parse_plate_well(well: str, labware_layout_spec: LabwareLayoutSpec) -> tuple[int, int]:
    """Resolve a well token to a ``(0-based row, 1-based column)`` cell.

    Accepts either addressing form regardless of the labware's canonical
    form, translating as needed:

    * Numeric tokens (``"1"``, ``"27"``) are treated as 1-based well numbers
      and mapped through the labware's ``pattern``.
    * Plate-style tokens (``"A1"``, ``"AA1"``) are parsed as Excel-style
      row/column coordinates.

    Out-of-range or unparseable tokens raise :class:`ValueError`.
    """
    normalized = _normalize_well_id(well)

    if _NUMERIC_WELL_RE.fullmatch(normalized):
        return _number_to_valid_cell(int(normalized), well, labware_layout_spec)

    match = _PLATE_WELL_RE.fullmatch(normalized)
    if not match:
        raise ValueError(f"invalid well selector: {well!r}")
    row = _alpha_label_to_index(match.group("row"))
    if not 0 <= row < labware_layout_spec.rows:
        raise ValueError(f"invalid well selector: {well!r} (labware has rows 1-{labware_layout_spec.rows})")
    col = int(match.group("col"))
    if col not in labware_layout_spec.col_labels:
        raise ValueError(
            f"invalid column in well selector: {well!r} (labware has columns 1-{labware_layout_spec.cols})"
        )
    return row, col


def _normalize_well_id(well: str) -> str:
    normalized = well.strip().upper()
    if not normalized:
        raise ValueError("well selector cannot be empty")
    return normalized


def _is_numeric_well(well: str) -> bool:
    return well.strip().isdigit()


def _split_csv(selection: str) -> list[str]:
    parts = [part.strip() for part in selection.split(",") if part.strip()]
    if not parts:
        raise ValueError("selector cannot be empty")
    return parts


def _unique_preserve_order(values: list[_T]) -> list[_T]:
    return list(dict.fromkeys(values))


__all__ = [
    "LabwareLayoutSpec",
    "Position",
    "PositionDict",
    "PositionInput",
    "SpecResolver",
    "WellSelector",
    "normalize_positions",
]

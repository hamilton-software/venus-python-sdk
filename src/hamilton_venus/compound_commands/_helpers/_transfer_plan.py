"""Shared transfer-plan helpers for compound commands.

This module hosts the CSV-driven transfer-plan primitives that are reusable
across compound commands such as ``add_reagent``, ``hit_picking``, and
``copy_plate``: the row/group dataclasses (:class:`TransferRow`,
:class:`DestGroup`, :class:`SourceGroup`, :class:`SourceWellGroup`), the
parsing/grouping helpers (:func:`_parse_transfer_csv`, :func:`_group_csv_rows`,
:func:`_group_by_source_well`, :func:`_plan_source_runs`,
:func:`_group_in_order`, :func:`_validate_required_csv_field`, :func:`_cell`),
the per-row volume validator (:func:`_validate_row_volumes_in_range`), the
plate-grouped column-major reordering helpers (:func:`_well_grid_index`,
:func:`_plate_grouped_column_major_key`,
:func:`_sort_plate_grouped_column_major`), and the up-front deck-validation
helper (:func:`validate_labware_on_deck`).
"""

from __future__ import annotations

import csv
import logging
import os
from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from hamilton_venus.exceptions import VenusCommandFailedError
from hamilton_venus.models.position import LabwareLayoutSpec, _parse_plate_well

if TYPE_CHECKING:
    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.models.command_types import LabwareDefinitionSingleReturnParameters


_logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_K = TypeVar("_K", bound=Hashable)


def _group_in_order(items: Iterable[_T], key: Callable[[_T], _K]) -> list[list[_T]]:
    """Bucket *items* by *key*, preserving first-appearance order.

    Returns a list of buckets in the order each distinct key first appears in
    *items*; within each bucket the original input order is preserved.
    Grouping is **global** -- items that share a key are merged into one
    bucket even when items with other keys appear between them
    (``A -> B -> A`` yields two buckets, with the ``A`` bucket holding both
    ``A`` items).

    Shared by :func:`_group_by_source_well` and by the resolved-transfer
    grouper in ``hit_picking`` (``_group_resolved_by_source_well``).
    """
    order: list[_K] = []
    buckets: dict[_K, list[_T]] = {}
    for item in items:
        k = key(item)
        if k not in buckets:
            buckets[k] = []
            order.append(k)
        buckets[k].append(item)
    return [buckets[k] for k in order]


@dataclass(frozen=True)
class TransferRow:
    """One row of a transfer plan.

    Produced by :func:`_parse_transfer_csv` and consumed by
    :func:`_group_csv_rows` and compound-command main loops.

    ``line_no`` is the 1-based source line number in the originating CSV
    (header is line 1; first data row is line 2). It is ``None`` for rows
    constructed in code (e.g. unit tests) and is used by callers to surface
    CSV line numbers in volume-validation errors.
    """

    source_labware: str
    source_well: str
    dest_labware: str
    dest_well: str
    volume: float
    line_no: int | None = None


@dataclass(frozen=True)
class DestGroup:
    """All rows in a transfer plan that share a (source, dest) labware pair.

    Rows are kept in original CSV order; in ``multi_dispense`` mode the row
    volumes may vary and are batched greedily by the executor.
    """

    dest_labware: str
    rows: list[TransferRow] = field(default_factory=list)


@dataclass(frozen=True)
class SourceGroup:
    """All rows in a transfer plan that share a source labware.

    Crossing a source-group boundary forces a tip change in the executor to
    avoid cross-contamination.  Within a single source group, multiple
    destination labware ids are processed back-to-back without changing tips.
    """

    source_labware: str
    dest_groups: list[DestGroup] = field(default_factory=list)


@dataclass(frozen=True)
class SourceWellGroup:
    """All transfer rows originating from one specific source well.

    Produced by :func:`_group_by_source_well` and consumed by the
    ``minimize_tips=True`` path of ``hit_picking``, where a single tip serves
    every destination fed by one ``(source_labware, source_well)`` pair.
    """

    source_labware: str
    source_well: str
    rows: list[TransferRow] = field(default_factory=list)


def _validate_required_csv_field(value: str | None, field_name: str, path: Path, line_no: int) -> str:
    """Validate a required CSV field is present and non-empty.

    Strips leading/trailing whitespace before validation, so whitespace-only
    values are treated as missing. Returns the trimmed value.

    Args:
        value: The field value from CSV parsing or defaults.
        field_name: The name of the field (for error messages).
        path: The CSV file path (for error messages).
        line_no: The CSV line number (for error messages).

    Returns:
        The validated non-empty string (with whitespace trimmed).

    Raises:
        ValueError: If the value is None or empty/whitespace-only.
    """
    trimmed = value.strip() if value is not None else ""
    if not trimmed:
        raise ValueError(f"transfer CSV '{path}' line {line_no}: missing required field '{field_name}'.")
    return trimmed


def _cell(row: dict[str, str | None], column: str) -> str | None:
    """Look up *column* case-insensitively in *row* and return the stripped value or None."""
    for key, value in row.items():
        if key is None:
            continue
        if key.strip().lower() == column:
            if value is None:
                return None
            stripped = value.strip()
            return stripped or None
    return None


def _parse_transfer_csv(
    path: str | os.PathLike[str],
    *,
    default_source_labware: str | None = None,
    default_dest_labware: str | None = None,
    default_volume: float | None = None,
    ignore_source: bool = False,
) -> list[TransferRow]:
    """Parse a transfer CSV into a list of :class:`TransferRow` records.

    Used by both ``add_reagent`` (with parameter-level fallback defaults) and
    ``hit_picking`` (no fallbacks; every row must specify all fields).

    The CSV is expected to have a header row.  Recognised columns are
    ``source_labware``, ``source_well``, ``dest_labware``, ``dest_well``,
    ``volume`` (order-independent; extra columns are ignored).  Any missing
    column or empty cell falls back to the corresponding ``default_*`` keyword
    argument.

    No defaults exist for ``source_well`` / ``dest_well`` — those must be
    supplied in the CSV for every row.

    With *ignore_source* (``add_reagent``, whose reagent always comes from its
    own ``reagent_source``) the source columns are neither read nor required;
    rows carry empty source fields, and a warning is logged if the CSV fills
    them in anyway.  A row whose ``(source_labware,
    source_well, dest_labware, dest_well, volume)`` is not fully resolvable
    after defaulting raises :class:`ValueError`.

    Note:
        Row order is preserved from the CSV.  The grouper
        (:func:`_group_csv_rows`) reorders by source plate by default;
        callers may opt to keep original CSV row order instead.
    """
    path_obj = Path(path)
    rows: list[TransferRow] = []
    ignored_source_line: int | None = None

    with path_obj.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"transfer CSV '{path_obj}' is empty (no header row).")

        for line_no, raw in enumerate(reader, start=2):  # header is line 1
            if ignore_source:
                if ignored_source_line is None and (_cell(raw, "source_labware") or _cell(raw, "source_well")):
                    ignored_source_line = line_no
                source_labware: str | None = ""
                source_well: str | None = ""
            else:
                source_labware = _cell(raw, "source_labware") or default_source_labware
                source_well = _cell(raw, "source_well")
            dest_labware = _cell(raw, "dest_labware") or default_dest_labware
            dest_well = _cell(raw, "dest_well")
            volume_str = _cell(raw, "volume")

            if volume_str is None:
                volume: float | None = default_volume
            else:
                try:
                    volume = float(volume_str)
                except ValueError as exc:
                    raise ValueError(
                        f"transfer CSV '{path_obj}' line {line_no}: invalid volume {volume_str!r}."
                    ) from exc

            # Validate required string fields
            if not ignore_source:
                source_labware = _validate_required_csv_field(source_labware, "source_labware", path_obj, line_no)
                source_well = _validate_required_csv_field(source_well, "source_well", path_obj, line_no)
            dest_labware = _validate_required_csv_field(dest_labware, "dest_labware", path_obj, line_no)
            dest_well = _validate_required_csv_field(dest_well, "dest_well", path_obj, line_no)

            # Validate volume (special case: already converted to float)
            if volume is None:
                raise ValueError(
                    f"transfer CSV '{path_obj}' line {line_no}: missing required field 'volume'"
                    " (column absent or empty; pass default_volume= to supply a fallback)."
                )

            rows.append(
                TransferRow(
                    source_labware=source_labware or "",
                    source_well=source_well or "",
                    dest_labware=dest_labware,
                    dest_well=dest_well,
                    volume=volume,
                    line_no=line_no,
                )
            )

    if not rows:
        raise ValueError(f"transfer CSV '{path_obj}' contains no data rows.")
    if ignored_source_line is not None:
        _logger.warning(
            "transfer CSV '%s' names a source (first on line %d), which is ignored: the reagent "
            "comes from the command's reagent_source.",
            path_obj,
            ignored_source_line,
        )
    return rows


def _group_csv_rows(rows: list[TransferRow]) -> list[SourceGroup]:
    """Group transfer rows by source labware, then by destination labware.

    The grouping order is **source-first** in this implementation: rows are
    bucketed by ``source_labware`` (preserving first-appearance order) and
    within each source bucket are further grouped by ``dest_labware``
    (preserving first-appearance order).  Within a ``(source, dest)`` pair the
    original CSV row order is preserved.

    Crossing a source-group boundary requires a tip change in the executor to
    avoid cross-contamination; crossing only a dest-group boundary does not.

    """
    source_order: list[str] = []
    by_source: dict[str, dict[str, list[TransferRow]]] = {}
    dest_order_per_source: dict[str, list[str]] = {}

    for row in rows:
        if row.source_labware not in by_source:
            by_source[row.source_labware] = {}
            dest_order_per_source[row.source_labware] = []
            source_order.append(row.source_labware)
        dest_buckets = by_source[row.source_labware]
        if row.dest_labware not in dest_buckets:
            dest_buckets[row.dest_labware] = []
            dest_order_per_source[row.source_labware].append(row.dest_labware)
        dest_buckets[row.dest_labware].append(row)

    groups: list[SourceGroup] = []
    for src in source_order:
        dest_groups = [DestGroup(dest_labware=dst, rows=by_source[src][dst]) for dst in dest_order_per_source[src]]
        groups.append(SourceGroup(source_labware=src, dest_groups=dest_groups))
    return groups


def _plan_source_runs(rows: list[TransferRow]) -> list[list[TransferRow]]:
    """Split *rows* into consecutive same-source runs.

    Unlike :func:`_group_csv_rows`, this does **not** globally merge all rows
    that share a source labware.  A CSV pattern A\u2192B\u2192A produces three
    independent runs rather than two, forcing an extra tip change between the
    second A-run and the B-run.  Row order within each run is preserved
    exactly as it appears in the input list.

    Used when callers want to honour CSV row order rather than re-group by
    source labware.
    """
    if not rows:
        return []
    runs: list[list[TransferRow]] = []
    current_run: list[TransferRow] = [rows[0]]
    for row in rows[1:]:
        if row.source_labware == current_run[-1].source_labware:
            current_run.append(row)
        else:
            runs.append(current_run)
            current_run = [row]
    runs.append(current_run)
    return runs


def _group_by_source_well(rows: list[TransferRow]) -> list[SourceWellGroup]:
    """Group *rows* by their ``(source_labware, source_well)`` pair.

    Groups are returned in first-appearance order of the
    ``(source_labware, source_well)`` key, and rows within each group keep
    their original relative order.  Grouping is **global**: rows that share a
    key are merged into a single group even when other source wells appear
    between them (a source-well sequence ``W1 -> W2 -> W1`` yields two groups,
    with ``W1`` carrying both its first and third rows).  This differs from
    :func:`_plan_source_runs`, which emits a fresh run on every change.

    Used by the ``minimize_tips=True`` path of ``hit_picking``: one tip per
    unique source well serves every destination fed by that well.
    """
    buckets = _group_in_order(rows, key=lambda r: (r.source_labware, r.source_well))
    return [
        SourceWellGroup(source_labware=bucket[0].source_labware, source_well=bucket[0].source_well, rows=bucket)
        for bucket in buckets
    ]


def _validate_row_volumes_in_range(
    rows: list[TransferRow],
    *,
    max_aspiration: float,
    overhead: float = 0.0,
    capacity_label: str = "tip capacity",
    mode_suffix: str = "",
) -> None:
    """Validate every row's volume is positive and the aspiration fits.

    For each row the volume must be ``> 0`` and ``row.volume + overhead`` must
    not exceed *max_aspiration*. The first offending row raises
    :class:`ValueError` with its CSV line number (when available).

    The error wording adapts to the call site:

    * ``overhead == 0`` produces ``"Transfer volume X µL ... exceeds <label> Y µL"``
      (used by ``hit_picking`` and ``add_reagent`` multi-dispense mode).
    * ``overhead > 0`` produces ``"CSV row aspiration volume X µL ... exceeds
      <label> Y µL"`` (used by ``add_reagent`` single-dispense mode, where the per-row
      aspiration also carries ``pre_aliquot_volume + post_aliquot_volume``).

    Args:
        rows: Parsed transfer rows.
        max_aspiration: Per-row aspiration ceiling (µL).
        overhead: Extra volume aspirated per row beyond ``row.volume`` (e.g.
            ``pre_aliquot_volume + post_aliquot_volume`` in ``add_reagent``
            single-dispense mode).
        capacity_label: Phrase used in the over-capacity error (``"tip
            capacity"`` or ``"net capacity"``).
        mode_suffix: Optional trailing phrase appended to the over-capacity
            error (e.g. ``" in single-dispense mode"``).

    Raises:
        ValueError: If any row's volume is ``<= 0`` or its aspiration exceeds
            *max_aspiration*.
    """
    for row in rows:
        where = f" (CSV line {row.line_no})" if row.line_no is not None else ""
        if row.volume <= 0:
            raise ValueError(
                f"Transfer volume {row.volume} µL for dest {row.dest_labware}/{row.dest_well}{where} must be > 0."
            )
        aspiration = row.volume + overhead
        if aspiration > max_aspiration:
            if overhead > 0:
                raise ValueError(
                    f"CSV row aspiration volume {aspiration} µL for dest "
                    f"{row.dest_labware}/{row.dest_well}{where} exceeds "
                    f"{capacity_label} {max_aspiration} µL{mode_suffix}."
                )
            raise ValueError(
                f"Transfer volume {row.volume} µL for dest "
                f"{row.dest_labware}/{row.dest_well}{where} exceeds "
                f"{capacity_label} {max_aspiration} µL{mode_suffix}."
            )


def _well_grid_index(well_id: str, spec: LabwareLayoutSpec) -> tuple[int, int]:
    """Return the ``(column_index, row_index)`` of *well_id* within *spec*.

    Delegates to the SDK's canonical plate-well parser so the ordering used
    here agrees with selector expansion elsewhere.  ``column_index`` is the
    1-based column number and ``row_index`` is the 0-based row offset; only the
    relative ordering matters to callers.  Sorting wells on the returned tuple
    yields column-major order (one column top-to-bottom, then the next column).

    Works for plate-style ids (``"A1"``, ``"H12"``) and the numeric ids used by
    numeric-addressed labware (``"1"``, ``"8"``).  Invalid wells raise
    :class:`ValueError`.
    """
    row_index, column_index = _parse_plate_well(well_id, spec)
    return column_index, row_index


def _plate_grouped_column_major_key(
    row: TransferRow,
    spec_cache: Mapping[str, LabwareLayoutSpec],
    source_rank: Mapping[str, int],
    dest_rank: Mapping[str, int],
) -> tuple[int, int, int, int, int, int]:
    """Stable sort key implementing plate-grouped column-major ordering.

    The key orders rows by six tiers: source plate, source column, source row,
    dest plate, dest column, dest row.  The plate tiers use the first-appearance
    rank maps *source_rank* / *dest_rank* rather than the raw labware ids, so
    plates keep CSV first-appearance order instead of sorting lexicographically
    (``"Plate10"`` does not sort before ``"Plate2"``).

    Args:
        row: The transfer row to derive a key for.
        spec_cache: Maps every referenced labware id to its
            :class:`~hamilton_venus.models.position.LabwareLayoutSpec`.
        source_rank: Maps each source labware id to its first-appearance rank.
        dest_rank: Maps each dest labware id to its first-appearance rank.

    Returns:
        A six-tuple suitable as a ``sorted`` key.
    """
    source_column, source_row = _well_grid_index(row.source_well, spec_cache[row.source_labware])
    dest_column, dest_row = _well_grid_index(row.dest_well, spec_cache[row.dest_labware])
    return (
        source_rank[row.source_labware],
        source_column,
        source_row,
        dest_rank[row.dest_labware],
        dest_column,
        dest_row,
    )


def _sort_plate_grouped_column_major(
    rows: list[TransferRow],
    spec_cache: Mapping[str, LabwareLayoutSpec],
) -> list[TransferRow]:
    """Return *rows* stably reordered into plate-grouped column-major order.

    Builds first-appearance rank maps for the source and destination labware,
    then stably sorts *rows* with :func:`_plate_grouped_column_major_key`.
    Because the sort is stable, rows that compare equal on every tier retain
    their original relative order.  The input list is not mutated.

    Args:
        rows: The transfer rows to reorder.
        spec_cache: Maps every referenced labware id to its
            :class:`~hamilton_venus.models.position.LabwareLayoutSpec`.

    Returns:
        A new list ordered source plate -> source column -> source row -> dest
        plate -> dest column -> dest row.
    """
    source_rank = {labware: rank for rank, labware in enumerate(dict.fromkeys(row.source_labware for row in rows))}
    dest_rank = {labware: rank for rank, labware in enumerate(dict.fromkeys(row.dest_labware for row in rows))}
    return sorted(
        rows,
        key=lambda row: _plate_grouped_column_major_key(row, spec_cache, source_rank, dest_rank),
    )


def validate_labware_on_deck(
    client: InstrumentClient,
    labware_ids: Iterable[str],
    *,
    row_origin: dict[str, int] | None = None,
) -> dict[str, LabwareDefinitionSingleReturnParameters]:
    """Resolve every distinct labware id once and accumulate all errors.

    Unlike lazy per-row resolution, this helper queries every distinct labware
    id provided and gathers the full list of missing labware before raising,
    so the operator sees every bad labware in a single error message rather
    than only the first one encountered.

    Args:
        client: Connected :class:`~hamilton_venus.star_client.StarClient` used
            for deck queries.
        labware_ids: Iterable of labware ids to resolve.  Duplicates are
            de-duplicated; iteration order is preserved for the first
            occurrence of each id (so error messages list bad ids in the
            order they were first referenced).
        row_origin: Optional mapping from labware id to the 1-based CSV line
            number on which that labware was first referenced.  When provided
            and an id is missing, the error message includes the line number.

    Returns:
        Mapping from labware id to its resolved
        :class:`~hamilton_venus.models.command_types.LabwareDefinitionSingleReturnParameters`.
        Callers may reuse this as a geometry cache for subsequent
        position-resolution calls.

    Raises:
        ValueError: If any labware id is not present on the deck.  The error
            message lists every missing labware (one per line), each with its
            first-referenced CSV line number if *row_origin* was provided.
    """
    seen: set[str] = set()
    ordered_ids: list[str] = []
    for labware_id in labware_ids:
        if labware_id in seen:
            continue
        seen.add(labware_id)
        ordered_ids.append(labware_id)

    resolved: dict[str, LabwareDefinitionSingleReturnParameters] = {}
    missing: list[str] = []
    for labware_id in ordered_ids:
        try:
            resp = client.labware_get_params_from_id(labware_id)
        except VenusCommandFailedError:
            if row_origin is not None and labware_id in row_origin:
                missing.append(f"'{labware_id}' (first referenced on CSV line {row_origin[labware_id]})")
            else:
                missing.append(f"'{labware_id}'")
            continue
        resolved[labware_id] = resp.return_parameters

    if missing:
        joined = "\n  - ".join(missing)
        raise ValueError(
            "The following labware are referenced but not present on the deck:\n  - "
            f"{joined}\n"
            "Add them to the deck layout or correct the labware ids."
        )
    return resolved

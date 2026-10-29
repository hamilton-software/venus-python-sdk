"""Pure geometry helpers for serial-dilution grid resolution.

These helpers are deliberately free of any :class:`~hamilton_venus.star_client.StarClient`
dependency so they can be unit-tested in isolation.  They translate the
user-facing serial-dilution parameters (``start_column``, ``num_dilutions``,
``exclude_columns``, ``exclude_rows``, ``channels``) into the concrete grid a
run walks over: the ordered active rows partitioned into passes (§3.7) and the
column sequence (sample column plus ``num_dilutions`` dilution columns), with
excluded columns skipped without consuming a dilution step (Q-COL2).

Row indexing is **0-based** internally (channel *i* services the *i*-th active
row of a pass).  Columns are **1-based** throughout, matching the user-facing
``start_column`` convention.
"""

from __future__ import annotations

from dataclasses import dataclass

from hamilton_venus.models.position import LabwareLayoutSpec, _alpha_label_to_index


@dataclass(frozen=True)
class DilutionGrid:
    """Resolved geometry for one plate's serial dilution.

    Attributes:
        passes: Active rows partitioned into passes of ``<= len(channels)`` rows
            (§3.7).  Each entry is a list of **0-based** row indices; channel *i*
            services ``passes[p][i]``.
        column_sequence: The **1-based** columns the series spans, in order.  The
            first entry is the sample column; the remaining ``num_dilutions``
            entries are the dilution columns.  Length is ``num_dilutions + 1``.
    """

    passes: list[list[int]]
    column_sequence: list[int]

    @property
    def sample_column(self) -> int:
        """The 1-based column holding the pre-loaded sample."""
        return self.column_sequence[0]

    @property
    def dilution_columns(self) -> list[int]:
        """The 1-based dilution columns targeted by pre-charge and transfers."""
        return self.column_sequence[1:]

    @property
    def num_dilutions(self) -> int:
        """Number of dilution steps (transfers) in the series."""
        return len(self.column_sequence) - 1


def _normalize_exclude_rows(exclude_rows: list[int | str] | None, spec: LabwareLayoutSpec) -> set[int]:
    """Normalize a mixed list of 1-based ints and/or row letters to 0-based indices.

    Accepts either 1-based integer row numbers (``1`` -> first row) or alphabetic
    row labels (``"A"`` -> first row), matching the plate's own labelling.  For
    numeric-addressed labware (numeric well labels) only integer entries are valid.

    Args:
        exclude_rows: Rows to exclude, as 1-based ints and/or letters.  ``None``
            or empty yields an empty set.
        spec: The plate's layout spec, used for row-count bounds and labelling.

    Returns:
        A set of **0-based** row indices to exclude.

    Raises:
        ValueError: An entry is out of range, an unrecognised type, or a letter
            label is used for numeric-addressed labware.
    """
    result: set[int] = set()
    if not exclude_rows:
        return result

    for entry in exclude_rows:
        if isinstance(entry, bool):
            # bool is an int subclass; reject it explicitly to avoid True == 1.
            raise ValueError(f"exclude_rows entry must be an int or row letter, got {entry!r}.")
        if isinstance(entry, int):
            index = entry - 1
        elif isinstance(entry, str):
            label = entry.strip()
            if spec.numeric_addressing:
                raise ValueError(
                    f"Row letter {entry!r} is invalid for numeric-addressed labware; use a 1-based integer."
                )
            try:
                index = _alpha_label_to_index(label.upper())
            except ValueError as exc:
                raise ValueError(f"Invalid row label {entry!r} in exclude_rows.") from exc
        else:
            raise ValueError(f"exclude_rows entry must be an int or row letter, got {entry!r}.")

        if not 0 <= index < spec.rows:
            raise ValueError(f"exclude_rows entry {entry!r} is out of range for a plate with {spec.rows} rows.")
        result.add(index)

    return result


def _partition_rows_into_passes(active_rows: list[int], channels: list[int]) -> list[list[int]]:
    """Partition *active_rows* into passes of at most ``len(channels)`` rows (§3.7).

    When a plate has more active rows than there are channels, the rows are
    processed in successive passes; within a pass, channel *i* services the
    *i*-th row.

    Args:
        active_rows: Ordered 0-based row indices to process.
        channels: The channels available for one simultaneous stroke.

    Returns:
        A list of passes, each a list of ``<= len(channels)`` row indices.
    """
    width = len(channels)
    if width == 0:
        raise ValueError("channels must not be empty.")
    return [active_rows[i : i + width] for i in range(0, len(active_rows), width)]


def _resolve_column_sequence(
    start_column: int,
    num_dilutions: int,
    exclude_columns: list[int] | None,
    spec: LabwareLayoutSpec,
) -> list[int]:
    """Build the 1-based column sequence, skipping excluded columns (Q-COL2).

    Walks forward from *start_column*, skipping any column in *exclude_columns*
    (excluded columns do not consume a dilution step), collecting the sample
    column plus *num_dilutions* dilution columns.

    Raises:
        ValueError: *start_column* or an *exclude_columns* entry is out of range,
            or not enough non-excluded columns remain for *num_dilutions*.
    """
    excluded = set(exclude_columns or ())
    for col in excluded:
        if not 1 <= col <= spec.cols:
            raise ValueError(f"exclude_columns entry {col} is out of range for a plate with {spec.cols} columns.")
    if not 1 <= start_column <= spec.cols:
        raise ValueError(f"start_column {start_column} is out of range for a plate with {spec.cols} columns.")
    if start_column in excluded:
        raise ValueError(f"start_column {start_column} is listed in exclude_columns.")

    needed = num_dilutions + 1
    sequence: list[int] = []
    col = start_column
    while col <= spec.cols and len(sequence) < needed:
        if col not in excluded:
            sequence.append(col)
        col += 1

    if len(sequence) < needed:
        raise ValueError(
            f"Not enough non-excluded columns from start_column {start_column} for "
            f"{num_dilutions} dilutions ({needed} columns required, {len(sequence)} available) "
            f"on a plate with {spec.cols} columns."
        )
    return sequence


def _resolve_dilution_grid(
    spec: LabwareLayoutSpec,
    *,
    start_column: int,
    num_dilutions: int,
    exclude_columns: list[int] | None,
    exclude_rows: list[int | str] | None,
    channels: list[int],
) -> DilutionGrid:
    """Resolve the full dilution grid for a plate (pure geometry).

    Combines row exclusion/normalisation, pass partitioning (§3.7), and column
    sequence resolution (Q-COL2) into a single :class:`DilutionGrid`.

    Args:
        spec: The plate's layout spec (rows/columns).
        start_column: 1-based column holding the pre-loaded sample.
        num_dilutions: Number of dilution steps (transfers); must be ``>= 1``.
        exclude_columns: 1-based columns to skip (do not consume a step).
        exclude_rows: Rows to exclude, as 1-based ints and/or letters.
        channels: Channels available for one simultaneous stroke.

    Returns:
        The resolved :class:`DilutionGrid`.

    Raises:
        ValueError: *num_dilutions* < 1, all rows excluded, or a column/row
            range constraint is violated.
    """
    if num_dilutions < 1:
        raise ValueError(f"num_dilutions must be >= 1, got {num_dilutions}.")

    excluded_rows = _normalize_exclude_rows(exclude_rows, spec)
    active_rows = [r for r in range(spec.rows) if r not in excluded_rows]
    if not active_rows:
        raise ValueError("All plate rows are excluded; no active rows remain for dilution.")

    passes = _partition_rows_into_passes(active_rows, channels)
    column_sequence = _resolve_column_sequence(start_column, num_dilutions, exclude_columns, spec)
    return DilutionGrid(passes=passes, column_sequence=column_sequence)


def _validate_volumes(
    *,
    transfer_volume: float,
    diluent_volume: float | None = None,
    dilution_factor: float | None = None,
) -> None:
    """Validate serial-dilution volume parameters.

    *transfer_volume* must be positive.  When supplied, *diluent_volume* must be
    non-negative (zero skips the diluent phase) and *dilution_factor* must be
    ``>= 1`` (the by-factor command; a factor below 1 would concentrate rather
    than dilute).

    Raises:
        ValueError: Any constraint is violated.
    """
    if transfer_volume <= 0:
        raise ValueError(f"transfer_volume must be > 0, got {transfer_volume}.")
    if diluent_volume is not None and diluent_volume < 0:
        raise ValueError(f"diluent_volume must be >= 0, got {diluent_volume}.")
    if dilution_factor is not None and dilution_factor < 1:
        raise ValueError(f"dilution_factor must be >= 1, got {dilution_factor}.")

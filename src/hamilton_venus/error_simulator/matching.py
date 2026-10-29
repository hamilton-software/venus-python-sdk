"""Port of the ``ErrorSimulator`` HSL keyword-matching submethods
(``_GetFirmwareCode`` / ``_GetErrorCode``).

Two entry points per lookup:

* :func:`match_firmware` / :func:`match_error` -- fuzzy: keyword-generate the
  description then run the same progressive ``KEYn`` / ``TAGn`` narrowing the HSL
  drove with nested ``SELECT`` statements over the module table.
* the same functions with ``exact=True`` -- when the caller passed a typed
  constant (whose value is the exact description), match on ``DESCRIPTION``
  directly, exactly as the HSL's final ``WHERE [DESCRIPTION] = ?`` does.

For STAR error rows the returned code is ``"<MAIN>/<CODE>"``; for VANTAGE (no
``MAIN`` column) it is the bare ``CODE``.
"""

from __future__ import annotations

from hamilton_venus.error_simulator.exceptions import AmbiguousMatchError, NoMatchError
from hamilton_venus.error_simulator.keywords import generate_keywords
from hamilton_venus.error_simulator.knowledge_base import Row

_STAR = "STAR"


def _key(row: Row, n: int) -> str | None:
    return row.keys()[n - 1] if 1 <= n <= 3 else None


def _in(value: str | None, keywords: set[str]) -> bool:
    return value is not None and value in keywords


# -- firmware step -> firmware command code --------------------------------------


def match_firmware(description: str, rows: list[Row], *, exact: bool = False) -> str:
    """Return the firmware command code (e.g. ``"C0AS"``) for *description*."""
    if exact:
        hits = [r for r in rows if r.description == description]
        return _single(description, hits, "firmware step").code

    keywords = set(generate_keywords(description))

    k1 = [r for r in rows if _in(r.key1, keywords)]
    if len(k1) == 1:
        return k1[0].code
    if len(k1) > 1:
        k12 = [r for r in k1 if _in(r.key2, keywords)]
        if len(k12) == 1:
            return k12[0].code
        if not k12:
            k1_only = [r for r in k1 if r.key2 is None]
            return _single(description, k1_only, "firmware step").code
        return _single(description, k12, "firmware step").code

    # zero KEY1 hits -> the HSL shows a picker; we surface the options instead.
    raise NoMatchError(
        f"firmware step {description!r} matched no rows",
        candidates=[r.description for r in rows],
    )


# -- error description -> error code -----------------------------------------------


def match_error(
    description: str,
    rows: list[Row],
    *,
    instrument: str,
    exact: bool = False,
) -> str:
    """Return the error code for *description* (``"<MAIN>/<CODE>"`` for STAR)."""
    if exact:
        hits = [r for r in rows if r.description == description]
        row = _single(description, hits, "error")
        return _with_main(row, instrument, rows)

    keywords = set(generate_keywords(description))
    matched_row = _cascade(keywords, rows)
    if matched_row is None:
        raise NoMatchError(
            f"error {description!r} matched no rows",
            candidates=[r.description for r in rows],
        )
    return _with_main(matched_row, instrument, rows)


def _cascade(keywords: set[str], rows: list[Row]) -> Row | None:
    """Faithful port of ``_GetErrorCode``'s nested KEYn/TAGn narrowing.

    Returns the single surviving row, or ``None`` when the cascade ends with
    zero rows. Raises :class:`AmbiguousMatchError` when it ends with more than
    one.
    """
    current: list[Row] = []
    for start_col in (1, 2, 3):
        base = [r for r in rows if _in(_key(r, start_col), keywords)]
        start = base
        current = base
        loops = 4 - start_col
        matched: Row | None = None

        for step in range(1, loops + 1):
            previous = current
            for tag in (1, 2, 3, 4):
                if tag == 2:
                    current = [r for r in current if _in(r.tag1, keywords)]
                elif tag == 3:
                    current = [r for r in current if _in(r.tag2, keywords)]
                elif tag == 4:
                    current = [r for r in previous if _in(r.tag2, keywords)]
                if len(current) == 1:
                    matched = current[0]
                    break
            if matched is not None:
                break

            current = previous
            col = start_col + step
            if len(current) > 1:
                current = [r for r in current if _in(_key(r, col), keywords)]
            else:
                current = [r for r in start if _in(_key(r, col), keywords)]

        if matched is not None:
            return matched
        if len(current) == 1:
            return current[0]

    if len(current) > 1:
        raise AmbiguousMatchError(
            f"error description matched {len(current)} rows",
            candidates=[r.description for r in current],
        )
    return None


def _with_main(row: Row, instrument: str, rows: list[Row]) -> str:
    if instrument == _STAR:
        main = row.main
        if main is None:
            # match by code, mirroring the HSL's follow-up MAIN lookup
            matching_row = next((r for r in rows if r.code == row.code and r.main), None)
            main = matching_row.main if matching_row is not None else None
        if main:
            return f"{main}/{row.code}"
    return row.code


def _single(description: str, hits: list[Row], kind: str) -> Row:
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise NoMatchError(f"{kind} {description!r} matched no rows")
    raise AmbiguousMatchError(
        f"{kind} {description!r} matched {len(hits)} rows",
        candidates=[r.description for r in hits],
    )

"""Convert a custom ``ErrorSimulator.mdb`` into the data + typed constants that
``hamilton_venus.error_simulator`` ships.

``ErrorSimulator`` is a **custom** VENUS HSL library (not part of a VENUS install);
its Access database is the knowledge base of firmware commands, error codes, and
the keywords used to fuzzy-match a plain-language description to a code. This
one-off script reads that ``.mdb`` (via ADODB / the ACE OLE DB provider) and
writes, into ``src/hamilton_venus/error_simulator/``:

* ``data/error_simulator.json`` -- every ``MODULE`` / ``<INSTR>-<MODULE>`` row,
  loaded into memory at runtime; the keyword cascade is just list filtering.
* ``_generated_steps.py`` / ``_generated_errors.py`` -- ``StrEnum`` constants so
  callers pick a firmware step / error from autocomplete instead of typing a
  phrase. Enum ``value`` is the exact ``DESCRIPTION`` text, so the enum path is an
  exact DB lookup while a raw ``str`` still runs the fuzzy keyword matcher.

Run it by hand after editing the ``.mdb`` and commit the result::

    python -m hamilton_venus.tools.generate_error_simulator_data \\
        --mdb "C:/Program Files (x86)/Hamilton/Library/ErrorSimulator/ErrorSimulator.mdb"
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import keyword
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

#: ``TABLE`` suffixes in ``MODULE`` -> the ``Module`` enum member name used by the
#: hand-written ``error_simulator.constants`` module. Keep in sync with it.
_MODULE_MEMBERS = {
    "1mL": "CHANNELS_1ML",
    "5mL": "CHANNELS_5ML",
    "X1": "X1",
    "MPH96": "MPH96",
    "MPH384": "MPH384",
    "IPG": "IPG_ISWAP",
    "IDL": "AUTOLOAD_IDL",
    "MagPip": "MAGPIP",
}


def _default_mdb() -> Path:
    return Path(r"C:\Program Files (x86)\Hamilton\Library\ErrorSimulator\ErrorSimulator.mdb")


def _package_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "error_simulator"


# -- Access reading -------------------------------------------------------------


def _connect(mdb: Path) -> Any:
    import win32com.client

    conn = win32com.client.Dispatch("ADODB.Connection")
    conn.Open(f"Provider=Microsoft.ACE.OLEDB.12.0;Data Source={mdb};")
    return conn


def _rows(conn: Any, sql: str) -> Iterator[dict[str, Any]]:
    rs = conn.Execute(sql)[0]
    names = [rs.Fields.Item(i).Name for i in range(rs.Fields.Count)]
    while not rs.EOF:
        yield {name: rs.Fields.Item(i).Value for i, name in enumerate(names)}
        rs.MoveNext()
    rs.Close()


def _table_names(conn: Any) -> list[str]:
    rs = conn.OpenSchema(20)  # adSchemaTables
    out: list[str] = []
    while not rs.EOF:
        name = rs.Fields.Item("TABLE_NAME").Value
        if not name.startswith(("MSys", "~")):
            out.append(name)
        rs.MoveNext()
    rs.Close()
    return sorted(out)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# -- JSON payload -------------------------------------------------------------


def _build_payload(conn: Any, mdb: Path) -> dict[str, Any]:
    module_tables = set(_MODULE_MEMBERS)
    payload: dict[str, Any] = {
        "source": {
            "mdb": str(mdb),
            "generated": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        },
        "modules": [],
        "tables": {},
    }

    for row in _rows(conn, "SELECT * FROM [MODULE]"):
        payload["modules"].append(
            {
                "table": _clean(row["TABLE"]),
                "description": _clean(row["DESCRIPTION"]),
                "key1": _clean(row["KEY1"]),
                "key2": _clean(row["KEY2"]),
                "prefix": {"STAR": _clean(row["STAR"]), "VANTAGE": _clean(row["VANTAGE"])},
            }
        )

    for table in _table_names(conn):
        if "-" not in table:
            continue
        _instrument, _, suffix = table.partition("-")
        # MDB suffixes are upper-cased (STAR-1ML); MODULE.TABLE is mixed-case (1mL).
        canonical = next((s for s in module_tables if s.upper() == suffix.upper()), suffix)
        fw: list[dict[str, Any]] = []
        error: list[dict[str, Any]] = []
        for row in _rows(conn, f"SELECT * FROM [{table}]"):
            entry = {
                "code": _clean(row.get("CODE")),
                "key1": _clean(row.get("KEY1")),
                "key2": _clean(row.get("KEY2")),
                "key3": _clean(row.get("KEY3")),
                "tag1": _clean(row.get("TAG1")),
                "tag2": _clean(row.get("TAG2")),
                "description": _clean(row.get("DESCRIPTION")),
            }
            row_type = (_clean(row.get("TYPE")) or "").upper()
            if row_type == "FW":
                fw.append(entry)
            elif row_type == "ERROR":
                entry["main"] = _clean(row.get("MAIN"))
                error.append(entry)
        payload["tables"][f"{_instrument}-{canonical}"] = {"fw": fw, "error": error}

    return payload


# -- constant rendering -----------------------------------------------------------


def _identifier(text: str) -> str:
    ident = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").upper()
    ident = re.sub(r"_+", "_", ident)
    if not ident:
        ident = "VALUE"
    if ident[0].isdigit():
        ident = f"N_{ident}"
    if keyword.iskeyword(ident.lower()):
        ident = f"{ident}_"
    return ident


def _dedupe(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """``(identifier, description)`` pairs with numeric suffixes on collisions."""
    seen: dict[str, int] = {}
    out: list[tuple[str, str]] = []
    for ident, value in pairs:
        if ident in seen:
            seen[ident] += 1
            out.append((f"{ident}_{seen[ident]}", value))
        else:
            seen[ident] = 1
            out.append((ident, value))
    return out


def _render_enum_module(doc: str, classes: dict[str, list[tuple[str, str]]]) -> str:
    lines = [
        '"""' + doc + '"""',
        "",
        "# GENERATED by hamilton_venus.tools.generate_error_simulator_data -- do not edit.",
        "",
        "from __future__ import annotations",
        "",
        "from enum import StrEnum",
        "",
    ]
    for class_name in sorted(classes):
        members = _dedupe(sorted(classes[class_name], key=lambda p: p[0]))
        lines.append("")
        lines.append(f"class {class_name}(StrEnum):")
        if not members:
            lines.append("    pass")
            continue
        for ident, value in members:
            lines.append(f"    {ident} = {value!r}")
    return "\n".join(lines) + "\n"


def _step_class(instrument: str) -> str:
    return f"{instrument.capitalize()}Step"


def _error_class(instrument: str, module_member: str) -> str:
    part = module_member.title().replace("_", "")
    return f"{instrument.capitalize()}{part}Error"


def _render_constants(payload: dict[str, Any]) -> tuple[str, str]:
    # Firmware steps are generic operations (Aspirate, Tip Pick Up, ...) repeated
    # across module tables, so merge per instrument and dedupe by description.
    # Errors are module-specific and numerous, so keep one enum per module.
    steps: dict[str, dict[str, str]] = {}
    errors: dict[str, list[tuple[str, str]]] = {}
    for table_key, groups in payload["tables"].items():
        instrument, _, suffix = table_key.partition("-")
        member = _MODULE_MEMBERS.get(suffix, _identifier(suffix))
        step_cls = _step_class(instrument)
        for entry in groups["fw"]:
            desc = entry["description"]
            if desc:
                steps.setdefault(step_cls, {}).setdefault(_identifier(desc), desc)
        err_cls = _error_class(instrument, member)
        for entry in groups["error"]:
            desc = entry["description"]
            if desc:
                errors.setdefault(err_cls, []).append((_identifier(desc), desc))

    rendered_steps = {class_name: sorted(members.items()) for class_name, members in steps.items()}

    steps_doc = (
        "Firmware-step constants for ``ErrorSimulator``. Each value is the exact "
        "firmware-step description; pass one to ``simulate_error`` to skip keyword "
        "matching."
    )
    errors_doc = (
        "Error-description constants for ``ErrorSimulator``, grouped by instrument "
        "and module. Each value is the exact error description text."
    )
    return _render_enum_module(steps_doc, rendered_steps), _render_enum_module(errors_doc, errors)


def generate(mdb: Path, out_dir: Path | None = None) -> dict[str, Path]:
    """Write the JSON + generated constant modules. Returns the paths written."""
    out_dir = out_dir or _package_dir()
    conn = _connect(mdb)
    try:
        payload = _build_payload(conn, mdb)
    finally:
        conn.Close()

    json_path = out_dir / "data" / "error_simulator.json"
    steps_path = out_dir / "_generated_steps.py"
    errors_path = out_dir / "_generated_errors.py"

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    steps_src, errors_src = _render_constants(payload)
    steps_path.write_text(steps_src, encoding="utf-8")
    errors_path.write_text(errors_src, encoding="utf-8")

    logger.info("wrote %s (%d tables)", json_path, len(payload["tables"]))
    return {"json": json_path, "steps": steps_path, "errors": errors_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mdb", type=Path, default=_default_mdb(), help="path to ErrorSimulator.mdb")
    parser.add_argument("--out-dir", type=Path, default=None, help="error_simulator package dir")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    written = generate(args.mdb, args.out_dir)
    for label, path in written.items():
        logger.info("%-7s %s", label, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Generates generated_instrument_commands.py: one typed, keyword-only method per
StarClient/VantageClient SDK command, mirroring the base SDK's own call syntax so a
card script can write e.g. ``instrument.add_carrier(labware_definition=..., left_track=1)``
instead of hand-building a kwargs dict for ``orchestrator_session.run()``.

Needs an environment with hamilton-venus-sdk and hamilton-venus-mcp installed -- this
reads hamilton_venus_mcp.catalog.CATALOG_BY_INSTRUMENT directly, which is pure reflection
over the SDK classes (no live spoke or VENUS runtime required). Its OUTPUT has no such
requirement: generated_instrument_commands.py is stdlib-only and never imports
hamilton_venus/hamilton_venus_mcp, so it's safe to run on a thin orchestrator PC that has
neither package installed, exactly like orchestrator_session.py.

Usage (from an environment with both packages installed):
    python generate_instrument_commands.py            # write/overwrite the output file
    python generate_instrument_commands.py --check     # verify it's already up to date; exits nonzero if not

Re-run this after StarClient/VantageClient's mixins change (a new SDK release, a new
command, a changed signature) and commit the resulting diff.
"""

from __future__ import annotations

import argparse
import inspect
import types
import typing
from enum import Enum
from pathlib import Path
from typing import Any

from hamilton_venus.models import InstrumentType
from hamilton_venus_mcp.catalog import (
    CATALOG_BY_INSTRUMENT,
    CommandSpec,
    ParamInfo,
    _annotation_name,
    _json_schema_for,
)

_OUTPUT_PATH = Path(__file__).resolve().parent / "orchestrator_client" / "generated_instrument_commands.py"

_HEADER = '''"""GENERATED FILE -- do not hand-edit.

Produced by generate_instrument_commands.py from
hamilton_venus_mcp.catalog.CATALOG_BY_INSTRUMENT. Re-run that script (needs an
environment with hamilton-venus-sdk and hamilton-venus-mcp installed) after a
StarClient/VantageClient SDK command changes, and commit the diff.

Every method here is a thin, typed wrapper that calls self.call(name, **kwargs) --
see instrument.py's Instrument class, which mixes this module's _GeneratedCommands in.
Stdlib-only: no hamilton_venus or hamilton_venus_mcp import, so this file can run on a
thin orchestrator PC that has neither package installed.
"""

from __future__ import annotations

from typing import Any, Literal
'''


def _merge_catalogs() -> dict[str, tuple[CommandSpec, set[InstrumentType]]]:
    """Union of every instrument's catalog, keyed by command name. Shared commands have
    identical CommandSpecs across instruments (verified against the real catalog), so
    only the *set* of instrument types a name appears under needs tracking here."""
    merged: dict[str, tuple[CommandSpec, set[InstrumentType]]] = {}
    for instrument_type, catalog in CATALOG_BY_INSTRUMENT.items():
        for name, spec in catalog.items():
            _, present = merged.get(name, (spec, set()))
            merged[name] = (spec, present | {instrument_type})
    return merged


def _render_annotation(annotation: Any) -> str | None:
    """A type hint usable in generated source with no hamilton_venus import, or None if
    *annotation* can't be safely rendered that way (an SDK model class, an already-
    unresolved forward-reference string from the catalog itself, a non-enum opaque type,
    ...) -- callers fall back to "Any" and note the real type in the docstring instead."""
    if isinstance(annotation, str):
        return None  # unresolved forward reference, already a string in the catalog itself
    if annotation is inspect.Signature.empty or annotation is Any:
        return "Any"
    if annotation is type(None):
        return "None"
    if annotation in (str, int, float, bool):
        return annotation.__name__
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        values = _json_schema_for(annotation).get("enum")
        return f"Literal[{', '.join(repr(v) for v in values)}]" if values else None

    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        parts = []
        for arg in typing.get_args(annotation):
            rendered = _render_annotation(arg)
            if rendered is None:
                return None  # one unrenderable member collapses the whole union to Any
            parts.append(rendered)
        return " | ".join(parts)
    if origin in (list, set, frozenset):
        args = typing.get_args(annotation)
        if not args:
            return origin.__name__
        inner = _render_annotation(args[0])
        return f"{origin.__name__}[{inner}]" if inner is not None else None
    if origin is dict:
        args = typing.get_args(annotation)
        if len(args) != 2:
            return "dict"
        key_t, val_t = _render_annotation(args[0]), _render_annotation(args[1])
        return f"dict[{key_t}, {val_t}]" if key_t is not None and val_t is not None else None
    return None


def _render_default(default: Any) -> str:
    # Enum defaults (e.g. EjectMode.WASTE) must unwrap to their wire value (mirrors
    # catalog._json_safe_default) since the Enum class itself isn't imported here --
    # repr() of that value is still a legal member of the Literal[...] rendered above.
    if isinstance(default, Enum):
        return repr(default.value)
    return repr(default)


def _real_type_note(annotation: Any) -> str:
    if isinstance(annotation, str):
        return annotation
    args = typing.get_args(annotation)
    if typing.get_origin(annotation) in (typing.Union, types.UnionType) and args:
        # "AspirateSettings | None", not just "Union".
        return " | ".join("None" if a is type(None) else _real_type_note(a) for a in args)
    return _annotation_name(annotation)


def _render_param_signature(param: ParamInfo) -> str:
    type_text = _render_annotation(param.annotation) or "Any"
    if param.required:
        return f"{param.name}: {type_text}"
    return f"{param.name}: {type_text} = {_render_default(param.default)}"


def _render_docstring(lines: list[str]) -> str:
    # Backslashes doubled first, so a docstring like ``Labware\User`` can't become a string escape.
    text_lines = [ln.replace("\\", "\\\\").replace('"""', '\\"\\"\\"') for ln in lines] or [""]
    first, *rest = text_lines
    if not rest:
        return f'        """{first}"""'
    body = "\n".join(f"        {ln}" if ln else "" for ln in rest)
    return f'        """{first}\n{body}\n        """'


def _render_method(name: str, spec: CommandSpec, present: set[InstrumentType]) -> str:
    params = spec.params
    sig_parts = ["self"]
    if params:
        sig_parts.append("*")
        sig_parts.extend(_render_param_signature(p) for p in params)
    signature = f"    def {name}({', '.join(sig_parts)}) -> Any:"

    doc_lines = list((spec.doc or spec.summary or name).splitlines()) or [name]

    if present == {InstrumentType.STAR}:
        doc_lines += ["", "STAR only -- not available on Vantage."]
    elif present == {InstrumentType.Vantage}:
        doc_lines += ["", "Vantage only -- not available on STAR."]

    fallback_notes = [
        f'{p.name}: real type is {_real_type_note(p.annotation)!r} -- not representable as a plain '
        f'type hint here; see describe_sdk_command("{name}") for its full schema.'
        for p in params
        if _render_annotation(p.annotation) is None
    ]
    if fallback_notes:
        doc_lines += ["", *fallback_notes]

    docstring = _render_docstring(doc_lines)
    call_kwargs = ", ".join(f"{p.name}={p.name}" for p in params)
    body = f'        return self.call("{name}"' + (f", {call_kwargs}" if call_kwargs else "") + ")"

    return "\n".join([signature, docstring, body])


def render() -> str:
    merged = _merge_catalogs()
    by_category: dict[str, list[str]] = {}
    for name, (spec, _present) in merged.items():
        by_category.setdefault(spec.category, []).append(name)

    sections = [
        _HEADER,
        "",
        "class _GeneratedCommands:",
        '    """One typed method per StarClient/VantageClient command -- see module '
        'docstring. Mixed into instrument.Instrument; every method below calls '
        'self.call(name, **kwargs)."""',
        "",
    ]
    for category in sorted(by_category):
        sections.append(f"    # ---- {category} ----")
        sections.append("")
        for name in sorted(by_category[category]):
            spec, present = merged[name]
            sections.append(_render_method(name, spec, present))
            sections.append("")

    return "\n".join(sections).rstrip() + "\n"


def _write_or_check(path: Path, content: str, check: bool) -> bool:
    normalized = content.replace("\r\n", "\n")
    current = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None
    if current == normalized:
        return False
    if check:
        raise SystemExit(f"{path} is out of date -- re-run generate_instrument_commands.py and commit the diff")
    path.write_text(normalized, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=_OUTPUT_PATH)
    parser.add_argument("--check", action="store_true", help="verify the output is up to date instead of writing it")
    args = parser.parse_args(argv)

    changed = _write_or_check(args.output, render(), args.check)
    print(f"{'wrote' if changed else 'up to date'}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

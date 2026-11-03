"""Fitting resolved variable values to what a command's parameter accepts.

A variable can be a number where the command wants text (a loop counter `{{site}}` for a site name) or the
reverse. When a field's value came from a reference, it is converted to the parameter's type before the
command is sent: a number for a text-only parameter becomes its text, a numeric text for a number-only
parameter becomes the number. Values that are not references (typed by hand) are left exactly as written,
and so is anything the parameter could already accept (a choice from a list, a union that includes the type).
"""

from __future__ import annotations

from typing import Any

from backend import variables as variables_mod


def _kinds(schema: dict[str, Any]) -> set[str]:
    """The JSON types a parameter accepts (null aside); empty for choices and referenced models."""
    if not isinstance(schema, dict) or "enum" in schema or "$ref" in schema:
        return set()
    options = [o for o in schema.get("anyOf", []) if o.get("type") != "null"]
    if options:
        if any("enum" in o or "$ref" in o for o in options):
            return set()
        return {o.get("type") for o in options if o.get("type")}
    return {schema["type"]} if schema.get("type") else set()


def fit(value: Any, schema: dict[str, Any]) -> Any:
    kinds = _kinds(schema)
    numeric = kinds & {"integer", "number"}
    if "string" in kinds and not numeric and not kinds & {"boolean"} and isinstance(value, (int, float, bool)):
        return variables_mod._text(value)  # noqa: SLF001 - 2.0 -> "2", True -> "True"
    if numeric and "string" not in kinds and isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return value
        return int(number) if number.is_integer() and "number" not in kinds or number.is_integer() and "." not in value else number
    return value


def coerce_references(original: dict[str, Any], resolved: dict[str, Any], command: dict[str, Any] | None) -> dict[str, Any]:
    """`resolved` with every value that came from a {{reference}} fitted to its parameter's type."""
    if not command:
        return resolved
    schemas = {p["name"]: p.get("schema") or {} for p in command.get("params", [])}
    out = dict(resolved)
    for name, before in original.items():
        if name in out and isinstance(before, str) and variables_mod.REF.search(before):
            out[name] = fit(out[name], schemas.get(name, {}))
    return out

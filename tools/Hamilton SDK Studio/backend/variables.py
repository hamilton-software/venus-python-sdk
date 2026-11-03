"""Flow variables: named values a card's field can reference as {{name}}.

A variable is {"name", "type", "value", "prompt"}. `type` is string | number | list | bool; `prompt`
asks for the value before every run. A field that is exactly one reference takes the variable's
typed value (so {{volume}} in a number field sends a number, {{wells}} a list); a reference inside
longer text is replaced by the value's text (so "{{plate}}@col:{{col}}" works).
"""

from __future__ import annotations

import re
from typing import Any

# {{name}}, or {{name|type}} to convert the value on its way in (see CONVERSIONS)
REF = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\|\s*([A-Za-z_][A-Za-z0-9_]*)\s*)?\}\}")
CONVERSIONS = ("str", "text", "int", "float", "bool", "list")
# labware / liquid_class / positions hold text, like string; their type only picks the helper that fills them in
TYPES = ("string", "number", "list", "bool", "labware", "liquid_class", "positions")
TEXT_TYPES = ("string", "labware", "liquid_class", "positions")


class VariableError(ValueError):
    """A variable is undefined or has a value that does not match its type."""


def find_refs(value: Any) -> set[str]:
    """Every variable name referenced anywhere inside a (possibly nested) parameter value."""
    if isinstance(value, str):
        return {name for name, _ in REF.findall(value)}
    if isinstance(value, dict):
        return set().union(*(find_refs(v) for v in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(find_refs(v) for v in value)) if value else set()
    return set()


def coerce(variable: dict[str, Any]) -> Any:
    """The typed value of one variable definition (string input is parsed per its type)."""
    kind, raw, name = variable.get("type", "string"), variable.get("value"), variable.get("name", "?")
    if kind not in TYPES:
        raise VariableError(f"Variable {name}: unknown type {kind!r}")
    try:
        if kind in TEXT_TYPES:
            return "" if raw is None else str(raw)
        if kind == "number":
            if isinstance(raw, bool):
                raise ValueError
            number = float(raw)
            return int(number) if number.is_integer() and not (isinstance(raw, str) and "." in raw) else number
        if kind == "bool":
            if isinstance(raw, str):
                if raw.strip().lower() in ("true", "yes", "1"):
                    return True
                if raw.strip().lower() in ("false", "no", "0", ""):
                    return False
                raise ValueError
            return bool(raw)
        if isinstance(raw, (list, tuple)):  # list
            return list(raw)
        items = [part.strip() for part in str(raw or "").split(",") if part.strip()]
        return [_number_or_text(item) for item in items]
    except (TypeError, ValueError) as exc:
        raise VariableError(f"Variable {name} is not a valid {kind}: {raw!r}") from exc


def _number_or_text(text: str) -> Any:
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() and "." not in text else number


def values_of(variables: list[dict[str, Any]], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """name -> typed value, with `overrides` (the per-run prompt answers) applied first."""
    values: dict[str, Any] = {}
    for variable in variables:
        name = variable.get("name")
        if not name or not REF.fullmatch("{{" + name + "}}"):
            raise VariableError(f"Invalid variable name {name!r} (letters, digits and _, not starting with a digit)")
        if name in values:
            raise VariableError(f"Variable {name} is defined twice")
        item = {**variable, "value": (overrides or {}).get(name, variable.get("value"))}
        values[name] = coerce(item)
    return values


def resolve(value: Any, values: dict[str, Any]) -> Any:
    """`value` with every {{name}} replaced. Raises VariableError for an undefined name."""
    if isinstance(value, str):
        match = REF.fullmatch(value.strip())
        if match:
            return convert(_lookup(match.group(1), values), match.group(2), match.group(1))
        return REF.sub(lambda m: _text(convert(_lookup(m.group(1), values), m.group(2), m.group(1))), value)
    if isinstance(value, dict):
        return {k: resolve(v, values) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [resolve(v, values) for v in value]
    return value


def bad_conversions(value: Any) -> set[str]:
    """Conversion names used after a | that are not one of CONVERSIONS."""
    if isinstance(value, str):
        return {kind for _, kind in REF.findall(value) if kind and kind not in CONVERSIONS}
    if isinstance(value, dict):
        return set().union(*(bad_conversions(v) for v in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(bad_conversions(v) for v in value)) if value else set()
    return set()


def convert(value: Any, kind: str | None, name: str = "?") -> Any:
    """`value` as another type: str / text, int, float, bool or list (None leaves it as it is)."""
    if kind is None:
        return value
    if kind not in CONVERSIONS:
        raise VariableError(f"Unknown conversion '{kind}' on {{{{{name}}}}} (use {', '.join(CONVERSIONS)})")
    try:
        if kind in ("str", "text"):
            return _text(value)
        if kind == "list":
            if isinstance(value, (list, tuple)):
                return list(value)
            return [_number_or_text(p.strip()) for p in value.split(",") if p.strip()] if isinstance(value, str) else [value]
        if kind == "bool":
            if isinstance(value, str):
                return coerce({"name": name, "type": "bool", "value": value})
            return bool(value)
        number = float(value)
        if kind == "float":
            return number
        if not number.is_integer():
            raise ValueError("not a whole number")
        return int(number)
    except (TypeError, ValueError) as exc:
        raise VariableError(f"Cannot convert {{{{{name}}}}} ({value!r}) with |{kind}: {exc}") from exc


def _lookup(name: str, values: dict[str, Any]) -> Any:
    if name not in values:
        raise VariableError(f"Undefined variable {{{{{name}}}}}")
    return values[name]


def _text(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(_text(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def identifier(name: str, taken: set[str]) -> str:
    """A valid, unique UPPER_SNAKE Python constant name for a variable (used by Generate Script)."""
    base = re.sub(r"\W", "_", name).upper() or "VAR"
    if base[0].isdigit():
        base = f"_{base}"
    while base in taken:
        base += "_"
    taken.add(base)
    return base

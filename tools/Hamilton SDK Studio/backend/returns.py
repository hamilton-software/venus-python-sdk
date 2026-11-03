"""What a command returns, so a card can keep part of it in a variable.

A response from the spoke is `{"result": <the SDK's return value>, ...}` with the value serialised by wire
name. Most SDK commands return a typed response whose `returnParameters` hold the interesting values
(`returnParameters.serialNumber`); a few return their own result model (`candidates`, ...); some return a
plain value (a bool, a list). `describe` reads that from the command's return annotation so the card can
offer the real field names, and `pick` takes the chosen part out of a result at run time.

A path is dotted, from the result: "" is everything, "returnParameters" the return parameters, and
"returnParameters.serialNumber" one value. List positions are numbers ("candidates.0.name").
"""

from __future__ import annotations

import typing
from enum import Enum
from typing import Any

from pydantic import BaseModel

from backend.typeinfo import candidates, title_words


def _model(annotation: Any) -> type[BaseModel] | None:
    return next((c for c in candidates(annotation) if isinstance(c, type) and issubclass(c, BaseModel)), None)


def type_name(annotation: Any) -> str:
    """A short, plain name for a type: text, integer, number, true/false, list of text, object ..."""
    found = candidates(annotation)
    if not found:
        return "any"
    names = []
    for c in found:
        origin = typing.get_origin(c) or c
        if origin in (list, tuple, set, frozenset):
            args = [a for a in typing.get_args(c) if a is not Ellipsis]
            inner = type_name(args[0]) if args else "any"
            names.append(f"list of {inner}" if inner != "any" else "list")
        elif origin is dict or (isinstance(c, type) and issubclass(c, BaseModel)):
            names.append("object")
        elif isinstance(origin, type) and issubclass(origin, bool):
            names.append("true/false")
        elif isinstance(origin, type) and issubclass(origin, int) and not issubclass(origin, Enum):
            names.append("integer")
        elif isinstance(origin, type) and issubclass(origin, float):
            names.append("number")
        elif isinstance(origin, type) and issubclass(origin, (str, Enum)):
            names.append("text")
        else:
            names.append("any")
    return " or ".join(dict.fromkeys(names))


def _fields(model: type[BaseModel]) -> list[dict[str, str]]:
    return [{"name": info.alias or name, "attr": name, "label": title_words(name), "type": type_name(info.annotation)}
            for name, info in model.model_fields.items()]


def describe(annotation: Any) -> dict[str, Any] | None:
    """{"base": path of the main value, "python": how a script reaches it from `response`, "fields": [...]}
    or None when the command returns nothing worth keeping."""
    if annotation is None or annotation is type(None) or not candidates(annotation):
        return None
    model = _model(annotation)
    if model is None:  # a plain value: a bool, a list, a dict
        return {"base": "", "python": "response", "type": type_name(annotation), "fields": []}
    params = model.model_fields.get("return_parameters")
    if params is not None:
        inner = _model(params.annotation)
        return {"base": "returnParameters", "python": "response.return_parameters", "type": "object", "fields": _fields(inner) if inner else []}
    return {"base": "", "python": "response", "type": "object", "fields": _fields(model)}  # the command's own result model


def pick(result: Any, path: str) -> Any:
    """The part of `result` at `path`. Raises KeyError (naming the path) when it is not there."""
    value = result
    if not path:
        return value
    for part in path.split("."):
        try:
            if isinstance(value, list):
                value = value[int(part)]
            elif isinstance(value, dict):
                value = value[part]
            else:
                raise KeyError(part)
        except (KeyError, IndexError, ValueError):
            raise KeyError(path) from None
    return value


def _split(returns: dict[str, Any], path: str) -> tuple[str, list[str]]:
    """The known value `path` starts with (as Python), and the rest of the path below it."""
    base = returns["base"]
    known = [(f"{base}.{f['name']}" if base else f["name"], f"{returns['python']}.{f['attr']}") for f in returns["fields"]]
    for full, source in sorted(known, key=lambda k: -len(k[0])):
        if path == full or path.startswith(full + "."):
            return source, [p for p in path[len(full):].split(".") if p]
    below = path[len(base):].lstrip(".") if base and (path == base or path.startswith(base + ".")) else path
    return returns["python"], [p for p in below.split(".") if p]


def python_for(returns: dict[str, Any] | None, path: str) -> str | None:
    """Python that reads `path` from a script's `response`, or None when the field is unknown. Positions
    in a list become [n]; anything else below a value is not something a script can be sure of."""
    if returns is None:
        return None
    source, rest = _split(returns, path)
    if not all(part.isdigit() for part in rest):
        return None
    return source + "".join(f"[{part}]" for part in rest)


def path_for(returns: dict[str, Any] | None, attributes: list[str]) -> str | None:
    """The reverse of python_for: `response.return_parameters.serial_number` (attributes after `response`)
    to "returnParameters.serialNumber"; None when it is not something this command returns."""
    if returns is None:
        return None
    base = returns["base"]
    rest = list(attributes)
    if base:
        if rest[:1] != ["return_parameters"]:
            return None
        rest = rest[1:]
    if not rest:
        return base
    for field in returns["fields"]:
        if field["attr"] == rest[0] and len(rest) == 1:
            return f"{base}.{field['name']}" if base else field["name"]
    return None

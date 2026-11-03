"""Generic argument coercion and result serialization for dynamically-dispatched
StarClient SDK calls.

Rather than hand-writing per-command argument parsing (as a curated app registry's
``kwargs_builder`` would), this uses pydantic's :class:`~pydantic.TypeAdapter` to
validate/coerce each argument against the SDK method's own type hints -- so plain
JSON from an MCP tool call (dicts, strings, numbers) is turned into the Enums,
pydantic models, and typed collections the SDK methods actually expect.
"""

from __future__ import annotations

import dataclasses
import inspect
from enum import Enum
from typing import Any

from pydantic import TypeAdapter, ValidationError

from hamilton_venus_mcp.catalog import CommandSpec


class ArgumentError(ValueError):
    """Raised for unknown/missing/invalid arguments to call_sdk_command."""


# The SDK names the same thing differently across commands -- a carrier is `carrier` in 21
# commands (get_available_carrier_sites, get_labware_on_carrier, transports, ...) but
# `carrier_id` in the add_* commands -- so an agent that learned one spelling while building a
# deck keeps guessing it for the others. Within one group, a spelling the command doesn't take
# is mapped to the one it does, as long as that is unambiguous.
PARAMETER_SYNONYMS: tuple[frozenset[str], ...] = (
    frozenset({"carrier", "carrier_id"}),
    frozenset({"labware_name", "labware", "labware_id", "plate_id"}),
)


def apply_synonyms(spec: CommandSpec, raw_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Rename a synonym the command doesn't take to the group member it does take, when the
    command has exactly one parameter of that group and it wasn't passed under its own name."""
    known = {p.name for p in spec.params}
    kwargs = dict(raw_kwargs)
    for group in PARAMETER_SYNONYMS:
        targets = group & known
        passed = [k for k in kwargs if k in group and k not in known]
        if len(targets) != 1 or len(passed) != 1:
            continue
        target = next(iter(targets))
        if target not in kwargs:
            kwargs[target] = kwargs.pop(passed[0])
    return kwargs


def coerce_kwargs(spec: CommandSpec, raw_kwargs: dict[str, Any]) -> dict[str, Any]:
    known = {p.name: p for p in spec.params}
    raw_kwargs = apply_synonyms(spec, raw_kwargs)
    unknown = sorted(set(raw_kwargs) - set(known))
    if unknown:
        raise ArgumentError(
            f"{spec.name}: unknown parameter(s) {unknown}. Valid parameters: {sorted(known)}"
        )

    missing = sorted(p.name for p in spec.params if p.required and p.name not in raw_kwargs)
    if missing:
        raise ArgumentError(f"{spec.name}: missing required parameter(s) {missing}")

    kwargs: dict[str, Any] = {}
    for name, value in raw_kwargs.items():
        param = known[name]
        if param.annotation is inspect.Signature.empty:
            kwargs[name] = value
            continue
        # Prefer the adapter catalog.py already built once at import time; only construct
        # one here (matching pre-caching behavior) if that eager build failed for this param.
        adapter = param.type_adapter or TypeAdapter(param.annotation)
        try:
            kwargs[name] = adapter.validate_python(value)
        except ValidationError as exc:
            raise ArgumentError(f"{spec.name}: invalid value for {name!r}: {exc}") from exc
    return kwargs


def serialize_result(result: Any) -> Any:
    """Convert an SDK return value into plain JSON-safe data (dict/list/str/int/float/bool/None)."""
    if result is None or isinstance(result, str | int | float | bool):
        return result
    if isinstance(result, Enum):
        return result.value
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json", by_alias=True)
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        return {k: serialize_result(v) for k, v in dataclasses.asdict(result).items()}
    if isinstance(result, dict):
        return {k: serialize_result(v) for k, v in result.items()}
    if isinstance(result, list | tuple | set):
        return [serialize_result(v) for v in result]
    return str(result)

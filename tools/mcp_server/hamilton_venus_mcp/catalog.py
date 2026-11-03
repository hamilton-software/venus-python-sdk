"""Reflection-based catalog of StarClient's/VantageClient's public SDK command methods.

Rather than hand-maintaining a curated list of commands (the way each workflow app's
own ``command_registry.py`` does for its param-form UI), this module introspects
``hamilton_venus.StarClient``/``hamilton_venus.VantageClient`` directly so every mixin
method -- across status, deck, channel, labware, liquid-class, compound-command,
device, etc. -- is automatically discoverable and callable through the MCP tools in
``server.py``, with no per-method maintenance as the SDK grows.

VantageClient's method surface is almost identical to StarClient's now (both classes
compose nearly the same mixins) -- the two real differences are load_tray_lower/raise
(Vantage only, its own mixin) and a small manually-curated hardware-incompatibility list
(``_HARDWARE_INCOMPATIBLE``) for methods that live in a *shared* mixin but only make sense
on one instrument's actual hardware -- CO-RE 5mL transport (no 5mL transport tool on
Vantage) and the interior status light (no interior light on STAR). Reflection alone
can't know these hardware facts, so they're the one manually-maintained exception in an
otherwise fully reflection-driven catalog. A separate catalog is still built per
instrument type rather than one shared catalog, so an agent never "discovers" a command
that would fail the moment it's actually called. See ``CATALOG_BY_INSTRUMENT``.

Pure-Python, no-VENUS devices (HHC, ODTC, ...) are not on StarClient/VantageClient at
all -- each has its own standalone client (see ``hamilton_venus.standalone_devices``).
``_build_standalone_catalog()`` reflects over those the same way and merges the result
into every instrument's catalog, since these commands aren't instrument-specific.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from enum import Enum
import typing
from typing import Any, get_type_hints

from pydantic import TypeAdapter

from hamilton_venus import StarClient, VantageClient
from hamilton_venus.models import InstrumentType
from hamilton_venus.standalone_devices import STANDALONE_DEVICES

_logger = logging.getLogger("hamilton_venus_mcp.catalog")

# Methods on StarClient/VantageClient that are not instrument commands -- lifecycle,
# advanced fallback, or internal caching -- and are handled by dedicated MCP tools (or
# not exposed at all) instead of being routed through call_sdk_command. Also applies
# to the standalone device clients built below ("close" is a context-manager
# convenience, not a device command).
_EXCLUDED_METHODS = frozenset(
    {
        "start",
        "stop",
        "send_command",
        "set_command_timeout",
        "use_error_profile",
        "get_labware_spec",
        "register_labware_definition",
        "close",
    }
)

_CLIENT_CLASSES: dict[InstrumentType, type] = {
    InstrumentType.STAR: StarClient,
    InstrumentType.Vantage: VantageClient,
}

# TransportCommandsMixin is shared by both client classes, so its CO-RE 5mL
# grip methods are technically callable on VantageClient too -- but VantageClient's
# own docstring documents them as "not available on Vantage hardware" (no 5mL
# transport tool on Vantage). Reflection alone can't know this hardware fact, so
# it's the one manually-curated exclusion in an otherwise fully reflection-driven
# catalog -- kept here rather than in _EXCLUDED_METHODS since it's instrument-specific.
_HARDWARE_INCOMPATIBLE: dict[InstrumentType, frozenset[str]] = {
    InstrumentType.Vantage: frozenset(
        {
            "core_5ml_transport",
            "core_5ml_transport_is_holding_labware",
            "core_5ml_transport_tracking_clear",
            "core_5ml_eject_grips",
            "core_5ml_transport_return_plate",
            "core_5ml_transport_to_waste",
            "core_5ml_present_and_scan",
            "core_5ml_hold_lid",
            # Present-and-scan is STAR only for every gripper.
            "core_present_and_scan",
            "iswap_present_and_scan",
        }
    ),
    # StatusLightCommandsMixin is likewise shared by both classes, so
    # status_light_set_interior_light (a Vantage-only interior light, per its own
    # docstring) is technically callable on StarClient too -- STAR has no interior
    # light to control.
    InstrumentType.STAR: frozenset({"status_light_set_interior_light"}),
}


@dataclass(frozen=True)
class ParamInfo:
    name: str
    annotation: Any
    required: bool
    default: Any
    # Pre-built once here rather than in coerce_kwargs's hot path (TypeAdapter construction
    # has real cost, and this dataclass is built once at import time and never changes).
    # None when the annotation is empty, or when eager construction itself failed for this
    # one parameter (e.g. an unresolvable annotation) -- coerce_kwargs falls back to building
    # it lazily in that case, exactly as it always has, so a single bad parameter degrades
    # gracefully instead of blanking out the whole catalog at import time.
    type_adapter: TypeAdapter | None = None


@dataclass(frozen=True)
class CommandSpec:
    name: str
    category: str
    summary: str
    doc: str
    params: list[ParamInfo] = field(default_factory=list)
    return_annotation: Any = inspect.Signature.empty


def _summary_from_doc(doc: str | None) -> str:
    if not doc:
        return ""
    for line in doc.strip().splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _category_for(client_cls: type, name: str) -> str:
    """The nearest *client_cls* base class (by MRO) that defines *name*, used as a
    human-readable grouping -- e.g. "ChannelCommands" for aspirate/dispense.
    """
    for klass in client_cls.__mro__[1:]:
        if name in klass.__dict__:
            label = klass.__name__.lstrip("_")
            for suffix in ("CommandsMixin", "CommandMixin", "CommandsBase", "CommandBase", "Mixin", "Base"):
                if label.endswith(suffix):
                    label = label[: -len(suffix)]
                    break
            return label or klass.__name__
    return "Other"


def _is_opaque_passthrough(signature: inspect.Signature) -> bool:
    kinds = {p.kind for name, p in signature.parameters.items() if name != "self"}
    return bool(kinds) and kinds <= {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}


def _unwrap_opaque_wrapper(func: Any) -> Any | None:
    """Best-effort de-sugaring for a ``def wrapper(self, *args, **kwargs): ...`` method
    that forwards to a real implementation captured in its closure without
    ``functools.wraps`` (e.g. channel_commands.py's per-channel-type factory wrappers
    for aspirate/dispense/tip_pickup/tip_eject/...). Returns the wrapped function to
    introspect instead, or None if no single unambiguous candidate is found.
    """
    closure = func.__closure__
    if not closure:
        return None
    candidates = [cell.cell_contents for cell in closure if inspect.isfunction(cell.cell_contents)]
    return candidates[0] if len(candidates) == 1 else None


def _resolution_namespace(func: Any) -> dict[str, Any]:
    """Names to resolve a method's string annotations against: its own module's globals, over
    the SDK's public types and typing's names. With ``from __future__ import annotations`` a
    module can annotate with a type it only imports under TYPE_CHECKING, or never imports at all
    (``Any``), and still run -- but resolving that annotation here would fail, leaving the
    parameter without a usable type (e.g. add_tubes_to_carrier's positions, or every compound
    command's aspirate_settings / dispense_settings / error_profile)."""
    import hamilton_venus.error_handling as error_handling
    import hamilton_venus.error_simulator.constants as simulator_constants
    import hamilton_venus.models as models

    namespace: dict[str, Any] = dict(vars(typing))
    for module in (models, error_handling, simulator_constants):
        namespace.update({k: v for k, v in vars(module).items() if not k.startswith("_")})
    namespace.update(getattr(func, "__globals__", {}))
    return namespace


def _resolve_hints_individually(func: Any, signature: inspect.Signature) -> dict[str, Any]:
    """Per-parameter fallback for when a whole-function ``get_type_hints(func)`` call fails.

    Some SDK type aliases (e.g. ``PositionInput``, defined in ``models/position.py``)
    embed a nested forward reference (``"Position"``) that only resolves against their
    *defining* module's namespace. When such an alias is imported and used as a parameter
    annotation elsewhere (e.g. ``channel_commands.py``), resolving it via the *importing*
    module's globals raises ``NameError`` -- and since ``get_type_hints`` resolves every
    parameter of a function in one pass, that single bad parameter blanks out real types
    for every other parameter of the same method (e.g. ``tip_eject``'s ``eject_mode``
    silently degrading from the ``EjectMode`` enum to the bare unresolved string
    "EjectMode", breaking both its JSON schema and its ``TypeAdapter``-based coercion).

    Re-resolves each parameter's own annotation in isolation -- by compiling a throwaway
    single-parameter function with the identical annotation text in the same globals and
    resolving *that* -- so one unresolvable parameter only costs that parameter its type,
    not its neighbors.
    """
    globalns = _resolution_namespace(func)
    hints: dict[str, Any] = {}
    for name, param in signature.parameters.items():
        if name == "self" or not isinstance(param.annotation, str):
            continue
        probe_ns: dict[str, Any] = {}
        try:
            exec(f"def _probe({name}: {param.annotation}) -> None: ...", globalns, probe_ns)  # noqa: S102
            hints[name] = get_type_hints(probe_ns["_probe"], globalns)[name]
        except Exception:  # noqa: BLE001 - leave this one parameter unresolved; caller falls back to the raw annotation
            continue
    return hints


def _build_catalog(client_cls: type, instrument_type: InstrumentType) -> dict[str, CommandSpec]:
    hardware_incompatible = _HARDWARE_INCOMPATIBLE.get(instrument_type, frozenset())
    catalog: dict[str, CommandSpec] = {}
    for name, member in inspect.getmembers(client_cls, predicate=inspect.isfunction):
        if name.startswith("_") or name in _EXCLUDED_METHODS or name in hardware_incompatible:
            continue

        try:
            signature = inspect.signature(member)
        except (TypeError, ValueError):
            _logger.warning("Skipping %s: signature could not be resolved", name)
            continue

        doc_source = member
        if _is_opaque_passthrough(signature):
            impl = _unwrap_opaque_wrapper(member)
            if impl is not None:
                try:
                    signature = inspect.signature(impl)
                    doc_source = impl
                except (TypeError, ValueError):
                    pass

        try:
            hints = get_type_hints(doc_source, _resolution_namespace(doc_source))
        except Exception:  # noqa: BLE001 - one bad parameter shouldn't blank out its siblings
            hints = _resolve_hints_individually(doc_source, signature)

        params: list[ParamInfo] = []
        for param_name, param in signature.parameters.items():
            if param_name == "self":
                continue
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            annotation = hints.get(param_name, param.annotation)
            type_adapter = None
            if annotation is not inspect.Signature.empty:
                try:
                    type_adapter = TypeAdapter(annotation)
                except Exception:  # noqa: BLE001 - fall back to lazy construction in coerce_kwargs
                    type_adapter = None
            params.append(
                ParamInfo(
                    name=param_name,
                    annotation=annotation,
                    required=param.default is inspect.Parameter.empty,
                    default=None if param.default is inspect.Parameter.empty else param.default,
                    type_adapter=type_adapter,
                )
            )

        catalog[name] = CommandSpec(
            name=name,
            category=_category_for(client_cls, name),
            summary=_summary_from_doc(doc_source.__doc__),
            doc=inspect.getdoc(doc_source) or "",
            params=params,
            return_annotation=hints.get("return", signature.return_annotation),
        )
    return catalog


def _build_standalone_catalog() -> dict[str, CommandSpec]:
    """Commands from pure-Python, no-VENUS device clients (HHC, ODTC, ...; see
    hamilton_venus.standalone_devices) -- not instrument-specific, so merged into
    every instrument's catalog below. Hidden per-device when its vendor driver
    isn't available (mirrors the demo app's guarded registry), via the same
    reflective _build_catalog() every other command in this module goes through
    -- instrument_type is irrelevant for these classes (no hardware-incompatible
    entries reference them) so STAR is passed arbitrarily.
    """
    catalog: dict[str, CommandSpec] = {}
    for spec in STANDALONE_DEVICES:
        if not spec.available():
            continue
        catalog.update(_build_catalog(spec.client_cls, InstrumentType.STAR))
    return catalog


_STANDALONE_CATALOG = _build_standalone_catalog()

CATALOG_BY_INSTRUMENT: dict[InstrumentType, dict[str, CommandSpec]] = {
    instrument_type: {**_build_catalog(client_cls, instrument_type), **_STANDALONE_CATALOG}
    for instrument_type, client_cls in _CLIENT_CLASSES.items()
}

# Kept for any caller that hasn't been made instrument-aware yet -- always the STAR
# catalog (the superset), matching this module's pre-Vantage behavior exactly.
CATALOG: dict[str, CommandSpec] = CATALOG_BY_INSTRUMENT[InstrumentType.STAR]


def _annotation_name(annotation: Any) -> str:
    if annotation is inspect.Signature.empty:
        return "Any"
    return getattr(annotation, "__name__", None) or str(annotation)


def _json_safe_default(value: Any) -> Any:
    """Defaults come straight from the SDK's own signatures (e.g. ``EjectMode.WASTE``),
    so an Enum member -- not JSON-serializable as-is -- must be unwrapped to its wire
    value or describe_sdk_command itself fails before an agent can see the valid options.
    """
    if isinstance(value, Enum):
        return value.value
    return value


def _json_schema_for(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Signature.empty:
        return {}
    try:
        return TypeAdapter(annotation).json_schema()
    except Exception:  # noqa: BLE001 - schema is informational; never let it block discovery
        return {"type": _annotation_name(annotation)}


def describe_command(spec: CommandSpec) -> dict[str, Any]:
    """Full parameter schema + docstring for one command, returned by describe_sdk_command."""
    return {
        "name": spec.name,
        "category": spec.category,
        "doc": spec.doc,
        "return_type": _annotation_name(spec.return_annotation),
        "params": [
            {
                "name": p.name,
                "type": _annotation_name(p.annotation),
                "required": p.required,
                "default": _json_safe_default(p.default),
                "schema": _json_schema_for(p.annotation),
            }
            for p in spec.params
        ],
    }

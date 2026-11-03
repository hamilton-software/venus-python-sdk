"""The palette's command catalog: the SDK's own command list merged with JSON overlays.

The base is the MCP server's reflected catalog (hamilton_venus_mcp.catalog), so every SDK
command is available the moment it exists -- with a form generated from its signature. An
overlay only *improves* a command: a friendlier label, a palette group, help text, units, or a
widget hint (this string is a labware, that one a tip pool). Overlays are plain JSON, loaded
from the shipped command_defs/ folder and then the user's, so adding or polishing a function
is a data edit and "Reload definitions", never a JS change or a rebuild.

Overlay file::

    {"version": 1,
     "commands": {
       "tip_pickup": {
         "label": "Pick Up Tips", "group": "Tips", "subgroup": "", "description": "...", "hidden": false,
         "params": {"tip_pool": {"label": "Tip pool", "widget": "tip_pool", "help": "...",
                                 "min": 0, "max": 5, "advanced": false, "order": 1}}}}}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend import returns as returns_mod
from backend.capabilities import requires_for
from backend.typeinfo import collect_enums, enum_choices, enum_class, title_words

_logger = logging.getLogger(__name__)

GROUPS = ("Liquid Handling", "Transport", "Tips", "Deck & Labware", "Instrument", "Devices", "Flow Control", "Advanced")
FLOW_CONTROL_GROUP = "Flow Control"

# SDK command category (the class the method lives on) -> palette group, for commands no overlay places.
_GROUP_BY_SDK_CATEGORY = {
    "Channel": "Liquid Handling", "Channels5mL": "Liquid Handling", "MPH96": "Liquid Handling", "LiquidClass": "Liquid Handling",
    "TipPool": "Tips",
    "Transport": "Transport",
    "DeckLabware": "Deck & Labware", "Deck": "Deck & Labware", "Labware": "Deck & Labware", "LabwareDefinition": "Deck & Labware",
    "DeckStatus": "Deck & Labware", "TaughtLocation": "Deck & Labware", "SplitWell": "Deck & Labware", "SampleTracking": "Deck & Labware",
    "Autoload": "Instrument", "Configuration": "Instrument", "Status": "Instrument", "FrontCover": "Instrument",
    "PipettingArm": "Instrument", "Maintenance": "Instrument", "Firmware": "Instrument",
}

# A parameter name implies a picker even when the SDK types it as a plain string. Values are the
# same keys the Demo Apps' "suggest" used, so migrated overlays and these defaults agree.
_WIDGET_BY_NAME = {
    "positions": "positions",
    "tip_pool": "tip_pool", "tip_pool_name": "tip_pool",
    "carrier": "carrier", "carrier_name": "carrier", "carrier_id": "carrier",
    "plate": "plate", "plate_name": "plate", "labware": "plate", "labware_id": "plate", "labware_name": "plate",
    "track": "track", "left_track": "track",
    "liquid_class": "liquid_class", "liquid_class_name": "liquid_class",
    "labware_definition": "labware_type", "lid_definition": "labware_type",
}


# Commands Studio runs itself (through spoke tools, not call_sdk_command). They sit in the palette
# beside the SDK commands and are built with the same overlay machinery.
STUDIO_CONNECT = "studio_connect_instrument"
STUDIO_COMMANDS: list[tuple[dict[str, Any], dict[str, Any]]] = [(
    {
        "name": STUDIO_CONNECT, "category": "Studio", "doc": "Connect the instrument for the open session.", "return_type": "dict",
        "params": [{"name": "initialize", "type": "bool", "required": False, "default": True, "schema": {"type": "boolean"}}],
    },
    {
        "label": "Connect Instrument", "group": "Instrument", "subgroup": "Session",
        "description": "Connect the instrument for the open session. Place it where the flow should connect, e.g. after setting up the deck.",
        "params": {"initialize": {"label": "Initialize", "help": "Also home the arms and initialize the instrument (can take a minute on hardware)."}},
    },
)]


def _control(name: str, label: str, subgroup: str, description: str, params: list[tuple[str, str, bool, Any, dict[str, Any]]]):
    """(described, overlay) for a flow-control card. params: (name, JSON type, required, default, overlay)."""
    described = {
        "name": name, "category": "Studio", "doc": description, "return_type": "dict",
        "params": [{"name": n, "type": t, "required": req, "default": d, "schema": {"type": t}} for n, t, req, d, _ in params],
    }
    overlay = {"label": label, "group": "Flow Control", "subgroup": subgroup, "description": description,
               "params": {n: {**o, "order": i} for i, (n, _, _, _, o) in enumerate(params)}}
    return described, overlay


_EXPR = {"widget": "expr"}
CONTROL_KIND = {  # flow-control card -> "container" (holds cards) or "leaf"
    "flow_repeat": "container", "flow_for_plate": "container", "flow_for_list": "container", "flow_while": "container", "flow_if": "container",
    "flow_break": "leaf", "flow_continue": "leaf", "flow_set_variable": "leaf", "flow_prompt": "leaf", "flow_wait": "leaf",
    "flow_call": "leaf",
}
STUDIO_COMMANDS += [
    _control("flow_repeat", "Repeat", "Loops", "Run the cards inside a number of times.", [
        ("count", "integer", True, None, {"label": "Times", "help": "A number, or {{variable}}."}),
        ("variable", "string", False, "i", {"label": "Counter name", "help": "The loop counter, 1 to Times; use it as {{i}}."}),
    ]),
    _control("flow_for_plate", "For Each in Plate", "Loops", "Run the cards inside once per column, row or well of a plate.", [
        ("iterate", "string", False, "columns", {"label": "Go through", "widget": "enum", "choices": ["columns", "rows", "wells"]}),
        ("format", "string", False, "96", {"label": "Plate format", "widget": "enum", "choices": ["6", "12", "24", "48", "96", "384", "custom"], "help": "Wells in the plate."}),
        ("rows", "integer", False, None, {"label": "Rows (custom)"}),
        ("columns", "integer", False, None, {"label": "Columns (custom)"}),
        ("order", "string", False, "column-wise", {"label": "Well order", "widget": "enum", "choices": ["column-wise", "row-wise"], "help": "For wells: A1, B1, ... or A1, A2, ..."}),
        ("variable", "string", False, None, {"label": "Variable name", "help": "Default: col, row or well. Use it as {{col}}; wells also give {{col}} and {{row}}. {{index}} counts from 1."}),
    ]),
    _control("flow_for_list", "For Each in List", "Loops", "Run the cards inside once per item of a list.", [
        ("items", "string", True, None, {"label": "Items", "help": "Comma separated, e.g. 10, 20, 50, or {{variable}} holding a list."}),
        ("variable", "string", False, "item", {"label": "Variable name", "help": "Use it as {{item}}; {{index}} counts from 1."}),
    ]),
    _control("flow_while", "While", "Loops", "Repeat the cards inside while a condition is true.", [
        ("condition", "string", True, None, {"label": "Condition", **_EXPR, "help": "e.g. volume > 10 and count < 5. Variable names without braces."}),
        ("max_iterations", "integer", False, 1000, {"label": "Stop after at most", "help": "Safety limit on repeats."}),
    ]),
    _control("flow_if", "If / Else", "Logic", "Run one set of cards or another depending on a condition.", [
        ("condition", "string", True, None, {"label": "Condition", **_EXPR, "help": 'e.g. col % 2 == 0, or last["status"] == "success" for the previous command.'}),
    ]),
    _control("flow_break", "Break", "Logic", "Leave the enclosing loop.", []),
    _control("flow_continue", "Continue", "Logic", "Skip to the next repeat of the enclosing loop.", []),
    _control("flow_set_variable", "Set Variable", "Variables & timing", "Give a variable a new value, calculated from others.", [
        ("name", "string", True, None, {"label": "Variable", "help": "Letters, digits and _."}),
        ("expression", "string", True, None, {"label": "Value", **_EXPR, "help": "e.g. volume * 2, or count + 1."}),
    ]),
    _control("flow_prompt", "Ask / Pause", "Variables & timing", "Pause the run and show a message; optionally keep what the person types.", [
        ("message", "string", True, None, {"label": "Message"}),
        ("store_in", "string", False, None, {"label": "Keep the answer in", "help": "A variable name. Leave empty for a plain Continue."}),
    ]),
    _control("flow_wait", "Wait", "Variables & timing", "Wait a number of seconds.", [
        ("seconds", "number", True, None, {"label": "Seconds"}),
    ]),
    _control("flow_call", "Run Subflow", "Subflows", "Run the cards of another tab (a subflow) here, then carry on.", [
        ("subflow", "string", True, None, {"label": "Subflow", "widget": "subflow", "help": "A tab of this flow. Its cards run here, using the same variables."}),
    ]),
]


def group_for_sdk_category(category: str) -> str:
    if category.endswith("DeviceCommands"):
        return "Devices"
    return _GROUP_BY_SDK_CATEGORY.get(category, "Advanced")


# Device commands with no overlay still land in their device's subgroup, by command prefix.
_SUBGROUP_BY_PREFIX = {"odtc_": "Inheco ODTC"}


def _default_subgroup(name: str, group: str) -> str:
    if group != "Devices":
        return ""
    return next((sub for prefix, sub in _SUBGROUP_BY_PREFIX.items() if name.startswith(prefix)), "")


def _humanize(name: str) -> str:
    return title_words(name.strip())


def _norm_choices(choices: list[Any]) -> list[dict[str, Any]]:
    """Dropdown choices as {"value", "label"}: a plain value is its own label."""
    return [c if isinstance(c, dict) else {"value": c, "label": str(c)} for c in choices]


# -- schema -> widget ----------------------------------------------------------------------------


def _resolve(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref and ref.startswith("#/$defs/"):
        return {**defs.get(ref.split("/")[-1], {}), **{k: v for k, v in schema.items() if k != "$ref"}}
    return schema


def _non_null(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in schema.get("anyOf", []) if s.get("type") != "null"]


def _union_widget(options: list[dict[str, Any]], defs: dict[str, Any]) -> str:
    """number_or_list for number | [number]; scalar for number/string mixes; string for string
    unions; json when a union mixes in objects or lists of different kinds."""
    bases: set[str] = set()
    has_list = False
    for option in options:
        option = _resolve(option, defs)
        kind = "string" if "enum" in option else option.get("type")
        if kind == "array":
            has_list = True
            item = _resolve(option.get("items", {}), defs)
            kind = "string" if "enum" in item else item.get("type")
        if kind not in ("integer", "number", "string"):
            return "json"
        bases.add(kind)
    if bases <= {"integer", "number"}:
        return "number_or_list"
    if bases == {"string"}:
        return "string"
    return "json" if has_list else "scalar"


def widget_for(name: str, schema: dict[str, Any]) -> tuple[str, list[str] | None]:
    """The form widget for one parameter, and its choices when it is an enum.

    Widgets: string, int, float, bool, enum, int_list, float_list, string_list, number_or_list,
    scalar, object, json, plus the name-implied pickers (positions, tip_pool, carrier, plate, track, liquid_class).
    """
    defs = schema.get("$defs", {})
    schema = _resolve(schema, defs)
    options = _non_null(schema)
    if len(options) == 1:  # Optional[X]
        schema = _resolve(options[0], defs)
        options = []

    if "enum" in schema:
        return "enum", [str(v) for v in schema["enum"]]
    named = _WIDGET_BY_NAME.get(name) or ("liquid_class" if name.endswith("liquid_class") else None)
    takes_text = (not options and schema.get("type") in (None, "string", "array")) or any(o.get("type") == "string" for o in options)
    if named and takes_text:  # a name hint only applies where text is accepted (not to a field that takes an object)
        return named, None
    if options:  # a real union: simple scalar/list unions get a text-style widget, the rest stay JSON
        return _union_widget(options, defs), None

    kind = schema.get("type")
    if kind == "boolean":
        return "bool", None
    if kind == "integer":
        return "int", None
    if kind == "number":
        return "float", None
    if kind == "string":
        return "string", None
    if kind == "array":
        item = _resolve(schema.get("items", {}), defs).get("type")
        return {"integer": "int_list", "number": "float_list", "string": "string_list"}.get(item, "json"), None
    if kind == "object" or "properties" in schema:
        return "object", None
    return "json", None


# -- overlays ------------------------------------------------------------------------------------


def load_overlays(*directories: Path) -> dict[str, dict[str, Any]]:
    """Merge every *.json overlay in the given folders, in order; later files win per command, and
    per parameter within a command. A malformed file is skipped with a warning, never fatal."""
    merged: dict[str, dict[str, Any]] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                commands = data["commands"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                _logger.warning("Skipping command overlay %s: %s", path, exc)
                continue
            for method, entry in commands.items():
                if not isinstance(entry, dict):
                    continue
                current = merged.setdefault(method, {"params": {}})
                params = {**current["params"], **entry.get("params", {})}
                current.update({k: v for k, v in entry.items() if k != "params"})
                current["params"] = params
    return merged


# -- merge ---------------------------------------------------------------------------------------


def _build_param(described: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    name = described["name"]
    schema = described.get("schema") or {}
    widget, schema_choices = widget_for(name, schema)
    choices = overlay.get("choices") or described.get("enum_choices") or schema_choices
    param = {
        "name": name,
        "label": overlay.get("label") or _humanize(name),
        "widget": overlay.get("widget") or widget,
        "required": described["required"],
        "default": described.get("default"),
        "help": overlay.get("help", ""),
        "choices": _norm_choices(choices) if choices else None,
        "min": overlay.get("min"),
        "max": overlay.get("max"),
        "advanced": bool(overlay.get("advanced", False)),
        "profile_source": overlay.get("profile_source"),
        "schema": schema,
    }
    if "order" in overlay:
        param["order"] = overlay["order"]
    return param


def build_command(described: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    overlay = overlay or {}
    param_overlays = overlay.get("params", {})
    params = [_build_param(p, param_overlays.get(p["name"], {})) for p in described["params"]]
    if any("order" in p for p in params):  # overlay-ordered first, the rest in signature order
        params.sort(key=lambda p: p.get("order", 10_000))
    doc = described.get("doc", "")
    group = overlay.get("group") or group_for_sdk_category(described["category"])
    return {
        "name": described["name"],
        "label": overlay.get("label") or _humanize(described["name"]),
        "group": group,
        "subgroup": overlay.get("subgroup") or _default_subgroup(described["name"], group),
        "description": overlay.get("description") or (doc.strip().splitlines()[0] if doc.strip() else ""),
        "doc": doc,
        "sdk_category": described["category"],
        "requires": requires_for(described["name"], described["category"]),
        "returns": described.get("returns"),
        "return_type": described.get("return_type", ""),
        "params": params,
        "overlaid": bool(overlay),
    }


def sdk_commands(instrument_type: str) -> list[dict[str, Any]]:
    """Every SDK command for the instrument, as describe_sdk_command would return it. Read from the
    MCP server's catalog in-process, so the palette works before a spoke or session exists."""
    from hamilton_venus.models import InstrumentType
    from hamilton_venus_mcp import catalog

    specs = catalog.CATALOG_BY_INSTRUMENT[InstrumentType(instrument_type)]
    described = []
    for spec in specs.values():
        data = catalog.describe_command(spec)
        data["returns"] = returns_mod.describe(spec.return_annotation)
        for param, info in zip(data["params"], spec.params):  # named choices come from the real enum, not the schema's bare values
            enum_cls = enum_class(info.annotation)
            if enum_cls is not None:
                param["enum_choices"] = enum_choices(enum_cls)
        described.append(data)
    return described


def sdk_enums(instrument_type: str) -> dict[str, list[dict[str, Any]]]:
    """Every enum the instrument's commands use (also inside settings objects), by class name."""
    from hamilton_venus.models import InstrumentType
    from hamilton_venus_mcp import catalog

    found: dict[str, list[dict[str, Any]]] = {}
    for spec in catalog.CATALOG_BY_INSTRUMENT[InstrumentType(instrument_type)].values():
        for info in spec.params:
            collect_enums(info.annotation, found)
    return found


class CommandCatalog:
    """Merged, cached catalog per instrument type; `reload()` re-reads the overlay files."""

    def __init__(self, overlay_dirs: list[Path]):
        self._overlay_dirs = overlay_dirs
        self._overlays: dict[str, dict[str, Any]] | None = None
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._enums: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def reload(self) -> None:
        self._overlays = None
        self._cache.clear()
        self._enums.clear()

    @property
    def overlays(self) -> dict[str, dict[str, Any]]:
        if self._overlays is None:
            self._overlays = load_overlays(*self._overlay_dirs)
        return self._overlays

    def commands(self, instrument_type: str = "STAR") -> list[dict[str, Any]]:
        if instrument_type not in self._cache:
            overlays = self.overlays
            built = [
                build_command(described, overlays.get(described["name"]))
                for described in sdk_commands(instrument_type)
            ]
            built = [c for c in built if not overlays.get(c["name"], {}).get("hidden")]
            built += [{**build_command(described, overlay), "studio": True, "flow": CONTROL_KIND.get(described["name"])}
                      for described, overlay in STUDIO_COMMANDS]
            self._cache[instrument_type] = built
        return self._cache[instrument_type]

    def command(self, name: str, instrument_type: str = "STAR") -> dict[str, Any] | None:
        return next((c for c in self.commands(instrument_type) if c["name"] == name), None)

    def payload(self, instrument_type: str = "STAR") -> dict[str, Any]:
        commands = self.commands(instrument_type)
        present = {c["group"] for c in commands}
        groups = [g for g in GROUPS if g in present] + sorted(present - set(GROUPS))
        if instrument_type not in self._enums:
            self._enums[instrument_type] = sdk_enums(instrument_type)
        return {"instrument_type": instrument_type, "groups": groups, "commands": commands, "enums": self._enums[instrument_type]}

"""Generic command-catalog types shared by every workflow app.

``ParamSpec``/``RegistryEntry`` are pure data shapes -- the actual curated list of
commands (which SDK method each entry calls, what its form fields are) is inherently
app-specific and lives in each app's own registry module, not here. ``CommandRegistry``
is the generic lookup/serialization wrapper every app builds around its own list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from hamilton_venus.models import InstrumentType

_BOTH_INSTRUMENTS: frozenset[InstrumentType] = frozenset({InstrumentType.STAR, InstrumentType.Vantage})

ParamType = Literal[
    "string", "int", "float", "bool", "enum", "int_list", "float_list", "string_list", "json", "file_path",
    "tube_positions",
]


@dataclass
class ParamSpec:
    name: str
    label: str
    type: ParamType
    required: bool = False
    default: Any = None
    enum_cls: type[Enum] | None = None
    help: str = ""
    # For type="file_path": extension (without the dot, e.g. "lay") the Browse
    # dialog filters files to. Directories are always shown regardless, so the
    # user can navigate to wherever the file actually lives.
    file_filter: str = ""
    # For type="int"/"float": when both are set, the param form renders a range
    # slider instead of a bare number input (e.g. a discrete 0-5 progress level).
    min_value: float | None = None
    max_value: float | None = None
    # Live-lookup datalist to attach, independent of type/name -- e.g. one of
    # "plate", "tip_pool", "carrier", "track", or None. The set of valid values
    # is an app-level convention (see each app's extra WS lookup messages), not
    # constrained by the framework itself.
    suggest: str | None = None
    # For a settings-profile-selector param: the command_id of the app-defined
    # "Define ... Settings"-style entry whose profile_name values populate this
    # field's dropdown. Lets param-form.js resolve the right datalist generically
    # instead of special-casing the field name. App-defined semantics only --
    # the framework does not interpret this value itself.
    profile_source: str | None = None

    def enum_choices(self) -> list[dict[str, str]] | None:
        if self.enum_cls is None:
            return None
        return [
            {"value": member.name, "label": member.name.replace("_", " ").title()}
            for member in self.enum_cls
        ]

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "enum_choices": self.enum_choices(),
            "help": self.help,
            "file_filter": self.file_filter,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "suggest": self.suggest,
            "profile_source": self.profile_source,
        }


@dataclass
class RegistryEntry:
    command_id: str
    label: str
    category: str
    method_name: str | None
    is_raw: bool = False
    description: str = ""
    subgroup: str = ""
    params: list[ParamSpec] = field(default_factory=list)
    # True for a "pseudo-command" that is never sent to the instrument -- e.g. a
    # "Define ... Settings" step that only builds a named object in memory for
    # later steps to reference. App-defined semantics; the framework's execution
    # engine only knows to skip the SDK call when this is True (see
    # ExecutionEngine's app-supplied observers/kwargs_builder for what happens
    # instead).
    is_settings_profile: bool = False
    # App-defined: the command_id of the "Define ... Settings"-style entry whose
    # profile_name values this entry's own settings_profile param can select from.
    settings_profile_source: str | None = None
    # Which instrument type(s) this command is valid for. Defaults to both -- almost
    # all commands are shared (channel/5mL/deck/labware/liquid-class/transport/
    # compound/...); an app only needs to narrow this for entries backed by a method
    # that's exclusive to one client class (e.g. StarClient's CO-RE 5mL transport,
    # or VantageClient's load tray / interior status light). Used by
    # CommandRegistry.for_instrument() to build a per-instrument-type view without
    # maintaining a second, duplicate entry list.
    instruments: frozenset[InstrumentType] = field(default_factory=lambda: _BOTH_INSTRUMENTS)

    def to_json(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "label": self.label,
            "category": self.category,
            "method_name": self.method_name,
            "is_raw": self.is_raw,
            "description": self.description,
            "subgroup": self.subgroup,
            "params": [p.to_json() for p in self.params],
            "is_settings_profile": self.is_settings_profile,
            "settings_profile_source": self.settings_profile_source,
        }


class CommandRegistry:
    """Generic lookup/serialization wrapper around one app's curated entry list."""

    def __init__(self, entries: list[RegistryEntry]) -> None:
        self.entries = entries
        self._by_id: dict[str, RegistryEntry] = {entry.command_id: entry for entry in entries}

    def get_entry(self, command_id: str) -> RegistryEntry:
        try:
            return self._by_id[command_id]
        except KeyError as exc:
            raise KeyError(f"Unknown command_id: {command_id!r}") from exc

    def catalog_payload(self) -> dict[str, Any]:
        return {"commands": [entry.to_json() for entry in self.entries]}

    def for_instrument(self, instrument_type: InstrumentType) -> CommandRegistry:
        """A new CommandRegistry containing only entries valid for *instrument_type* --
        e.g. a Vantage-mode app never offers (or can look up/execute) an entry backed
        by a method the Vantage/StarClient class doesn't have (see each entry's
        ``instruments`` field for what's actually exclusive to which client).
        """
        return CommandRegistry([entry for entry in self.entries if instrument_type in entry.instruments])

"""Sample Tracking payloads for a finished run, in the Script Manager's own message shapes
(``sample_labware_info``, ``sample_event``, ``tadm_result``) so its views render them as-is.

A log written by a Script Manager run carries those messages itself (the bootstrap's
``\\x00SAMPLE\\x00``-style markers in the console capture); they are used unchanged.
Any other log is rebuilt from its aspirate and dispense commands with the same rules
``python_script_manager_app/backend/script_runner.py`` applies live:

- a dispense's source is whatever that channel last aspirated;
- a reservoir's positions are one pool (``<reservoir>@all``);
- a dispense into a reservoir is a refill and is not tracked, except the liquid waste;
- only labware that was dispensed into gets a card; aspirates from it before then are kept;
- split-well slot racks are shown as their parent well.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from hamilton_venus.models.position import LabwareLayoutSpec, normalize_positions

from hamilton_workflow_framework.run_log._common import (
    Command,
    entry_time,
    index_commands,
    iso,
    log_entries,
    marker_json,
    markers,
    payload_of,
)

_CHANNEL_ACTIONS = {
    "channels.1ml.aspirate": "aspirate",
    "channels.1ml.dispense": "dispense",
    "channels.5ml.aspirate": "aspirate",
    "channels.5ml.dispense": "dispense",
    "channels.magpip.aspirate": "aspirate",
    "channels.magpip.dispense": "dispense",
}
_ON_THE_FLY_ACTIONS = {"channels.1ml.dispenseonthefly", "channels.5ml.dispenseonthefly", "channels.magpip.dispenseonthefly"}
_MPH_ACTIONS = {"mph96.aspirate": "aspirate", "mph96.dispense": "dispense"}
_ADD_ACTIONS_WITH_NAME = ("labware.add",)
LIQUID_WASTE = "liquid_waste"


def build_sample_tracking(log: dict[str, Any]) -> dict[str, Any]:
    """``{"source", "labware", "events", "tadm"}``; ``source`` is ``"script_manager"`` when the
    log's own Sample Tracking messages were used, ``"rebuilt"`` otherwise."""
    from_markers = _from_markers(log)
    if from_markers is not None:
        return from_markers
    return _Rebuild(log).run()


# --- Script Manager messages ------------------------------------------------------------


def _from_markers(log: dict[str, Any]) -> dict[str, Any] | None:
    labware: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    tadm: list[dict[str, Any]] = []
    for entry, name, text in markers(log):
        data = marker_json(text)
        if not isinstance(data, dict):
            continue
        stamp = iso(entry_time(entry))
        if name == "SAMPLE_LABWARE_INFO" and data.get("labware"):
            labware[data["labware"]] = {**labware.get(data["labware"], {}), **data}
        elif name == "SAMPLE":
            # Events held until their labware became a target carry their own time.
            events.append({"timestamp": stamp, **data})
        elif name == "TADM":
            tadm.append({"timestamp": stamp, **data})
    if not events and not labware:
        return None
    return {"source": "script_manager", "labware": list(labware.values()), "events": events, "tadm": tadm}


# --- Rebuild from commands ------------------------------------------------------------


@lru_cache(maxsize=1)
def _catalog_index() -> dict[str, Path]:
    """Labware definition name (lower case) -> JSON file in the SDK's labware catalog."""
    roots: list[Path] = []
    try:
        from hamilton_venus._internal._sdk_paths import get_sdk_install_path

        roots.append(Path(get_sdk_install_path()) / "Labware")
    except Exception:  # noqa: BLE001 - no SDK install on this PC; layouts fall back below
        pass
    index: dict[str, Path] = {}
    for root in roots:
        if root.is_dir():
            for path in root.rglob("*.json"):
                index.setdefault(path.stem.lower(), path)
    return index


def _per_channel(value: Any, index: int) -> Any:
    if isinstance(value, list):
        return value[index] if 0 <= index < len(value) else None
    return value


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class _Rebuild:
    def __init__(self, log: dict[str, Any]) -> None:
        self.log = log
        self.commands = index_commands(log).commands
        self.display_names: dict[str, str] = {}
        self.split_parents: dict[str, tuple[str, str]] = {}
        self.reservoirs: set[str] = set()
        self.definitions: dict[str, dict[str, Any]] = {}
        self.definition_names: dict[str, str] = {}
        self.error_entries: list[tuple[Any, dict[str, Any]]] = []
        # Live state, mirroring script_runner.py's module globals.
        self.volumes: dict[str, float] = {}
        self.targets: list[str] = []
        self.channel_source: dict[Any, dict[str, Any]] = {}
        self.source_colors: dict[str, int] = {}
        self.transfer_seq = 0
        self.events: list[dict[str, Any]] = []
        self.tadm: list[dict[str, Any]] = []

    # -- what the log says about labware ----------------------------------------------

    def _scan_labware(self) -> None:
        for command in self.commands:
            action = command.action.lower()
            parameters = command.parameters
            if action.startswith(_ADD_ACTIONS_WITH_NAME):
                for key in ("labwareName", "splitLabwareName", "plateId", "labwareId"):
                    name = parameters.get(key)
                    if isinstance(name, str) and name:
                        self.display_names.setdefault(name.lower(), name)
                definition = parameters.get("labwareDefinition")
                name = parameters.get("labwareName")
                if isinstance(definition, str) and isinstance(name, str):
                    self.definition_names[name.lower()] = definition
                # Names VENUS assigned (no labwareName in the request) come back in the response.
                returned = command.return_parameters.get("labwareName")
                if isinstance(returned, str) and returned:
                    self.display_names.setdefault(returned.lower(), returned)
                    if isinstance(definition, str):
                        self.definition_names.setdefault(returned.lower(), definition)
            if action == "labware.addreservoir":
                for name in (parameters.get("labwareName"), command.return_parameters.get("labwareName")):
                    if isinstance(name, str):
                        self.reservoirs.add(name.lower())
            elif action == "labware.addsplitwellsite":
                split, parent, well = (
                    parameters.get("splitLabwareName"), parameters.get("parentLabwareName"), parameters.get("parentWell"),
                )
                if isinstance(split, str) and isinstance(parent, str) and isinstance(well, str):
                    self.split_parents[split.lower()] = (parent, well.upper())
            elif action == "labware.getlabwareparamsfromid":
                definition = command.return_parameters.get("definition")
                name = parameters.get("labwareName") or command.return_parameters.get("labwareName")
                if isinstance(definition, dict) and isinstance(name, str):
                    self.definitions[name.lower()] = definition
                    if str(definition.get("labwareClass") or "").lower() == "reservoir":
                        self.reservoirs.add(name.lower())
        for entry in log_entries(self.log):
            kind = entry.get("type")
            payload = payload_of(entry)
            if kind == "reservoir_labware" and isinstance(payload.get("labware"), str):
                self.reservoirs.add(payload["labware"].lower())
            elif kind == "instrument_error":
                self.error_entries.append((entry_time(entry), payload))

    def _name(self, labware: str) -> str:
        return self.display_names.get(labware.lower(), labware)

    def _location(self, labware: str, well: str) -> tuple[str, str]:
        """Split-well slots -> their parent well; everything else as given."""
        parent = self.split_parents.get(labware.lower())
        if parent is not None:
            return self._name(parent[0]), parent[1]
        return self._name(labware), well

    def _is_reservoir(self, labware: str) -> bool:
        return labware.lower() in self.reservoirs

    def _definition(self, labware: str) -> dict[str, Any] | None:
        key = labware.lower()
        if key in self.definitions:
            return self.definitions[key]
        name = self.definition_names.get(key)
        path = _catalog_index().get(name.lower()) if name else None
        if path is not None:
            try:
                definition = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                definition = None
            if isinstance(definition, dict):
                self.definitions[key] = definition
                return definition
        return None

    def _spec(self, labware: str) -> LabwareLayoutSpec | None:
        definition = self._definition(labware)
        if definition is not None:
            try:
                return LabwareLayoutSpec.from_definition(definition)
            except (ValueError, TypeError, KeyError):
                pass
        return None

    def _all_wells(self, labware: str) -> list[str]:
        spec = self._spec(labware)
        if spec is None:
            return []
        try:
            return [p.well for p in normalize_positions(f"{labware}@all", get_spec=lambda _name: spec)]
        except (ValueError, TypeError):
            return []

    # -- the Script Manager's ledger, offline -----------------------------------------

    def _source_key(self, labware: str | None, well: str | None) -> int | None:
        if labware is None or well is None:
            return None
        key = f"{labware}@{well}"
        if key not in self.source_colors:
            self.source_colors[key] = len(self.source_colors)
        return self.source_colors[key]

    def _source_position(self, labware: str, well: str) -> tuple[str, str]:
        return (labware, "all") if self._is_reservoir(labware) else (labware, well)

    def _errors(self, command: Command, channel: Any, operation: str) -> list[dict[str, Any]]:
        if command.requested_at is None:
            return []
        errors = []
        for moment, payload in self.error_entries:
            if moment is None or not command.active_at(moment):
                continue
            for detail in payload.get("detailed_errors") or [{}]:
                if not isinstance(detail, dict):
                    continue
                detail_channel = next(
                    (a.get("value") for a in detail.get("attributes") or [] if isinstance(a, dict) and a.get("name") == "channel"),
                    None,
                )
                if detail_channel is not None and str(detail_channel) != str(channel):
                    continue
                errors.append({
                    "time": iso(moment),
                    "during": operation,
                    "code": payload.get("code"),
                    "detail_code": detail.get("code"),
                    "title": payload.get("title"),
                    "message": detail.get("message") or payload.get("message"),
                    "channel": detail_channel,
                })
        return errors

    def _record(
        self,
        command: Command,
        labware: str,
        well: str,
        *,
        operation: str,
        channel: Any,
        volume: float,
        details: dict[str, Any] | None = None,
        source: dict[str, Any] | None = None,
    ) -> int | None:
        if operation == "dispense" and labware.lower() != LIQUID_WASTE and self._is_reservoir(labware):
            return None  # a refill, not a sample delivery
        key = f"{labware}@{well}"
        current = self.volumes.get(key, 0.0)
        if operation == "dispense":
            current += volume
            if labware not in self.targets:
                self.targets.append(labware)
        else:
            current = max(0.0, current - volume)
        self.volumes[key] = current
        self.transfer_seq += 1
        source = source or {}
        event = {
            "timestamp": iso(command.responded_at or command.requested_at),
            "labware": labware,
            "well": well,
            "operation": operation,
            "channel": channel,
            "volume": volume,
            "current_volume_ul": current,
            "success": bool(command.success),
            "error": None if command.success else (command.message or "command failed or did not finish"),
            "source_labware": source.get("labware"),
            "source_well": source.get("well"),
            "source_key": self._source_key(source.get("labware"), source.get("well")),
            "transfer_id": self.transfer_seq,
            "source_transfer_id": source.get("transfer_id"),
            "source_barcode": None,
            "source_barcode_type": None,
            "liquid_class": None,
            "lld": False,
            "liquid_level_mm": None,
            "liquid_volume_ul": None,
            "errors": self._errors(command, channel, operation),
        }
        event.update(details or {})
        self.events.append(event)
        return self.transfer_seq

    def _record_tadm(self, command: Command, transfer_ids: dict[Any, int]) -> None:
        tadm = command.return_parameters.get("TADM")
        curves = tadm.get("tadmCurves") if isinstance(tadm, dict) else None
        for curve in curves or []:
            if not isinstance(curve, dict):
                continue
            transfer_id = transfer_ids.get(curve.get("channelNumber"))
            if transfer_id is None:
                continue
            self.tadm.append({
                "timestamp": iso(command.responded_at),
                "transfer_id": transfer_id,
                "channel": curve.get("channelNumber"),
                "step_type_name": curve.get("stepTypeName") or "",
                "liquid_class_name": curve.get("liquidClassName") or "",
                "volume": curve.get("volume"),
                "curve_flagged": bool(curve.get("curveFlagged")),
                "error_code": str(curve.get("error")) if curve.get("error") else None,
                "curve_points": [
                    {"time_ms": p.get("timeMs"), "pressure": p.get("pressure")}
                    for p in curve.get("curvePoints") or []
                    if isinstance(p, dict)
                ],
            })

    def _channel_transfer(self, command: Command, operation: str) -> None:
        parameters = command.parameters
        channels = parameters.get("channels") if isinstance(parameters.get("channels"), list) else []
        positions = parameters.get("positions") if isinstance(parameters.get("positions"), list) else []
        reported = {
            c.get("channel"): c for c in command.return_parameters.get("channels") or [] if isinstance(c, dict)
        }
        transfer_ids: dict[Any, int] = {}
        for index, channel in enumerate(channels):
            position = positions[index] if index < len(positions) else None
            if not isinstance(position, dict):
                continue
            labware, well = self._location(str(position.get("labwareId") or ""), str(position.get("wellId") or ""))
            if not labware:
                continue
            data = reported.get(channel, {})
            actual = data.get("aspiratedVolume" if operation == "aspirate" else "dispensedVolume")
            volume = _to_float(actual if actual is not None else _per_channel(parameters.get("volumes"), index))
            liquid_class = _per_channel(parameters.get("liquidClass"), index)
            if operation == "aspirate":
                lld = _to_float(_per_channel(parameters.get("capacitiveLLD"), index)) > 0
                details = {
                    "liquid_class": str(liquid_class) if liquid_class else None,
                    "lld": lld,
                    "liquid_level_mm": data.get("liquidLevel_mm") if lld else None,
                    "liquid_volume_ul": data.get("liquidVolume_uL") if lld else None,
                }
                transfer_id = self._record(command, labware, well, operation="aspirate", channel=channel, volume=volume, details=details)
                if command.success and transfer_id is not None:
                    src_labware, src_well = self._source_position(labware, well)
                    self.channel_source[channel] = {
                        "labware": src_labware, "well": src_well, "transfer_id": transfer_id, "details": details,
                    }
            else:
                source = self.channel_source.get(channel)
                details = dict((source or {}).get("details") or {})
                transfer_id = self._record(
                    command, labware, well, operation="dispense", channel=channel, volume=volume, details=details, source=source,
                )
            if transfer_id is not None:
                transfer_ids[channel] = transfer_id
        self._record_tadm(command, transfer_ids)

    def _on_the_fly(self, command: Command) -> None:
        parameters = command.parameters
        labware = parameters.get("labwareName")
        if not isinstance(labware, str):
            return
        channels = sorted(c for c in parameters.get("channels") or [] if isinstance(c, int))
        volumes = parameters.get("volumes")
        volume = _to_float(volumes[0] if isinstance(volumes, list) and volumes else volumes)
        excluded = set(parameters.get("excludedPositions") or [])
        label = ",".join(str(c) for c in channels) or "?"
        source = self.channel_source.get(channels[0]) if channels else None
        for well in self._all_wells(labware):
            if well not in excluded:
                self._record(command, self._name(labware), well, operation="dispense", channel=label, volume=volume, source=source)

    def _mph(self, command: Command, operation: str) -> None:
        parameters = command.parameters
        labware = parameters.get("labwareName") or parameters.get("labwareId")
        if not isinstance(labware, str):
            return
        selection = parameters.get("mphSelection")
        wells = (
            list(selection) if isinstance(selection, list) and selection and all(isinstance(w, str) for w in selection)
            else self._all_wells(labware)
        )
        volume = _to_float(parameters.get("volume"))
        source = self.channel_source.get("MPH") if operation == "dispense" else None
        for well in wells:
            self._record(command, self._name(labware), well, operation=operation, channel="MPH", volume=volume, source=source)
        if operation == "aspirate" and command.success and wells:
            self.channel_source["MPH"] = {"labware": self._name(labware), "well": "*"}

    # -- assembly -------------------------------------------------------------------

    def _labware_info(self, labware: str) -> dict[str, Any]:
        spec = self._spec(labware)
        definition = self._definition(labware) or {}
        info = {
            "labware": labware,
            "labware_class": str(definition.get("labwareClass") or "unknown").lower(),
            "rows": 8,
            "cols": 12,
            "numeric_addressing": False,
            "pattern": "COLUMN_MAJOR",
            "barcode": None,
        }
        if spec is not None:
            info.update(rows=spec.rows, cols=spec.cols, numeric_addressing=bool(spec.numeric_addressing), pattern=spec.pattern)
        else:
            wells = [e["well"] for e in self.events if e["labware"] == labware]
            info.update(_grid_from_wells(wells))
        return info

    def run(self) -> dict[str, Any]:
        self._scan_labware()
        for command in self.commands:
            action = command.action.lower()
            if action in _CHANNEL_ACTIONS:
                self._channel_transfer(command, _CHANNEL_ACTIONS[action])
            elif action in _ON_THE_FLY_ACTIONS:
                self._on_the_fly(command)
            elif action in _MPH_ACTIONS:
                self._mph(command, _MPH_ACTIONS[action])
        targets = set(self.targets)
        events = [e for e in self.events if e["labware"] in targets]
        return {
            "source": "rebuilt",
            "labware": [self._labware_info(labware) for labware in self.targets],
            "events": events,
            "tadm": [t for t in self.tadm if any(e["transfer_id"] == t["transfer_id"] for e in events)],
        }


def _grid_from_wells(wells: list[str]) -> dict[str, Any]:
    """Best-effort grid when no definition is available: from the well names seen."""
    rows, cols, numeric = 1, 1, True
    for well in wells:
        match = re.fullmatch(r"([A-Za-z]+)(\d+)", well)
        if match:
            numeric = False
            letters = match.group(1).upper()
            row = 0
            for char in letters:
                row = row * 26 + (ord(char) - 64)
            rows, cols = max(rows, row), max(cols, int(match.group(2)))
        elif well.isdigit():
            cols = max(cols, int(well))
    return {"rows": rows, "cols": cols, "numeric_addressing": numeric, "pattern": "COLUMN_MAJOR"}

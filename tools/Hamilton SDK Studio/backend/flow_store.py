"""Saved flows: `<name>.studio.json` files in the app's data folder.

A flow file holds everything needed to reopen a flow: its cards, variables and the instrument it
was built for. The same format is used for the Export / Import file buttons, so a flow can be moved
between PCs.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from backend import flow as flow_mod

FORMAT = "sdk-studio-flow"
VERSION = 1
SUFFIX = ".studio.json"
_BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class FlowError(ValueError):
    """The flow file or name is not usable; the message is safe to show."""


def safe_name(name: str) -> str:
    cleaned = _BAD_NAME_CHARS.sub("_", (name or "").strip()).strip(" .")
    if not cleaned:
        raise FlowError("Give the flow a name first.")
    return cleaned[:80]


_LANES = ("children", "else_children")
_MAX_DEPTH = 20


def _clean_steps(steps: Any, prefix: str, depth: int = 0) -> list[dict[str, Any]]:
    """Validated cards, keeping the nesting of control cards (their `children` / `else_children`)."""
    if not isinstance(steps, list):
        raise FlowError("The flow's cards are malformed.")
    if depth > _MAX_DEPTH:
        raise FlowError("The cards are nested too deeply.")
    clean: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        where = f"{prefix}{index}"
        if not isinstance(step, dict) or not isinstance(step.get("command"), str):
            raise FlowError(f"Card {where} has no command.")
        card = {
            "id": str(step.get("id") or f"s{where.replace('.', '_')}"),
            "kind": step.get("kind", "command"),
            "command": step["command"],
            "params": step.get("params") if isinstance(step.get("params"), dict) else {},
            "enabled": bool(step.get("enabled", True)),
        }
        saves = flow_mod.saves_of(step)
        if saves:
            card["saves"] = saves  # keep parts of the result in variables
        for lane in _LANES:
            if lane in step:
                card[lane] = _clean_steps(step[lane], f"{where}.", depth + 1)
        clean.append(card)
    return clean


def _clean_subflows(raw: Any) -> list[dict[str, Any]]:
    """The tabs after Main: [{id, name, steps}] with unique, non-empty names."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise FlowError("The flow's subflows are malformed.")
    clean, seen = [], set()
    for index, sub in enumerate(raw, start=1):
        if not isinstance(sub, dict):
            raise FlowError("A subflow is malformed.")
        name = str(sub.get("name") or "").strip()
        if not name or name.lower() in seen:
            raise FlowError(f"Subflow {index} needs a name that no other subflow uses.")
        seen.add(name.lower())
        clean.append({"id": str(sub.get("id") or f"sub{index}"), "name": name, "steps": _clean_steps(sub.get("steps", []), f"{name}: ")})
    return clean


def count_cards(steps: list[dict[str, Any]]) -> int:
    return sum(1 + sum(count_cards(step.get(lane, [])) for lane in _LANES) for step in steps)


def normalize(data: Any, name: str | None = None, instrument: str | None = None) -> dict[str, Any]:
    """A validated flow dict in file format. Raises FlowError for anything that is not a flow."""
    if not isinstance(data, dict):
        raise FlowError("This is not an SDK Studio flow file.")
    if data.get("format") not in (None, FORMAT):
        raise FlowError("This is not an SDK Studio flow file.")
    if int(data.get("version", VERSION)) > VERSION:
        raise FlowError("This flow was saved by a newer SDK Studio; update to open it.")
    steps, variables = data.get("steps", []), data.get("variables", [])
    if not isinstance(steps, list) or not isinstance(variables, list):
        raise FlowError("The flow's cards or variables are malformed.")
    clean_steps = _clean_steps(steps, "")
    clean_subflows = _clean_subflows(data.get("subflows", []))
    clean_vars = []
    for variable in variables:
        if not isinstance(variable, dict) or not isinstance(variable.get("name"), str):
            raise FlowError("A variable has no name.")
        clean_vars.append({
            "name": variable["name"],
            "type": variable.get("type", "string"),
            "value": variable.get("value", ""),
            "prompt": bool(variable.get("prompt", False)),
        })
    return {
        "format": FORMAT,
        "version": VERSION,
        "name": str(name or data.get("name") or "Untitled flow"),
        "instrument": instrument or data.get("instrument"),
        "variables": clean_vars,
        "steps": clean_steps,
        "subflows": clean_subflows,
    }


class FlowStore:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _path(self, name: str) -> Path:
        return self.folder / f"{safe_name(name)}{SUFFIX}"

    def list(self) -> list[dict[str, Any]]:
        if not self.folder.is_dir():
            return []
        items = []
        for path in self.folder.glob(f"*{SUFFIX}"):
            try:
                flow = json.loads(path.read_text(encoding="utf-8-sig"))
                count = count_cards(flow.get("steps", []))
                instrument = flow.get("instrument")
            except (OSError, ValueError, AttributeError):
                continue  # an unreadable file just is not listed
            items.append({"name": path.name[: -len(SUFFIX)], "steps": count, "instrument": instrument, "modified": path.stat().st_mtime})
        return sorted(items, key=lambda item: item["modified"], reverse=True)

    def load(self, name: str) -> dict[str, Any]:
        path = self._path(name)
        if not path.is_file():
            raise FileNotFoundError(name)
        try:
            return normalize(json.loads(path.read_text(encoding="utf-8-sig")), name=path.name[: -len(SUFFIX)])
        except ValueError as exc:
            raise FlowError(f"{path.name} could not be read: {exc}") from exc

    def save(self, name: str, flow: Any, instrument: str | None = None) -> dict[str, Any]:
        clean = normalize(flow, name=safe_name(name), instrument=instrument)
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self._path(name)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(clean, indent=1) + "\n", encoding="utf-8")
        temporary.replace(path)  # a crash mid-write never leaves a half-written flow
        return {**clean, "saved_at": time.time()}

    def delete(self, name: str) -> None:
        path = self._path(name)
        if not path.is_file():
            raise FileNotFoundError(name)
        path.unlink()

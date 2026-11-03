"""What the connected instrument can do, so the palette can hide commands it cannot run.

Read from the instrument's configuration (`instrument_get_configuration`) when it connects: how many
1 mL / 5 mL / MagPip channels are fitted, whether there is an MPH96 head, a gripper (iSWAP or IPG)
and an autoload. A command that needs something the system does not have (the 5 mL channel commands
on a system with no 5 mL channels) is hidden; Studio keeps it in the flow if it is already there and
can show everything again on request.
"""

from __future__ import annotations

from typing import Any


def _arms(parameters: dict[str, Any]) -> list[dict[str, Any]]:
    return [arm for key in ("LeftArm", "RightArm", "left_arm", "right_arm") if isinstance(arm := parameters.get(key), dict)]


def _channels(arm: dict[str, Any], *keys: str) -> int:
    for key in keys:
        info = arm.get(key)
        if isinstance(info, dict) and isinstance(info.get("total"), (int, float)):
            return int(info["total"])
    return 0


def _present(value: Any) -> bool:
    """A head is fitted when VENUS reports an object (its details) or true; null / false / 0 channels is not fitted."""
    if isinstance(value, dict):
        total = value.get("total")
        return total is None or bool(total)
    return bool(value)


_GROUP_LABELS = (("channels_1ml", "1 mL"), ("channels_5ml", "5 mL"), ("channels_magpip", "MagPip"))


def channel_groups(counts: dict[str, int]) -> list[dict[str, Any]]:
    """The fitted channel types, each with how many channels it has. Numbering restarts at 1 for every type
    (1 mL channels 1-8, 5 mL channels 1-4), so a channel picker works on one type at a time."""
    return [{"key": key, "label": label, "count": counts[key]} for key, label in _GROUP_LABELS if counts.get(key)]


def from_configuration(parameters: dict[str, Any] | None) -> dict[str, Any] | None:
    """The capabilities in a configuration's return parameters, or None when it holds no arms (unknown)."""
    if not isinstance(parameters, dict):
        return None
    arms = _arms(parameters)
    if not arms:
        return None
    gripper = None
    for arm in arms:
        kind = (arm.get("gripper") or {}).get("type") if isinstance(arm.get("gripper"), dict) else None
        if kind:
            gripper = str(kind)
    counts = {
        "channels_1ml": sum(_channels(a, "channels1mL", "channels_1_ml") for a in arms),
        "channels_5ml": sum(_channels(a, "channels5mL", "channels_5_ml") for a in arms),
        "channels_magpip": sum(_channels(a, "channelsMagPip", "channels_mag_pip") for a in arms),
    }
    return {
        **counts,
        "channel_groups": channel_groups(counts),
        "mph96": any(_present(a.get("MPH96", a.get("mph96"))) for a in arms),
        "mph384": any(_present(a.get("MPH384", a.get("mph384"))) for a in arms),
        "gripper": gripper,
        "autoload": bool(parameters.get("Autoload", parameters.get("autoload"))),
    }


def return_parameters(response: Any) -> dict[str, Any] | None:
    """The configuration's return parameters inside a call_sdk_command response."""
    result = response.get("result") if isinstance(response, dict) else None
    parameters = result.get("returnParameters") if isinstance(result, dict) else None
    return parameters if isinstance(parameters, dict) else None


def describe(capabilities: dict[str, Any] | None) -> str:
    """A short summary for the connection pill's tooltip."""
    if not capabilities:
        return ""
    parts = []
    for label, key in (("1 mL channels", "channels_1ml"), ("5 mL channels", "channels_5ml"), ("MagPip channels", "channels_magpip")):
        if capabilities.get(key):
            parts.append(f"{capabilities[key]} {label}")
    if capabilities.get("mph96"):
        parts.append("MPH96")
    if capabilities.get("mph384"):
        parts.append("MPH384")
    if capabilities.get("gripper"):
        parts.append(str(capabilities["gripper"]))
    if capabilities.get("autoload"):
        parts.append("Autoload")
    return ", ".join(parts)


# -- which commands need what ---------------------------------------------------------------------------


def requires_for(name: str, sdk_category: str) -> str | None:
    """The capability a command needs: channels_5ml, channels_magpip, mph96, autoload, gripper, channels_1ml,
    or None when it runs on any system."""
    if sdk_category == "Channels5mL" or "_5ml" in name or name.startswith("core_5ml"):
        return "channels_5ml"
    if sdk_category == "ChannelsMagPip" or name.endswith("_magpip"):
        return "channels_magpip"
    if sdk_category == "MPH96" or "mph96" in name:
        return "mph96"
    if sdk_category == "Autoload" or name.startswith("autoload_"):
        return "autoload"
    if name.startswith("iswap_"):
        return "gripper"
    if name.startswith("core_") or name == "add_1ml_core_grip":
        return "channels_1ml"
    return None


def satisfied(requires: str | None, capabilities: dict[str, Any] | None) -> bool:
    """True when the system has what the command needs (or nothing is known, so nothing is hidden)."""
    if requires is None or capabilities is None:
        return True
    return bool(capabilities.get(requires))

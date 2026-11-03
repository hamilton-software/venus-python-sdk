"""Liquid-level reading extraction, as a StepObserver plugin.

Two sources of liquid-level data exist in the SDK today:

1. aspirate/aspirate_5ml already report per-channel liquid_level_mm/
   liquid_volume_ul as part of their normal response (see
   hamilton_venus.models.command_types.AspirationChannelData) -- confirmed
   directly against the SDK models, so this path is exact.
2. detect_liquid_level/detect_liquid_level_5ml return a bare CommandResponse
   with an untyped ``return_parameters: Any`` (no dedicated
   LiquidLevelReturnParameters model exists in the SDK) -- what keys VENUS
   actually populates there is unverified here. This extractor reads it
   defensively (dict access with a handful of plausible key names) and
   degrades to nothing found rather than guessing wrong field names.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hamilton_workflow_framework.execution_engine import SendFn, Step
from hamilton_workflow_framework.registry import RegistryEntry

_ASPIRATE_COMMANDS = {"aspirate", "aspirate_5ml"}
_DETECT_COMMANDS = {"detect_liquid_level", "detect_liquid_level_5ml"}

# Plausible key spellings for detect_liquid_level's untyped return_parameters,
# tried in order -- unverified against real VENUS output, see module docstring.
_LEVEL_KEYS = ("liquidLevel_mm", "liquid_level_mm", "liquidLevelMm")
_VOLUME_KEYS = ("liquidVolume_uL", "liquid_volume_ul", "liquidVolumeUl")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LiquidLevelObserver:
    """Emits a `liquid_level_reading` WS message per channel whenever a step
    reports (or plausibly reports) liquid-level data. Stateless -- just
    forwards readings; an app that wants a persisted per-well history should
    consume these messages itself rather than relying on this class to store them.
    """

    async def after_step(
        self, entry: RegistryEntry, kwargs: dict[str, Any], result: Any, step: Step, send: SendFn
    ) -> None:
        position = kwargs.get("positions") if isinstance(kwargs.get("positions"), str) else ""
        timestamp = _now_iso()

        if entry.method_name in _ASPIRATE_COMMANDS:
            channels_data = getattr(getattr(result, "return_parameters", None), "channels", None) or []
            for channel_data in channels_data:
                level = getattr(channel_data, "liquid_level_mm", None)
                volume = getattr(channel_data, "liquid_volume_ul", None)
                if level is None and volume is None:
                    continue
                await send({
                    "type": "liquid_level_reading",
                    "position": position,
                    "channel": getattr(channel_data, "channel", 0),
                    "liquid_level_mm": level or 0.0,
                    "liquid_volume_ul": volume or 0.0,
                    "timestamp": timestamp,
                })
            return

        if entry.method_name in _DETECT_COMMANDS:
            return_parameters = getattr(result, "return_parameters", None)
            if not isinstance(return_parameters, dict):
                return
            level = next((return_parameters[k] for k in _LEVEL_KEYS if k in return_parameters), None)
            volume = next((return_parameters[k] for k in _VOLUME_KEYS if k in return_parameters), None)
            if level is None and volume is None:
                return
            channels = kwargs.get("channels") or []
            for channel in channels or [0]:
                await send({
                    "type": "liquid_level_reading",
                    "position": position,
                    "channel": channel,
                    "liquid_level_mm": level or 0.0,
                    "liquid_volume_ul": volume or 0.0,
                    "timestamp": timestamp,
                })

"""Which instrument this PC has. A VENUS install is a STAR or a Vantage, never both, so Studio
reports it instead of asking -- read the same way the installer does: the InstCfgFile registry
value ("VStar.cfg" or any Vantage-flavoured name is a Vantage, anything else a STAR)."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from hamilton_venus._internal._sdk_paths import read_instrument_cfg_name

# Dev/test machines without a VENUS install can pin the type; a real install never needs this.
OVERRIDE_ENV = "HAMILTON_SDK_STUDIO_INSTRUMENT"


@lru_cache(maxsize=1)
def detect() -> dict[str, Any]:
    """{"type": "STAR" | "Vantage", "detected": bool, "config": cfg file name or None}.

    `detected` is False when the registry value is missing (no VENUS install found); the type
    is then STAR, the same fallback the SDK uses."""
    override = os.environ.get(OVERRIDE_ENV, "").strip()
    if override.lower() in ("star", "vantage"):
        return {"type": "Vantage" if override.lower() == "vantage" else "STAR", "detected": True, "config": None}
    config = read_instrument_cfg_name()
    name = (config or "").lower()
    vantage = name.startswith("vstar") or "vantage" in name
    return {"type": "Vantage" if vantage else "STAR", "detected": config is not None, "config": config}


def instrument_type() -> str:
    return detect()["type"]

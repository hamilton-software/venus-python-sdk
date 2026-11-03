"""Which instrument family this spoke's VENUS is installed for, and refusing the other one.

A VENUS install is a STAR or a Vantage, never both. A spoke is reached over the network by
orchestrators and AI agents on other computers (which may have the other family installed
themselves), so the spoke decides from *its own* registry, and a caller cannot talk it into the
wrong client: ``start_session`` and ``run_script`` both refuse it. The one way round it is for the
spoke's owner to set ``HAMILTON_MCP_ALLOW_INSTRUMENT_MISMATCH=1`` where the spoke starts (e.g. to
simulate the other family on a development PC).

Nothing is refused when the registry can't say which family is installed.
"""

from __future__ import annotations

import os

from hamilton_venus._internal._sdk_paths import installed_instrument_type, read_instrument_cfg_name
from hamilton_venus.models import InstrumentType

ALLOW_MISMATCH_ENV = "HAMILTON_MCP_ALLOW_INSTRUMENT_MISMATCH"

CLIENT_FAMILIES = {"StarClient": InstrumentType.STAR, "VantageClient": InstrumentType.Vantage}


def installed_instrument() -> InstrumentType | None:
    """The family this PC's VENUS is installed for (None if the registry can't say)."""
    kind = installed_instrument_type()
    if kind is None:
        return None
    return InstrumentType.Vantage if kind == "vantage" else InstrumentType.STAR


def mismatch_allowed() -> bool:
    return os.environ.get(ALLOW_MISMATCH_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def refusal_for_type(installed: InstrumentType, requested: InstrumentType) -> str:
    return (
        f"This spoke's VENUS is installed for {installed.value} (instrument config "
        f"{read_instrument_cfg_name()}), so it does not accept {requested.value} connections, "
        f"whatever the calling computer has installed. Call start_session(instrument_type="
        f"{installed.value!r}) or leave instrument_type out. start_session was not called."
    )


def refusal_for_client(installed: InstrumentType, client_name: str) -> str:
    wanted = "VantageClient" if installed is InstrumentType.Vantage else "StarClient"
    return (
        f"{client_name} cannot be used here: this spoke's VENUS is installed for {installed.value}, "
        f"so it does not accept {CLIENT_FAMILIES[client_name].value} connections. Use {wanted}."
    )


def wrong_client_message(client_name: str) -> str | None:
    """The refusal for a script building *client_name* (``StarClient`` / ``VantageClient``) on this
    spoke, or None when it is fine (right family, family unknown, or the owner allowed it)."""
    family = CLIENT_FAMILIES.get(client_name)
    installed = installed_instrument()
    if family is None or installed is None or family == installed or mismatch_allowed():
        return None
    return refusal_for_client(installed, client_name)

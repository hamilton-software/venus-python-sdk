"""Which SDK commands only read state.

Kept free of heavy imports (no FastMCP, no SDK) so callers outside the server, such as
the Claude Code plugin's hardware approval hook, can use it without loading the server.
"""

from __future__ import annotations

import re

# Read-only queries by name: a get / is / list / has / describe word (get_added_plates,
# instrument_is_idle, front_cover_is_locked, tip_pool_get_tip_counter, ...), a *_status
# reading, or status_* other than the status light itself. Deliberately not "check": tip_check
# may move channels.
_QUERY_COMMAND = re.compile(r"(^|_)(get|is|list|has|describe)(_|$)|_status$|^status_(?!light)")

# Command prefixes of the standalone benchtop devices (hamilton_venus.standalone_devices).
# They drive their own hardware whether or not the instrument session is simulated.
STANDALONE_DEVICE_PREFIXES = ("hhc_", "odtc_", "inheco_tec_", "tilt_module_", "media_fill_")


def is_query_command(name: str) -> bool:
    """True for a command that only reads state -- it does not count as instrument activity
    for the status light or the spoke status."""
    return bool(_QUERY_COMMAND.search(name))


def is_standalone_device_command(name: str) -> bool:
    """True for a command of a standalone benchtop device (HHC, ODTC, tilt module, ...)."""
    return name.startswith(STANDALONE_DEVICE_PREFIXES)

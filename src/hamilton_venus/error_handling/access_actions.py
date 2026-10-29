"""Instrument access actions offered while an error waits for a recovery.

While a WebAPI error handler works on an error the front cover stays locked and
the Vantage loading tray stays raised. VENUS therefore lists, next to the
recoveries, the one cover action and (Vantage only) the one tray action that
currently applies. They are sent with ``POST instrument-errors/{uuid}/action``
and do not answer the error: the instrument carries the action out and publishes
the same error again with the opposite action listed.

An operator escalation callback offers them with :func:`access_actions` and
returns :func:`access_action_recovery` for the one chosen; the SDK then submits
it and invokes the callback again with the republished error.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hamilton_venus.models.instrument_errors import ErrorData, ErrorRecovery

LOWER_LOAD_TRAY = "lower_load_tray"
RAISE_LOAD_TRAY = "raise_load_tray"
UNLOCK_DOOR = "unlock_door"
LOCK_DOOR = "lock_door"

# Server action ids (the same on STAR and Vantage); names are localized, ids are not.
ACCESS_ACTION_IDS: dict[int, str] = {
    4220: LOWER_LOAD_TRAY,
    4221: RAISE_LOAD_TRAY,
    4222: UNLOCK_DOOR,
    4223: LOCK_DOOR,
}

ACCESS_ACTION_LABELS: dict[str, str] = {
    LOWER_LOAD_TRAY: "Lower Load Tray",
    RAISE_LOAD_TRAY: "Raise Load Tray",
    UNLOCK_DOOR: "Unlock Door",
    LOCK_DOOR: "Lock Door",
}


def access_actions(error: ErrorData | Any) -> list[dict[str, Any]]:
    """The access actions *error* currently lists, as ``{"id", "key", "label"}`` dicts."""
    found: list[dict[str, Any]] = []
    listed = [*(getattr(error, "actions", None) or []), *(getattr(error, "recovery_actions", None) or [])]
    for action in listed:
        action_id = getattr(action, "id", None)
        key = ACCESS_ACTION_IDS.get(action_id) if isinstance(action_id, int) else None
        if key is None or any(item["key"] == key for item in found):
            continue
        found.append({"id": action.id, "key": key, "label": ACCESS_ACTION_LABELS[key]})
    return found


def is_access_action_recovery(recovery: ErrorRecovery) -> bool:
    """Whether *recovery* asks for an access action instead of answering the error."""
    return not recovery.selected_action_is_recovery and recovery.selected_action_id in ACCESS_ACTION_IDS


def access_action_recovery(error: ErrorData | Any, key: str | None) -> ErrorRecovery | None:
    """The payload that asks for access action *key* on *error*, or ``None`` if it is not listed."""
    wanted = (key or "").lower()
    for item in access_actions(error):
        if item["key"] == wanted:
            return ErrorRecovery(
                date=datetime.now(UTC).isoformat(),
                uuid=error.uuid,
                selected_action_id=item["id"],
                selected_action_is_recovery=False,
            )
    return None

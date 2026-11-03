"""Wire format between the run manager (parent) and ``child_bootstrap`` (the script's process).

Child -> parent: one event per line on the child's stdout, ``EVENT_PREFIX`` followed by a JSON
object with at least ``type`` and ``ts``. Everything else the script prints stays ordinary
text. The prefix starts with a NUL, which no script prints on purpose, and the parser looks for
it anywhere in a line so an event survives a script that happens to write half a line first.

Parent -> child: one command per line on the child's stdin --

    PAUSE
    RESUME
    STOP
    PROMPT_RESPONSE <prompt_id> <json>

where the JSON is ``{"kind": "action", "action": "<name>"}``, ``{"kind": "channels",
"channel_actions": {...}}``, or ``{"kind": "continue"}`` / ``{"kind": "abort"}`` for the
tip and liquid reload prompts.
"""

from __future__ import annotations

import json
import time
from typing import Any

EVENT_PREFIX = "\x00HVE\x00"


def encode_event(event_type: str, **data: Any) -> str:
    """One newline-terminated event line."""
    return EVENT_PREFIX + json.dumps({"type": event_type, "ts": time.time(), **data}, default=str) + "\n"


def decode_line(line: str) -> tuple[str, dict[str, Any] | None]:
    """Split a stdout line into ``(plain_text_before_the_event, event_or_None)``.

    A line with no event is ``(line, None)``. A line whose payload is not valid JSON is treated
    as plain text, so a stray prefix can never raise.
    """
    index = line.find(EVENT_PREFIX)
    if index < 0:
        return line, None
    payload = line[index + len(EVENT_PREFIX) :].strip()
    try:
        event = json.loads(payload)
    except ValueError:
        return line, None
    if not isinstance(event, dict) or "type" not in event:
        return line, None
    return line[:index], event


def prompt_response_line(prompt_id: str, response: dict[str, Any]) -> str:
    return f"PROMPT_RESPONSE {prompt_id} {json.dumps(response)}\n"

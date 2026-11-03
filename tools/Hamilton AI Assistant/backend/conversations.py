"""Past conversations, from their audit files (one JSON line per event, see AgentRunner._audit).

The audit file is the conversation: the page's events, in order. Reopening one replays them
into the page, and the engine resumes its own session (``engine_session`` events carry its
id), so the assistant remembers what was said. Instrument sessions are not resumed: the MCP
server that held them ended with the conversation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TITLE_CHARS = 90
# Audit-only keys that are not part of the page's events.
_AUDIT_KEYS = ("time", "windows_user")


def _read_lines(path: Path) -> list[dict[str, Any]]:
    lines = []
    try:
        with path.open(encoding="utf-8") as f:
            for raw in f:
                try:
                    line = json.loads(raw)
                except ValueError:
                    continue  # a line cut short when the app was closed mid-write
                if isinstance(line, dict):
                    lines.append(line)
    except OSError:
        return []
    return lines


def conversation_path(folder: Path, conversation_id: str) -> Path:
    """The audit file of *conversation_id*; raises ValueError for anything but a plain name in *folder*."""
    if not conversation_id or Path(conversation_id).name != conversation_id or conversation_id.startswith("."):
        raise ValueError("Unknown conversation.")
    path = folder / f"{conversation_id}.jsonl"
    if not path.is_file():
        raise ValueError("That conversation no longer exists.")
    return path


def summarize(path: Path) -> dict[str, Any] | None:
    lines = _read_lines(path)
    messages = [line for line in lines if line.get("type") == "user_message"]
    if not messages:
        return None  # nothing was ever asked: not worth listing
    titles = [line.get("title") for line in lines if line.get("type") == "title" and line.get("title")]
    title = titles[-1] if titles else (
        str(messages[0].get("text", "")).strip().splitlines()[0] if messages[0].get("text") else "")
    sessions = [line for line in lines if line.get("type") == "session_state" and line.get("simulated") is not None]
    return {
        "id": path.stem,
        "title": title[:TITLE_CHARS] + ("…" if len(title) > TITLE_CHARS else ""),
        "started": lines[0].get("time"),
        "updated": lines[-1].get("time"),
        "messages": len(messages),
        "by": messages[0].get("by") or lines[0].get("windows_user"),
        "live": any(line.get("simulated") is False for line in sessions),
        "resumable": any(line.get("type") == "engine_session" for line in lines),
    }


def list_conversations(folder: Path, limit: int = 100) -> list[dict[str, Any]]:
    """Newest first (by last change)."""
    if not folder.is_dir():
        return []
    paths = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    summaries = []
    for path in paths:
        summary = summarize(path)
        if summary is not None:
            summaries.append(summary)
            if len(summaries) >= limit:
                break
    return summaries


def load(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """(the page's events, the engine session id to resume or None). Cards that were still
    open when the conversation ended are closed, so the page doesn't offer to answer them."""
    events: list[dict[str, Any]] = []
    session_id = None
    open_cards: dict[str, str] = {}
    for line in _read_lines(path):
        event = {k: v for k, v in line.items() if k not in _AUDIT_KEYS}
        kind = event.get("type")
        if kind == "engine_session":
            session_id = event.get("session_id") or session_id
        elif kind in ("approval_request", "form_request"):
            open_cards[str(event.get("id"))] = kind
        elif kind in ("approval_resolved", "form_resolved"):
            open_cards.pop(str(event.get("id")), None)
        events.append(event)
    for card_id, kind in open_cards.items():
        if kind == "approval_request":
            events.append({"type": "approval_resolved", "id": card_id, "approved": False, "by": "conversation ended"})
        else:
            events.append({"type": "form_resolved", "id": card_id, "action": "cancel", "by": "conversation ended"})
    return events, session_id

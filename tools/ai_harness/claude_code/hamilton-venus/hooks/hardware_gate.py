"""Claude Code hook: ask a person before the AI takes control of real Hamilton hardware.

Runs as both the PreToolUse and the PostToolUse hook on the hamilton-venus MCP server's
tools (hooks.json). Claude Code passes the event as JSON on stdin. The rules are
hamilton_venus_mcp.hardware_policy, shared with the Hamilton AI Assistant app.

Approval is asked once per session, not per command. PreToolUse answers "ask" (Claude Code
shows an approval prompt with the reason) when a call needs approval and has not been
granted yet:
- starting a live session (start_session simulate=false) -- approving it, or choosing "live"
  in start_session's own form, grants every later command of that session, until it is
  closed or another session is started;
- the first command of a standalone device (hhc_*, tilt_module_*, ...) not run with
  simulate=True -- granted for that device from then on;
- every VENUS run control call (venus_abort / venus_pause / venus_resume) and a script run
  on hardware -- asked each time.
operator_resolve_prompt is denied: only people answer script-run prompts.
Anything else gets no answer, so the user's normal Claude Code permissions apply.
If the hook itself fails, it answers "ask", never allow.

PostToolUse records this Claude session's instrument session (simulated or live) and the
grants the user gave (a call that needed approval and ran was approved), and appends every
executed hardware call to hardware_calls.jsonl, granted or not. Both files live in
%LOCALAPPDATA%\Hamilton\ai_harness (HAMILTON_AI_HARNESS_DIR overrides).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    from hamilton_venus_mcp.hardware_policy import (
        DENY_TOOLS,
        ONCE,
        Approval,
        approval_needed,
        simulated_after,
    )
except ImportError:  # hook run by a Python without the MCP server: every call asks
    from dataclasses import dataclass

    DENY_TOOLS = {"operator_resolve_prompt": "Only a person answers script-run prompts."}
    ONCE = "once"

    @dataclass(frozen=True)
    class Approval:  # type: ignore[no-redef]
        reason: str
        grants: str

    def approval_needed(tool, tool_input, simulated, granted=frozenset()):  # type: ignore[no-redef]
        return Approval(f"{tool}: the Hamilton safety rules could not be loaded, so every call needs approval", ONCE)

    def simulated_after(tool, tool_input, result, current):  # type: ignore[no-redef]
        return None


def state_dir() -> Path:
    override = os.environ.get("HAMILTON_AI_HARNESS_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Hamilton" / "ai_harness"


def short_tool_name(tool_name: str) -> str:
    """mcp__plugin_hamilton-venus_hamilton-venus__start_session -> start_session."""
    return tool_name.rsplit("__", 1)[-1]


def _load_sessions() -> dict[str, Any]:
    try:
        return json.loads((state_dir() / "sessions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_session(claude_session: str, simulate: bool | None, granted: set[str]) -> None:
    sessions = _load_sessions()
    sessions[claude_session] = {"simulate": simulate, "granted": sorted(granted), "updated": time.time()}
    # Keep the file small: drop entries untouched for a week.
    cutoff = time.time() - 7 * 24 * 3600
    sessions = {k: v for k, v in sessions.items() if v.get("updated", 0) >= cutoff}
    path = state_dir() / "sessions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sessions, indent=1), encoding="utf-8")


def session_state(claude_session: str) -> tuple[bool | None, set[str]]:
    """(simulated True / False / None when unknown, grants given) for this Claude session."""
    entry = _load_sessions().get(claude_session) or {}
    return entry.get("simulate"), set(entry.get("granted") or [])


def session_simulated(claude_session: str) -> bool | None:
    return session_state(claude_session)[0]


def _audit(event: dict[str, Any], tool: str, reason: str) -> None:
    response = event.get("tool_response")
    is_error = isinstance(response, dict) and bool(response.get("isError") or response.get("error"))
    line = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "claude_session": event.get("session_id"),
        "tool": tool,
        "input": event.get("tool_input"),
        "reason": reason,
        "status": "error" if is_error else "ok",
    }
    path = state_dir() / "hardware_calls.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, default=str) + "\n")


def pre_tool_use(event: dict[str, Any]) -> dict[str, Any] | None:
    tool = short_tool_name(str(event.get("tool_name", "")))
    tool_input = event.get("tool_input") or {}
    if tool in DENY_TOOLS:
        return _decision("deny", DENY_TOOLS[tool])
    simulated, granted = session_state(str(event.get("session_id", "")))
    approval = approval_needed(tool, tool_input, simulated, granted)
    if approval is None:
        return None
    scope = "this call only" if approval.grants == ONCE else "allows it for the rest of this session"
    return _decision("ask", f"Hamilton hardware approval ({scope}): {approval.reason}")


def post_tool_use(event: dict[str, Any]) -> None:
    tool = short_tool_name(str(event.get("tool_name", "")))
    tool_input = event.get("tool_input") or {}
    claude_session = str(event.get("session_id", ""))
    simulated, granted = session_state(claude_session)
    # Audit every executed hardware call, whether it was asked about or ran under a grant.
    moved = approval_needed(tool, tool_input, simulated)
    if moved is not None:
        _audit(event, tool, moved.reason)
    # It ran, so if it needed approval, the user approved it: keep the grant.
    approval = approval_needed(tool, tool_input, simulated, granted)
    if approval is not None and approval.grants != ONCE:
        granted.add(approval.grants)
    new_simulated = simulated_after(tool, tool_input, event.get("tool_response"), simulated)
    # A live session that start_session opened is itself the grant: it took either this
    # approval or the user choosing "live" in start_session's own form.
    if tool == "start_session":
        granted.discard("live_session")
        if new_simulated is False:
            granted.add("live_session")
    elif tool == "close_session":
        granted.discard("live_session")
    _save_session(claude_session, new_simulated, granted)


def _decision(decision: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
        if event.get("hook_event_name") == "PostToolUse":
            post_tool_use(event)
            return 0
        output = pre_tool_use(event)
    except Exception as exc:  # never let a hook failure turn into an unchecked hardware call
        if '"PostToolUse"' in raw:
            return 0
        output = _decision("ask", f"Hamilton hardware approval: the safety check failed ({exc}); review this call")
    if output is not None:
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())

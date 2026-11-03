"""Which hamilton-venus tool calls need a person's approval because they may move real hardware.

One policy for every AI harness: the Claude Code plugin's hook
(ai_harness/claude_code/hamilton-venus/hooks/hardware_gate.py) and the Hamilton AI Assistant
app both call approval_needed(). Like command_kinds, it imports nothing heavy.

Approval is asked once, not per command: approving (or choosing "live" in start_session's
own form) grants control for the rest of the session --
- LIVE_SESSION: every command of the live instrument session, until the session is closed or
  another one is started (see live_session_after);
- "device:<prefix>": one standalone benchtop device (hhc_, tilt_module_, ...), which runs its
  own hardware outside the instrument session;
- ONCE: just that call -- VENUS run control (abort / pause / resume), which acts on whatever
  VENUS is running, and a script run on hardware.
The caller tracks whether the session is simulated (True), live (False) or not known (None),
from the tool results (see simulated_after), and which grants the user has given.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from hamilton_venus_mcp.command_kinds import (
    STANDALONE_DEVICE_PREFIXES,
    is_query_command,
    is_standalone_device_command,
)

LIVE_SESSION = "live_session"
ONCE = "once"

SESSION_COMMAND_TOOLS = {"call_sdk_command", "poll_sdk_command_until", "send_raw_command"}
VENUS_RUN_CONTROL_TOOLS = {"venus_abort", "venus_pause", "venus_resume"}
# Part of operating the session: free in simulation, covered by the live-session grant.
SESSION_CONTROL_TOOLS = {"abort_run", "resolve_operator_prompt"}
# Never allowed for an AI, approval or not.
DENY_TOOLS = {"operator_resolve_prompt": "Only a person answers script-run prompts, on the operator page or the hub dashboard."}


@dataclass(frozen=True)
class Approval:
    reason: str
    # What approving grants: LIVE_SESSION, "device:<prefix>" or ONCE.
    grants: str


def _command_name(tool: str, tool_input: dict[str, Any]) -> str:
    if tool == "send_raw_command":
        return f"{tool_input.get('category', '')}.{tool_input.get('action_name', '')}"
    return str(tool_input.get("name", ""))


def _command_kwargs(tool: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    key = "parameters" if tool == "send_raw_command" else "kwargs"
    value = tool_input.get(key)
    return value if isinstance(value, dict) else {}


def device_grant(command_name: str) -> str:
    prefix = next((p for p in STANDALONE_DEVICE_PREFIXES if command_name.startswith(p)), command_name)
    return f"device:{prefix}"


def approval_needed(
    tool: str, tool_input: dict[str, Any], simulated: bool | None, granted: frozenset[str] | set[str] = frozenset()
) -> Approval | None:
    """The approval this call needs, or None when it may run. *tool* is the hamilton-venus
    tool's own name (start_session, call_sdk_command, ...); *granted* what the user already
    allowed this session."""
    live_granted = simulated is False and LIVE_SESSION in granted
    if tool == "start_session":
        if tool_input.get("simulate", True) is False:
            instrument = tool_input.get("instrument_type", "STAR")
            return Approval(f"start_session on the REAL INSTRUMENT ({instrument}, simulate=false)", LIVE_SESSION)
        return None
    if tool == "run_script":
        if tool_input.get("simulate", True) is False:
            return Approval(f"run_script {tool_input.get('script', '')} on the REAL INSTRUMENT (simulate=false)", ONCE)
        return None
    if tool == "connect_instrument":
        if tool_input.get("initialize") and simulated is not True and not live_granted:
            return Approval("connect_instrument(initialize=True) initializes the REAL INSTRUMENT (arms and channels move)",
                            LIVE_SESSION)
        return None
    if tool in VENUS_RUN_CONTROL_TOOLS:
        return Approval(f"{tool} acts on whatever VENUS is running: {json.dumps(tool_input)}", ONCE)
    if tool in SESSION_CONTROL_TOOLS:
        if simulated is True or live_granted:
            return None
        return Approval(f"{tool} acts on the instrument: {json.dumps(tool_input)}", LIVE_SESSION)
    if tool not in SESSION_COMMAND_TOOLS:
        return None

    name = _command_name(tool, tool_input)
    kwargs = _command_kwargs(tool, tool_input)
    if tool != "send_raw_command" and is_query_command(name):
        return None
    if is_standalone_device_command(name):
        grant = device_grant(name)
        if kwargs.get("simulate") is True or grant in granted:
            return None
        return Approval(f"{name} drives a REAL DEVICE ({grant.split(':', 1)[1].rstrip('_')})", grant)
    if simulated is True or live_granted:
        return None
    where = "the REAL INSTRUMENT" if simulated is False else "the instrument (session mode unknown, may be real)"
    return Approval(f"{name} on {where}; kwargs={json.dumps(kwargs)}", LIVE_SESSION)


def hardware_reason(
    tool: str, tool_input: dict[str, Any], simulated: bool | None, granted: frozenset[str] | set[str] = frozenset()
) -> str | None:
    """approval_needed()'s reason, or None."""
    approval = approval_needed(tool, tool_input, simulated, granted)
    return None if approval is None else approval.reason


def session_status_in(response: Any) -> dict[str, Any] | None:
    """The {"simulate": ..., ...} dict in a start_session / get_session_status / select_deck_layout
    result, whether it arrives as a dict, JSON text or MCP content blocks."""
    if isinstance(response, dict):
        if isinstance(response.get("simulate"), bool):
            return response
        for key in ("structuredContent", "result", "content"):
            found = session_status_in(response.get(key))
            if found is not None:
                return found
        if isinstance(response.get("text"), str):
            return session_status_in(response["text"])
    elif isinstance(response, list):
        for item in response:
            found = session_status_in(item)
            if found is not None:
                return found
    elif isinstance(response, str):
        try:
            return session_status_in(json.loads(response))
        except ValueError:
            return None
    return None


def simulated_after(tool: str, tool_input: dict[str, Any], result: Any, current: bool | None) -> bool | None:
    """The session's simulated/live state after this tool call succeeded."""
    if tool == "close_session":
        return None
    if tool == "start_session":
        status = session_status_in(result)
        if status is not None:
            return status["simulate"]
        return tool_input["simulate"] if isinstance(tool_input.get("simulate"), bool) else None
    if tool == "get_session_status":
        status = session_status_in(result)
        if status is not None:
            # With no session open, "simulate" is only the default, not a fact about the instrument.
            return status["simulate"] if status.get("session_active") else None
    return current


def live_session_after(tool: str, result: Any, current: bool) -> bool:
    """Whether the live-session grant holds after this tool call succeeded. A live session
    started by start_session is itself the grant: it took either an approved approval or the
    user choosing "live" in start_session's form. Closing it, or starting a simulated one, ends it."""
    if tool == "start_session":
        status = session_status_in(result)
        return status is not None and status["simulate"] is False
    if tool == "close_session":
        return False
    return current

"""What happens to each tool call the agent makes (the engine's can_use_tool callback).

The rules themselves are hamilton_venus_mcp.hardware_policy, shared with the Claude Code
plugin's hook. Here they turn into one of three decisions:
- refuse: not a Hamilton instrument tool, or never allowed for an AI (operator_resolve_prompt);
- ask: needs control the user has not granted yet -- the user approves or denies it on an
  approval card. Approval is per session, not per command: approving the live instrument
  (or choosing "live" in start_session's form) covers every command until the session ends;
  each standalone device is approved once; only VENUS run control is asked every time;
- allow: everything else (simulated sessions, queries, docs, catalogs, granted control).

Through a hub, every instrument tool is wrapped in call_tool_on(spoke_id, tool_name,
arguments) or broadcast_tool_call(...). The wrapped call gets the same rules, against that
spoke's own session: each spoke is a "target", and what the user grants is scoped to it
("live_session@star1"). The direct server (local or network spoke) is the target "".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from hamilton_venus_mcp.hardware_policy import DENY_TOOLS, ONCE, approval_needed

SERVER_NAME = "hamilton-venus"
HUB_SERVER_NAME = "hamilton-venus-hub"
MCP_PREFIX = f"mcp__{SERVER_NAME}__"
HUB_PREFIX = f"mcp__{HUB_SERVER_NAME}__"

HUB_RELAY_TOOLS = ("call_tool_on", "broadcast_tool_call")
# Hub tools that change the hub's spoke list, which every hub user shares.
HUB_ADMIN_TOOLS = ("add_spoke", "remove_spoke")
# Target of a broadcast without spoke_ids: every spoke, whose sessions this app can't know.
ALL_SPOKES = "*"


def short_name(tool_name: str) -> str:
    for prefix in (MCP_PREFIX, HUB_PREFIX):
        if tool_name.startswith(prefix):
            return tool_name[len(prefix):]
    return tool_name


def is_hub_tool(tool_name: str) -> bool:
    return tool_name.startswith(HUB_PREFIX)


def scoped(grant: str, target: str) -> str:
    """A grant for one target: unchanged for the direct server, "<grant>@<spoke>" via a hub."""
    return f"{grant}@{target}" if target and grant != ONCE else grant


def grants_for(granted: frozenset[str] | set[str], target: str) -> set[str]:
    """The plain grants (as hardware_policy knows them) the user gave *target*."""
    if not target:
        return {g for g in granted if "@" not in g}
    suffix = f"@{target}"
    return {g[: -len(suffix)] for g in granted if g.endswith(suffix)}


def instrument_calls(tool: str, tool_input: dict[str, Any], hub: bool) -> list[tuple[str, str, dict[str, Any]]]:
    """(target, instrument tool, its arguments) for each spoke call this tool call makes;
    [] for a hub's own tools."""
    if not hub:
        return [("", tool, tool_input)]
    if tool not in HUB_RELAY_TOOLS:
        return []
    inner = str(tool_input.get("tool_name") or "")
    arguments = tool_input.get("arguments") if isinstance(tool_input.get("arguments"), dict) else {}
    if tool == "call_tool_on":
        return [(str(tool_input.get("spoke_id") or ""), inner, arguments)]
    spoke_ids = tool_input.get("spoke_ids")
    targets = [str(s) for s in spoke_ids] if isinstance(spoke_ids, list) and spoke_ids else [ALL_SPOKES]
    return [(target, inner, arguments) for target in targets]


@dataclass(frozen=True)
class Decision:
    action: Literal["allow", "ask", "refuse"]
    reason: str = ""
    # For "ask": what approving grants (hardware_policy.LIVE_SESSION, "device:<prefix>" or ONCE),
    # scoped to a hub spoke as "<grant>@<spoke>".
    grants: str = ""


def decide(
    tool_name: str,
    tool_input: dict[str, Any],
    simulated: bool | None | dict[str, bool | None],
    granted: frozenset[str] | set[str] = frozenset(),
) -> Decision:
    """*simulated*: whether each target's open instrument session is simulated (True), live
    (False) or not known (None) -- one value for the direct server, or {target: value};
    *granted*: the control the user already gave (see scoped)."""
    hub = is_hub_tool(tool_name)
    if not hub and not tool_name.startswith(MCP_PREFIX):
        return Decision("refuse", "Only the Hamilton instrument tools are available in this app.")
    tool = short_name(tool_name)
    if hub and tool in HUB_ADMIN_TOOLS:
        return Decision("ask", f"{tool} changes the hub's spoke list, which everyone using the hub shares.", ONCE)
    sessions = simulated if isinstance(simulated, dict) else {"": simulated}
    calls = instrument_calls(tool, tool_input, hub)
    if hub and tool in HUB_RELAY_TOOLS and not calls[0][1]:
        return Decision("refuse", f"{tool} needs a tool_name.")
    asks: list[tuple[str, Any]] = []
    for target, inner, arguments in calls:
        if inner in DENY_TOOLS:
            return Decision("refuse", DENY_TOOLS[inner])
        approval = approval_needed(inner, arguments, sessions.get(target), grants_for(granted, target))
        if approval is not None:
            asks.append((target, approval))
    if not asks:
        return Decision("allow")
    if len(asks) == 1:
        target, approval = asks[0]
        where = f" (spoke {target})" if target and target != ALL_SPOKES else (" (every spoke)" if target else "")
        grant = ONCE if target == ALL_SPOKES else scoped(approval.grants, target)
        return Decision("ask", approval.reason + where, grant)
    spokes = ", ".join(t for t, _ in asks)
    return Decision("ask", f"{asks[0][1].reason} (spokes {spokes})", ONCE)

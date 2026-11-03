"""Shared library for card scripts -- connect, do one SDK action, or terminate.

An orchestrator built from separate "cards" (an Initialize card, a Show-tip-counter
card, an Add-reagent-to-plate card, a Finish card, ...) runs each one as its own,
independent Python script/process invocation -- nothing in memory survives from one
card to the next. Within one card, every call reuses one MCP session per server (opened
on the first call, so later calls skip the handshake; dropped when the process exits).
What actually stays open across cards is the session on the spoke process itself (a
StarClient/VantageClient the spoke keeps alive until something explicitly closes it) --
that's why this works at all without any card needing to hold anything.

See card_connect.py / card_action.py / card_terminate.py in this same folder for the
three card scripts built on top of this library -- each is a thin, standalone wrapper
around exactly one of start() / run() / finish(), meant to be read end to end as "what
does one card's script actually look like."

Works two ways, chosen by whether spoke_id is given:

  - Direct mode (spoke_id=None): `url` is a spoke's own MCP endpoint
    (hamilton_venus_mcp), e.g. "http://localhost:8000/mcp" when a card runs on the same
    PC as the instrument, or that PC's LAN address otherwise. The spoke must be started
    with HAMILTON_MCP_TRANSPORT=streamable-http -- its default is local stdio only (see
    mcp_server/README.md).
  - Hub mode (spoke_id="FM STARlet", say): `url` is the fleet hub's endpoint
    (hamilton_venus_mcp_hub); every call is relayed through the hub's own
    call_tool_on(spoke_id, tool_name, arguments) tool. Use this when a card's PC is
    different from the instrument's, or the deployment already reaches the fleet
    through the hub for other reasons.

Both modes drive the exact same spoke tools (start_session / connect_instrument /
call_sdk_command / get_session_status / close_session) -- only how each call is wrapped
differs (see _dispatch()). The session itself always lives on the spoke process; going
through the hub only adds a relay hop, not a second copy of that state.

No dependencies beyond the standard library.

## connection_id: telling "my" session apart from a later, different one

A spoke has exactly one session slot. start_session() always tears down and replaces
whatever was already open, silently -- so if two workflows ever ran against the same
spoke close together, a later card from workflow A could execute against workflow B's
session instead of its own, with nothing to catch it. start() returns a fresh
connection_id every time it opens a session; pass that into run()/finish() as
expected_connection_id and they refuse with a clear error instead of silently acting on
whatever happens to be open when a different connection is active.

Two ways a later card gets that value:

  1. If your orchestrator can carry a value from one card's output into a later card's
     input (common even in tools that can't hold live objects between cards): wire
     start()'s connection_id output into every later card's --connection-id input,
     including the Finish card. Full protection across the whole workflow.
  2. If it can't, or that's unclear: call status() first to read whatever connection_id
     is currently open, then immediately use that for the card's own action. This only
     guards the narrow window within that one card's own two calls, not the whole
     workflow -- weaker, but needs no data-passing at all, and it still turns "no
     session open" (nobody ran the Initialize card, or it failed) into a clear error
     instead of a confusing one from deeper in the SDK.

## Two more things worth knowing before relying on this for unattended operation

- Nothing cleans up a session left open by a card process that disappears uncleanly --
  the session (and the instrument connection) stays open until something explicitly
  closes it or the spoke restarts. Make sure a Finish card always runs, even on a
  workflow failure.
- A session and a whole-script run_script are mutually exclusive on one spoke, and the
  tip-counter dialog still needs a person at the instrument PC once per session (not
  once per action, but it can't be answered remotely) -- see "Tip counter dialogs" in
  either README.
"""

from __future__ import annotations

import atexit
import itertools
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from enum import StrEnum
from typing import Any

_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
_PROTOCOL_VERSION = "2025-03-26"


AUTH_TOKEN_ENV = "HAMILTON_MCP_AUTH_TOKEN"

# url -> bearer token, from set_auth_token() (Instrument(token=...) calls it).
_auth_tokens: dict[str, str] = {}


def set_auth_token(url: str, token: str | None) -> None:
    """Send ``Authorization: Bearer <token>`` on every call to *url* -- for a spoke or hub
    started with HAMILTON_MCP_AUTH_TOKEN. None removes it. Without one set here, the
    HAMILTON_MCP_AUTH_TOKEN environment variable (if set) is used for every URL."""
    if token:
        _auth_tokens[url] = token
    else:
        _auth_tokens.pop(url, None)


def _auth_token_for(url: str) -> str | None:
    return _auth_tokens.get(url) or os.environ.get(AUTH_TOKEN_ENV, "").strip() or None


class OrchestratorCallError(RuntimeError):
    """A start_session / connect_instrument / call_sdk_command / get_session_status /
    close_session call failed -- the message is that tool's own error text (or the
    hub's, in hub mode), or the SDK command's own reported error for run()."""


class _SessionGone(Exception):
    """The server no longer knows this MCP session (it restarted, or dropped it)."""


def _post(url: str, body: dict[str, Any], mcp_session_id: str | None, timeout_s: float) -> tuple[str | None, dict[str, Any] | None]:
    headers = dict(_HEADERS)
    if mcp_session_id:
        headers["mcp-session-id"] = mcp_session_id
    token = _auth_token_for(url)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, json.dumps(body).encode(), headers)
    try:
        response = urllib.request.urlopen(request, timeout=timeout_s)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            hint = "the token was rejected" if token else f"it requires a bearer token (set_auth_token / {AUTH_TOKEN_ENV})"
            raise OrchestratorCallError(f"{url} refused the call: {hint}.") from exc
        if exc.code in (400, 404) and mcp_session_id:
            raise _SessionGone(str(exc)) from exc
        raise OrchestratorCallError(f"Could not reach {url}: {exc}") from exc
    except urllib.error.URLError as exc:
        raise OrchestratorCallError(f"Could not reach {url}: {exc}") from exc
    message = None
    for line in response.read().decode().splitlines():
        if line.startswith("data:"):
            message = json.loads(line[5:])
    return response.headers.get("mcp-session-id"), message


# One MCP session per server URL for the life of this process (one card): the initialize
# handshake is paid on the first call only -- later calls are a single tools/call request.
# Nothing is shared across processes; each card opens its own and drops it on exit.
_mcp_sessions: dict[str, str] = {}
_sessions_lock = threading.Lock()
_request_ids = itertools.count(1)


def _open_session(url: str, timeout_s: float) -> str:
    mcp_session_id, _ = _post(
        url,
        {
            "jsonrpc": "2.0", "id": next(_request_ids), "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "orchestrator-card", "version": "1"},
            },
        },
        None,
        timeout_s,
    )
    _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, mcp_session_id, timeout_s)
    if not mcp_session_id:
        raise OrchestratorCallError(f"{url} did not start an MCP session.")
    return mcp_session_id


def _session_for(url: str, timeout_s: float) -> str:
    with _sessions_lock:
        existing = _mcp_sessions.get(url)
    if existing:
        return existing
    opened = _open_session(url, timeout_s)
    with _sessions_lock:
        return _mcp_sessions.setdefault(url, opened)


def _forget_session(url: str, mcp_session_id: str) -> None:
    with _sessions_lock:
        if _mcp_sessions.get(url) == mcp_session_id:
            del _mcp_sessions[url]


def close_connections() -> None:
    """Tell every server this process talked to that its MCP session can go (best effort --
    also run automatically when the process exits). The instrument session is unaffected."""
    with _sessions_lock:
        sessions = list(_mcp_sessions.items())
        _mcp_sessions.clear()
    for url, mcp_session_id in sessions:
        headers = {"mcp-session-id": mcp_session_id}
        token = _auth_token_for(url)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            urllib.request.urlopen(urllib.request.Request(url, headers=headers, method="DELETE"), timeout=2).close()
        except (urllib.error.URLError, OSError):
            pass


atexit.register(close_connections)


def _call_tool(url: str, tool_name: str, arguments: dict[str, Any], *, timeout_s: float) -> Any:
    """One tools/call on this process's MCP session with *url* (opened on first use). If the
    server no longer knows the session -- it restarted, say -- a new one is opened and the
    call is sent once more."""
    body = {"jsonrpc": "2.0", "id": next(_request_ids), "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}}
    mcp_session_id = _session_for(url, timeout_s)
    try:
        _, message = _post(url, body, mcp_session_id, timeout_s)
    except _SessionGone:
        _forget_session(url, mcp_session_id)
        mcp_session_id = _session_for(url, timeout_s)
        try:
            _, message = _post(url, {**body, "id": next(_request_ids)}, mcp_session_id, timeout_s)
        except _SessionGone as exc:
            _forget_session(url, mcp_session_id)
            raise OrchestratorCallError(f"{url} rejected a fresh MCP session: {exc}") from exc
    if message is None:
        raise OrchestratorCallError(f"{tool_name}: no response")
    if "error" in message:
        detail = message["error"]
        raise OrchestratorCallError(f"{tool_name}: {detail.get('message', detail)}")
    result = message.get("result") or {}
    if result.get("isError"):
        text = "; ".join(c.get("text", str(c)) for c in result.get("content", []))
        raise OrchestratorCallError(f"{tool_name}: {text or 'tool reported an error'}")
    # A dict tool result comes back as one text content block holding its JSON; a list
    # result as one block per item.
    items = []
    for content in result.get("content", []):
        text = content.get("text")
        if text is None:
            continue
        try:
            items.append(json.loads(text))
        except ValueError:
            items.append(text)
    if len(items) == 1:
        return items[0]
    if items:
        return items
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and list(structured) == ["result"]:
        return structured["result"]  # e.g. an empty list
    return result


def _dispatch(url: str, spoke_id: str | None, tool_name: str, arguments: dict[str, Any], *, timeout_s: float) -> Any:
    """Route one spoke tool call: straight through in direct mode, or wrapped in the
    hub's call_tool_on in hub mode -- then unwrap either kind of "this failed" result
    into a raised OrchestratorCallError, so a card's script can just let it propagate
    (mapped to a non-zero exit) instead of checking a status field itself.

    Two failure shapes to unwrap here: the hub's call_tool_on never raises/isError's
    for an INNER spoke-tool failure -- it reports {"status": "error", "message": ...}
    instead (hamilton_venus_mcp_hub/server.py's _unwrap_call_tool_result); and
    call_sdk_command itself catches an ordinary VENUS command failure and returns
    {"status": "error", "command": ..., "result": ...} rather than raising, so a caller
    can inspect it without a stack trace (see mcp_server/hamilton_venus_mcp/server.py's
    _dispatch_sdk_command) -- for a one-shot card, either shape means "this card
    failed," so both are raised the same way here. A successful result from any tool
    this library calls never carries a "status" key at all.
    """
    if spoke_id is None:
        result = _call_tool(url, tool_name, arguments, timeout_s=timeout_s)
    else:
        hub_arguments: dict[str, Any] = {
            "spoke_id": spoke_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "call_timeout_s": timeout_s,
        }
        result = _call_tool(url, "call_tool_on", hub_arguments, timeout_s=timeout_s)
    if isinstance(result, dict) and result.get("status") == "error":
        raise OrchestratorCallError(f"{tool_name}: {result.get('message') or result.get('result') or result}")
    return result


class InstrumentType(StrEnum):
    """The instrument_type for start() / Instrument.start(): InstrumentType.STAR or
    InstrumentType.VANTAGE. Picking a constant instead of typing the string rules out a
    typo (e.g. "Vantge") that would only fail at the spoke. Each value is the exact string
    the spoke expects, so it also works anywhere a plain string does."""

    STAR = "STAR"
    VANTAGE = "Vantage"


# Shorter aliases, kept for existing cards: STAR is InstrumentType.STAR.
STAR = InstrumentType.STAR
VANTAGE = InstrumentType.VANTAGE


def start(
    url: str,
    spoke_id: str | None = None,
    *,
    simulate: bool = True,
    deck_name: str | None = None,
    load_previous_deck: bool = False,
    instrument_type: InstrumentType | None = None,
    initialize: bool = True,
    connect_timeout_s: float = 200.0,
    hold_on_error: bool = False,
    error_profile: str | None = None,
    session_name: str | None = None,
) -> dict[str, Any]:
    """Initialize card body: opens a session (replacing whatever was open before) and
    connects the instrument. Returns the combined result, including a fresh
    "connection_id" -- see the module docstring's "telling my session apart" section for
    what to do with it.

    Args:
        url: A spoke's MCP endpoint (direct mode) or the hub's (hub mode).
        spoke_id: None for direct mode; a spoke id for hub mode.
        simulate: True (default) talks to VENUS's simulator, never real hardware.
        deck_name / load_previous_deck: Load a previously saved deck layout instead of
            rebuilding it with add_carrier/add_plate/add_tip_rack every session.
            Mutually exclusive.
        instrument_type: InstrumentType.STAR or InstrumentType.VANTAGE. None (default) uses the
            instrument the spoke's VENUS is installed for; the spoke refuses the other one.
        initialize: Also run instrument initialization (arm homing etc.) -- the
            expensive step (often a minute or more on real hardware) this whole card
            model exists to pay only once, not once per action.
        connect_timeout_s: HTTP/hub-relay timeout for this call, generous by default
            since connect_instrument(initialize=True) can block for a while.
        hold_on_error: Hold a command that fails with a Cancel-answered instrument error
            instead of failing the card, so it can be resumed after recovery (see run()).
            Only sent when True, so an older spoke without stop/resume still works.
        error_profile: The session's error recovery -- "standard", "cancel_all" (every
            error cancelled straight away, which is what hold_on_error needs to hold it),
            or a profile as JSON. None keeps the spoke's configured profile.
        session_name: The name the session runs under in VENUS's run control and run history
            (letters, digits, spaces, "-" and "_"), e.g. the workflow's name, so its runs
            can be told apart. None keeps the spoke's default, "hamilton-venus-mcp". Only sent
            when given, so an older spoke still works.
    """
    session_arguments: dict[str, Any] = {
        "simulate": simulate,
        "deck_name": deck_name,
        "load_previous_deck": load_previous_deck,
        # A card has no person to ask, so say "blank" outright: a spoke given no deck choice
        # asks the user (or refuses to connect until one is made). Older spokes ignore it.
        "blank_deck": deck_name is None and not load_previous_deck,
    }
    if instrument_type is not None:
        session_arguments["instrument_type"] = str(instrument_type)
    if hold_on_error:
        session_arguments["hold_on_error"] = True
    if error_profile is not None:
        session_arguments["error_profile"] = error_profile
    if session_name:
        session_arguments["session_name"] = session_name
    started = _dispatch(
        url,
        spoke_id,
        "start_session",
        session_arguments,
        timeout_s=connect_timeout_s,
    )
    connected = _dispatch(
        url,
        spoke_id,
        "connect_instrument",
        {"initialize": initialize, "expected_connection_id": started.get("connection_id")},
        timeout_s=connect_timeout_s,
    )
    return {**started, **connected}


def run(
    url: str,
    spoke_id: str | None,
    name: str,
    /,
    *,
    expected_connection_id: str | None = None,
    call_timeout_s: float = 60.0,
    recovery: bool = False,
    on_held: Callable[[dict[str, Any]], None] | None = None,
    max_hold_s: float | None = None,
    **kwargs: Any,
) -> Any:
    """"Do X" card body: one SDK command against whatever session is currently open --
    e.g. run(url, spoke_id, "aspirate", positions="Plate1@A1", volumes=100.0,
    liquid_class="..."). Which action a given card performs is just which `name`/kwargs
    that card's own script passes here -- the same function serves every "do X" card.

    Pass expected_connection_id (from start()'s output, or a fresh status() call) to
    fail clearly instead of silently acting on a different workflow's session if it's
    been replaced since. See describe_sdk_command on the spoke, or the SDK's own docs,
    for a given command's arguments.

    Stop / resume: if the spoke holds this step -- stop() was sent, or it failed with a
    Cancel-answered error while hold_on_error is on (see start()) -- this call does not
    return or raise yet. It waits (in bounded await_command_step long polls, so no single
    HTTP/hub-relay call runs long) until someone sends resume() / resume_from() / release_hold(),
    then returns the re-run's result, or raises if it was released or failed for good. So an
    orchestrator loop calling run() simply pauses in place.

    Args:
        recovery: Send as a recovery command (see recovery_call()): it runs even while a
            step is held and is never replayed by resume_from().
        on_held: Called once with the spoke's "held" result when this step is first held,
            e.g. to notify an operator.
        max_hold_s: Stop waiting after this many seconds held and raise
            OrchestratorCallError (the step stays held on the spoke). None waits forever.

    url, spoke_id and name are positional-only, so an SDK argument called "name" (e.g.
    get_liquid_class's) passes straight through in **kwargs. An SDK argument that shares a
    name with one of the options above needs run_command(), which takes them as a dict.
    """
    return run_command(
        url,
        spoke_id,
        name,
        kwargs,
        expected_connection_id=expected_connection_id,
        call_timeout_s=call_timeout_s,
        recovery=recovery,
        on_held=on_held,
        max_hold_s=max_hold_s,
    )


def run_command(
    url: str,
    spoke_id: str | None,
    name: str,
    kwargs: dict[str, Any] | None = None,
    *,
    expected_connection_id: str | None = None,
    call_timeout_s: float = 60.0,
    recovery: bool = False,
    on_held: Callable[[dict[str, Any]], None] | None = None,
    max_hold_s: float | None = None,
) -> Any:
    """run(), with the SDK command's arguments as one dict instead of keywords -- so they can
    never collide with this function's own options. What Instrument's typed methods use."""
    arguments: dict[str, Any] = {
        "name": name,
        "kwargs": dict(kwargs or {}),
        "expected_connection_id": expected_connection_id,
    }
    if recovery:
        arguments["recovery"] = True
    result = _dispatch(url, spoke_id, "call_sdk_command", arguments, timeout_s=call_timeout_s)
    if not _is_held(result):
        return result

    if on_held is not None:
        on_held(result)
    step = result["step"]
    held_since = time.monotonic()
    while _is_held(result):
        if max_hold_s is not None and time.monotonic() - held_since >= max_hold_s:
            raise OrchestratorCallError(
                f"{name}: step {step} still held after {max_hold_s:g} s ({result.get('hold')}); it stays held on the spoke."
            )
        result = _dispatch(
            url,
            spoke_id,
            "await_command_step",
            {"step": step, "wait_s": _HOLD_POLL_S},
            timeout_s=_HOLD_POLL_S + call_timeout_s,
        )
    return result


# Each await_command_step long poll waits at most this long on the spoke (its cap is 25 s).
_HOLD_POLL_S = 20.0


def _is_held(result: Any) -> bool:
    return isinstance(result, dict) and result.get("status") == "held"


def recovery_call(
    url: str,
    spoke_id: str | None,
    name: str,
    /,
    *,
    expected_connection_id: str | None = None,
    call_timeout_s: float = 60.0,
    **kwargs: Any,
) -> Any:
    """Recovery card body: run() with recovery=True -- for door unlock/lock, tip eject,
    tip pickup and the like while a step is held. Runs straight away, whatever the hold
    state, and is never replayed by resume_from(). With Instrument, the same thing is
    instrument.recovery().tip_eject(...) -- the typed SDK method on a recovery handle."""
    return run_command(
        url,
        spoke_id,
        name,
        kwargs,
        expected_connection_id=expected_connection_id,
        call_timeout_s=call_timeout_s,
        recovery=True,
    )


def stop(url: str, spoke_id: str | None = None, *, call_timeout_s: float = 60.0) -> dict[str, Any]:
    """Stop card body: hold the next command the workflow sends, before it runs, without
    aborting VENUS. A command already running finishes first."""
    return _dispatch(url, spoke_id, "stop_commands", {}, timeout_s=call_timeout_s)


def resume(url: str, spoke_id: str | None = None, *, call_timeout_s: float = 600.0) -> dict[str, Any]:
    """Resume card body: re-run the held step; the workflow's waiting run() then gets its
    result and carries on. Returns the spoke's command-hold summary plus "result"."""
    return _dispatch(url, spoke_id, "resume_commands", {}, timeout_s=call_timeout_s)


def resume_from(url: str, spoke_id: str | None, step: int, *, call_timeout_s: float = 600.0) -> dict[str, Any]:
    """Resume From card body: replay the successful steps from *step* up to the held one,
    then re-run the held step (see hold_status()/journal() for step numbers). The timeout
    is generous because every replayed step runs within this one call."""
    return _dispatch(url, spoke_id, "resume_commands_from", {"step": step}, timeout_s=call_timeout_s)


def release_hold(
    url: str, spoke_id: str | None = None, *, message: str | None = None, call_timeout_s: float = 60.0
) -> dict[str, Any]:
    """Give up on the held step: the workflow's waiting run() raises OrchestratorCallError."""
    return _dispatch(url, spoke_id, "release_command_hold", {"message": message}, timeout_s=call_timeout_s)


def hold_status(url: str, spoke_id: str | None = None, *, call_timeout_s: float = 60.0) -> dict[str, Any]:
    """The spoke's stop/resume state: running / stop_requested / held / resuming, the held
    step and why, and the most recent journal entries."""
    return _dispatch(url, spoke_id, "get_command_hold", {}, timeout_s=call_timeout_s)


def wait_for_command_event(
    url: str, spoke_id: str | None = None, *, since_seq: int = 0, wait_s: float = 20.0, call_timeout_s: float = 60.0
) -> dict[str, Any]:
    """Watcher card body: returns as soon as a step is held, a stop is requested, or a hold
    is resumed/released (or after wait_s with no events). Loop on it with
    since_seq=result["next_since_seq"] to be told about every hold the moment it happens:

        seq = 0
        while True:
            update = wait_for_command_event(URL, SPOKE_ID, since_seq=seq)
            seq = update["next_since_seq"]
            for event in update["events"]:
                if event["kind"] == "held":
                    notify_operator(event)   # step, command, reason, message
    """
    return _dispatch(
        url,
        spoke_id,
        "wait_for_command_event",
        {"since_seq": since_seq, "wait_s": wait_s},
        timeout_s=wait_s + call_timeout_s,
    )


def subscribe_command_events(
    url: str, spoke_id: str | None, webhook_url: str, *, kinds: list[str] | None = None, call_timeout_s: float = 60.0
) -> list[dict[str, Any]]:
    """Have the spoke POST every stop/resume event (or only *kinds*, e.g. ["held"]) to
    *webhook_url* as it happens. Returns the spoke's current subscriptions."""
    result = _dispatch(
        url,
        spoke_id,
        "subscribe_command_events",
        {"url": webhook_url, "kinds": kinds},
        timeout_s=call_timeout_s,
    )
    return result["subscriptions"]


def journal(
    url: str, spoke_id: str | None = None, *, since_step: int = 0, call_timeout_s: float = 60.0
) -> list[dict[str, Any]]:
    """This session's numbered steps (and recovery commands) -- for picking resume_from()'s step."""
    return _dispatch(url, spoke_id, "get_command_journal", {"since_step": since_step}, timeout_s=call_timeout_s)


def status(url: str, spoke_id: str | None = None, *, call_timeout_s: float = 60.0) -> dict[str, Any]:
    """Discovery / pre-flight-check card body: whether a session is active and
    connected, and its current connection_id -- the fallback for a card that can't
    receive connection_id from an earlier card's output (see the module docstring)."""
    return _dispatch(url, spoke_id, "get_session_status", {}, timeout_s=call_timeout_s)


def finish(
    url: str,
    spoke_id: str | None = None,
    *,
    expected_connection_id: str | None = None,
    connect_timeout_s: float = 200.0,
) -> None:
    """Finish/Cleanup card body: closes the session, disconnecting the instrument.
    Always run this, even on a workflow failure -- nothing else releases the session."""
    _dispatch(
        url,
        spoke_id,
        "close_session",
        {"expected_connection_id": expected_connection_id},
        timeout_s=connect_timeout_s,
    )

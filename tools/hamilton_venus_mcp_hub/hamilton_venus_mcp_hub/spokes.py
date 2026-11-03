"""Spoke configuration and per-call connection handling.

Each spoke is an unmodified ``hamilton_venus_mcp`` server (see the ``mcp_server`` project)
running on its own PC with ``HAMILTON_MCP_TRANSPORT=streamable-http``, one per physical
instrument.

SpokeGroup opens a fresh, short-lived MCP session for every call rather than holding one
persistent :class:`mcp.ClientSession` open per spoke for the hub's whole lifetime. A
persistent-connection design was tried first and found unsafe by direct testing: killing a
spoke while its connection was held open crashed the *entire hub process* (an unhandled
exception surfaced from the connection's own background reader task, not from any code path
this module controls) -- taking down every other spoke's connection along with it, not just
the dead one. Reconnecting per call trades a few tens of milliseconds of MCP handshake
overhead (negligible on a LAN for this workload -- occasional commands, not a tight polling
loop; polling itself already runs locally on the spoke via poll_sdk_command_until) for
eliminating that whole failure mode: a dead spoke can now only ever fail its own call.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, ListResourcesResult, ReadResourceResult

from hamilton_venus_mcp_hub import spoke_store
from hamilton_venus_mcp_hub.auth import spoke_headers

DEFAULT_SPOKES_ENV_VAR = "HAMILTON_MCP_SPOKES"

# A dead spoke (process killed, network dropped) doesn't necessarily fail promptly -- an
# in-flight connection attempt or request can sit waiting far longer than is useful (observed
# directly: an early version of this call, without a timeout, hung well past two minutes
# against a killed spoke). Every call needs a hub-side ceiling so one offline spoke degrades
# to a fast, reported error instead of hanging whatever's waiting on it (a single
# call_tool_on, or every spoke in a broadcast_tool_call).
DEFAULT_CALL_TIMEOUT_S = 30.0

# Startup reachability probe (see SpokeGroup.connect_all) -- a real spoke tool call with no
# side effects, present on every hamilton_venus_mcp server regardless of instrument type or
# session state.
_HEALTH_CHECK_TOOL = "get_session_status"


@dataclass(frozen=True)
class SpokeConfig:
    id: str
    url: str


def parse_spokes(value: str) -> list[SpokeConfig]:
    """Parse ``id1=url1,id2=url2,...`` (see HAMILTON_MCP_SPOKES) into SpokeConfigs."""
    spokes: list[SpokeConfig] = []
    for raw_entry in value.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"Invalid spoke entry {entry!r}; expected id=url")
        spoke_id, url = (part.strip() for part in entry.split("=", 1))
        if not spoke_id or not url:
            raise ValueError(f"Invalid spoke entry {entry!r}; expected id=url")
        spokes.append(SpokeConfig(id=spoke_id, url=url))

    if not spokes:
        raise ValueError(f"No spokes found in {value!r}; expected id1=url1,id2=url2,...")
    ids = [s.id for s in spokes]
    if len(set(ids)) != len(ids):
        raise ValueError(f"Duplicate spoke id(s) in {value!r}")
    return spokes


def spokes_from_env(var: str = DEFAULT_SPOKES_ENV_VAR) -> list[SpokeConfig]:
    """Parse *var* into SpokeConfigs, or ``[]`` if it is unset/blank -- pre-configuring a spoke
    this way is optional, not required to start the hub: add_spoke/the dashboard's "Add spoke"
    form register one at runtime just as well, and are the intended path for a hub started from
    a plain "start the hub" shortcut/batch file with no spoke PCs known yet."""
    value = os.environ.get(var)
    if not value or not value.strip():
        return []
    return parse_spokes(value)


def _is_unauthorized(exc: BaseException) -> bool:
    """True if *exc* (or anything inside an ExceptionGroup, which is how the MCP client's
    task group reports it) is an HTTP 401 from the spoke."""
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_unauthorized(inner) for inner in exc.exceptions)
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 401


# How many instrument errors / prompts the hub remembers per spoke, newest last.
ERROR_LOG_SIZE = 200
# How many of them go into the state view (the dashboard and /api/status.json).
ERROR_VIEW_SIZE = 20

_ERROR_KINDS = {"command_error": "error", "run_hold": "held", "operator_prompt": "operator_prompt"}


def _error_entry(event: dict[str, Any]) -> dict[str, Any] | None:
    """The part of a spoke event worth keeping as an error record, or None when the event is not
    one (a status change, a resume, a hold that is only a stop). Accepts the event as pushed
    (has "kind") and as listed in the spoke's recent_errors (has only "type")."""
    kind = _ERROR_KINDS.get(str(event.get("type"))) or (
        event.get("kind") if event.get("kind") in ("error", "operator_prompt") else None
    )
    if kind is None and event.get("kind") == "held":
        kind = "held"
    if kind is None or (kind == "held" and event.get("reason") not in (None, "error")):
        return None
    entry: dict[str, Any] = {
        "kind": kind,
        "seq": event.get("seq"),
        "at": event.get("at"),
        "session_id": event.get("session_id"),
        "connection_id": event.get("connection_id"),
        "step": event.get("step"),
        "command": event.get("command"),
        "error_type": event.get("error_type"),
        "message": event.get("message"),
    }
    if kind == "operator_prompt":
        if entry["at"] is None and isinstance(event.get("timestamp"), str):
            try:
                entry["at"] = datetime.fromisoformat(event["timestamp"]).timestamp()
            except ValueError:
                pass
        entry.update(
            command=None,
            error_uuid=event.get("error_uuid"),
            code=event.get("code"),
            message=event.get("title"),
            actions=event.get("top_level_actions"),
        )
    if kind == "held":
        entry["held"] = True
    return entry


@dataclass
class SpokeConnection:
    config: SpokeConfig
    # False for a spoke sourced from HAMILTON_MCP_SPOKES -- never written to spokes.json,
    # so an env-pinned spoke can't silently outlive being removed from the env var (see
    # SpokeGroup._save). True (the default) for everything added at runtime, whether via
    # add_spoke directly or the dashboard's discovery-connect flow, which reuses it.
    persist: bool = True
    connected: bool = False
    last_seen: float | None = None
    last_error: str | None = None
    # The spoke's own get_spoke_state answer, as last polled (see SpokeGroup.record_state).
    state: dict[str, Any] | None = None
    state_checked_at: float | None = None
    state_error: str | None = None
    # When the spoke last pushed an event to this hub (see SpokeGroup.apply_pushed_event).
    last_push_at: float | None = None
    # Instrument errors, holds and operator prompts the spoke reported, newest last. Unlike
    # state (replaced on every poll) this outlives the hold or prompt it describes.
    error_log: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=ERROR_LOG_SIZE))


# What the hub reports for a spoke. The first three come straight from the spoke; "unreachable"
# means it could not be contacted at all; "unknown" means it answered but cannot say (e.g. an
# older spoke without script runs, or a state that has not been polled yet).
STATE_LABELS = ("idle", "running", "error", "unreachable", "unknown")


def state_label(conn: SpokeConnection) -> str:
    if not conn.connected:
        return "unreachable"
    reported = (conn.state or {}).get("state")
    return reported if reported in ("idle", "running", "error") else "unknown"


class SpokeGroup:
    """Tracks configured spokes and their last-known reachability; opens a fresh connection
    for every call_tool (see module docstring for why).
    """

    def __init__(
        self,
        spokes: list[SpokeConfig],
        *,
        spokes_file: Path | None = None,
        env_ids: frozenset[str] = frozenset(),
    ) -> None:
        # Empty is allowed -- a freshly started hub with none pre-configured is the expected
        # state when it was launched from a plain "start the hub" shortcut/batch file rather
        # than with HAMILTON_MCP_SPOKES set; add_spoke (a tool, or the dashboard's "Add spoke"
        # form) is how spokes normally get registered in that case.
        #
        # spokes_file=None (the default) disables persistence entirely -- every existing
        # construction (tests, or any future caller that doesn't care about durability)
        # keeps today's in-memory-only behavior unchanged; only __main__.py's production
        # call opts in. env_ids marks which of *spokes* came from HAMILTON_MCP_SPOKES, so
        # they're tracked like everything else but never written to spokes_file (see _save).
        self._spokes_file = spokes_file
        self._connections: dict[str, SpokeConnection] = {
            s.id: SpokeConnection(config=s, persist=s.id not in env_ids) for s in spokes
        }

    @property
    def ids(self) -> list[str]:
        return list(self._connections)

    async def connect_all(self) -> None:
        """Probe every configured spoke concurrently so the dashboard/status() has real data
        as soon as the hub starts, instead of waiting for the first real tool call. Not a
        precondition for call_tool -- a spoke that fails here can still succeed (or fail) on
        its own later, since every call reconnects independently regardless of this result.
        """
        await asyncio.gather(*(self._probe_one(conn) for conn in self._connections.values()))

    async def _probe_one(self, conn: SpokeConnection) -> None:
        try:
            await self.call_tool(conn.config.id, _HEALTH_CHECK_TOOL, None)
        except Exception:  # noqa: BLE001 - already recorded on the connection by call_tool
            pass

    def url_of(self, spoke_id: str) -> str:
        """The spoke's MCP endpoint URL. Raises ValueError for an unknown spoke_id."""
        return self._get(spoke_id).config.url

    def _get(self, spoke_id: str) -> SpokeConnection:
        try:
            return self._connections[spoke_id]
        except KeyError:
            raise ValueError(f"Unknown spoke_id {spoke_id!r}. Known spokes: {sorted(self._connections)}") from None

    def _save(self) -> None:
        """Write every persist=True spoke to spokes_file, if one was given at construction
        (production only -- see __init__). The single choke point every caller funnels
        through (add_spoke/remove_spoke, called by their MCP-tool wrappers, the dashboard's
        add-spoke form, and discovery-connect, which reuses that same form), so persistence
        happens automatically everywhere with no per-caller special-casing. Failures
        (disk full, permissions) propagate rather than being swallowed -- silently losing
        persistence here would just reintroduce the exact bug this is fixing.
        """
        if self._spokes_file is None:
            return
        spoke_store.save(
            [{"id": c.config.id, "url": c.config.url} for c in self._connections.values() if c.persist],
            self._spokes_file,
        )

    async def add_spoke(self, spoke_id: str, url: str) -> None:
        """Register a new spoke and probe it immediately, without disturbing any other
        spoke's connection. Persisted (see _save) so it survives a hub restart, unless this
        SpokeGroup was constructed with no spokes_file.
        """
        if spoke_id in self._connections:
            raise ValueError(f"Spoke {spoke_id!r} already exists. Remove it first to replace its url.")
        conn = SpokeConnection(config=SpokeConfig(id=spoke_id, url=url))
        self._connections[spoke_id] = conn
        self._save()
        await self._probe_one(conn)

    def remove_spoke(self, spoke_id: str) -> None:
        """Drop a spoke immediately. Persisted (see _save) -- a spoke removed this way
        stays gone across a hub restart unless it's listed in HAMILTON_MCP_SPOKES, which
        always wins over whatever spokes.json has for that id.
        """
        self._get(spoke_id)  # raises ValueError for an unknown id before mutating anything
        del self._connections[spoke_id]
        self._save()

    @staticmethod
    def _failure_message(exc: BaseException, timeout_s: float, spoke_id: str) -> str:
        if isinstance(exc, TimeoutError):
            return f"timed out after {timeout_s}s"
        if _is_unauthorized(exc):
            if spoke_headers(spoke_id):
                return "the spoke rejected the hub's bearer token (HAMILTON_MCP_SPOKE_TOKEN / HAMILTON_MCP_SPOKE_TOKENS)"
            return (
                "the spoke requires a bearer token -- set HAMILTON_MCP_SPOKE_TOKEN (or "
                "HAMILTON_MCP_SPOKE_TOKENS) on the hub to the spoke's HAMILTON_MCP_AUTH_TOKEN"
            )
        return str(exc)

    def _headers_for(self, url: str) -> dict[str, str] | None:
        """The Authorization header for whichever spoke *url* belongs to, if it needs one
        (see auth.spoke_token -- tokens come only from the hub's environment)."""
        spoke_id = next((c.config.id for c in self._connections.values() if c.config.url == url), None)
        return spoke_headers(spoke_id)

    async def _open_and_call(self, url: str, tool_name: str, arguments: dict[str, Any] | None) -> CallToolResult:
        """The actual network round trip -- its own method (rather than inlined in
        call_tool) so tests can patch exactly this seam instead of faking the transport.
        """
        async with streamablehttp_client(url, headers=self._headers_for(url)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool_name, arguments or {})

    async def _open_and_read_resource(self, url: str, uri: str) -> ReadResourceResult:
        """Same per-call connection pattern as _open_and_call, for a resources/read
        instead of a tools/call -- its own method so tests can patch this seam too.
        """
        async with streamablehttp_client(url, headers=self._headers_for(url)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.read_resource(uri)

    async def _open_and_list_resources(self, url: str) -> ListResourcesResult:
        """Same per-call connection pattern as _open_and_call, for a resources/list."""
        async with streamablehttp_client(url, headers=self._headers_for(url)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.list_resources()

    async def call_tool(
        self,
        spoke_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None,
        *,
        timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
    ) -> CallToolResult:
        """Open a fresh connection to the named spoke, call *tool_name* once, and close it.

        Raises if the connection/call fails outright or exceeds timeout_s -- a normal
        tool-level error response (CallToolResult.isError) is returned, not raised, since
        that's a successful round trip that just reports a failure.

        Raise timeout_s above its default for a spoke tool that's meant to run long (e.g.
        poll_sdk_command_until with a large timeout_s of its own) -- give it headroom above
        that tool's own internal timeout so this one doesn't fire first.
        """
        conn = self._get(spoke_id)
        try:
            result = await asyncio.wait_for(
                self._open_and_call(conn.config.url, tool_name, arguments), timeout=timeout_s
            )
        except Exception as exc:
            conn.connected = False
            conn.last_error = self._failure_message(exc, timeout_s, conn.config.id)
            if _is_unauthorized(exc):
                raise PermissionError(conn.last_error) from exc
            raise
        conn.connected = True
        conn.last_seen = time.time()
        conn.last_error = None
        return result

    async def read_resource(
        self,
        spoke_id: str,
        uri: str,
        *,
        timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
    ) -> ReadResourceResult:
        """Open a fresh connection to the named spoke and read one MCP resource by uri --
        same per-call connection and timeout/state-tracking semantics as call_tool (see its
        docstring), just for resources/read instead of tools/call.
        """
        conn = self._get(spoke_id)
        try:
            result = await asyncio.wait_for(self._open_and_read_resource(conn.config.url, uri), timeout=timeout_s)
        except Exception as exc:
            conn.connected = False
            conn.last_error = self._failure_message(exc, timeout_s, conn.config.id)
            if _is_unauthorized(exc):
                raise PermissionError(conn.last_error) from exc
            raise
        conn.connected = True
        conn.last_seen = time.time()
        conn.last_error = None
        return result

    async def list_resources(
        self,
        spoke_id: str,
        *,
        timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
    ) -> ListResourcesResult:
        """Open a fresh connection to the named spoke and list its MCP resources -- same
        per-call connection and timeout/state-tracking semantics as call_tool.
        """
        conn = self._get(spoke_id)
        try:
            result = await asyncio.wait_for(self._open_and_list_resources(conn.config.url), timeout=timeout_s)
        except Exception as exc:
            conn.connected = False
            conn.last_error = self._failure_message(exc, timeout_s, conn.config.id)
            if _is_unauthorized(exc):
                raise PermissionError(conn.last_error) from exc
            raise
        conn.connected = True
        conn.last_seen = time.time()
        conn.last_error = None
        return result

    def record_state(
        self, spoke_id: str, state: dict[str, Any] | None, *, error: str | None = None, checked_at: float | None = None
    ) -> None:
        """Remember what a spoke said about itself (or that it could not say). Only ever stores
        the spoke's own report: the hub adds no state of its own."""
        conn = self._get(spoke_id)
        conn.state = state
        conn.state_error = error
        conn.state_checked_at = checked_at if checked_at is not None else time.time()
        for event in (state or {}).get("recent_errors") or []:
            self._log_error(conn, event)
        for prompt in (state or {}).get("pending_operator_prompts") or []:
            self._log_error(conn, prompt)

    @staticmethod
    def _log_error(conn: SpokeConnection, event: dict[str, Any]) -> None:
        """Remember an error/prompt once, however many times it arrives (pushed, then listed in
        the next poll's recent_errors)."""
        entry = _error_entry(event)
        if entry is None:
            return

        def identity(e: dict[str, Any]) -> tuple[Any, ...]:
            # A prompt is told apart by its uuid: the pushed copy has a seq, the polled one none.
            if e["kind"] == "operator_prompt":
                return (e["kind"], e.get("error_uuid"))
            return (e["kind"], e["seq"], e["at"])

        if any(identity(e) == identity(entry) for e in conn.error_log):
            return
        conn.error_log.append(entry)

    def apply_pushed_event(self, spoke_id: str, event: dict[str, Any]) -> None:
        """Fold an event the spoke POSTed to this hub (see the /api/spoke-events route) into its
        last-known state straight away, ahead of the next poll: a status change replaces the
        status the dashboard shows. Raises ValueError for an unknown spoke_id."""
        conn = self._get(spoke_id)
        conn.connected = True
        conn.last_seen = conn.last_push_at = time.time()
        self._log_error(conn, event)
        if event.get("kind") == "operator_prompt_resolved":
            for entry in conn.error_log:
                if entry.get("error_uuid") == event.get("error_uuid"):
                    entry["resolved_at"] = event.get("at")
                    entry["resolved_action"] = event.get("action")
        if event.get("kind") == "status" and event.get("status"):
            state = dict(conn.state or {})
            state["status"] = {
                "status": event["status"],
                "detail": event.get("detail"),
                "source": event.get("source"),
                "since": event.get("at"),
            }
            conn.state = state

    def error_history(
        self, spoke_id: str, *, since: float | None = None, kind: str | None = None, limit: int = ERROR_LOG_SIZE
    ) -> list[dict[str, Any]]:
        """What the hub remembers of a spoke's instrument errors, holds and operator prompts,
        newest first (the same records as the state view's recent_errors, but all of them).
        *since* keeps only records after that epoch time; *kind* is "error", "held" or
        "operator_prompt". Raises ValueError for an unknown spoke_id."""
        conn = self._get(spoke_id)
        found = [
            dict(e)
            for e in reversed(conn.error_log)
            if (since is None or (e.get("at") or 0) > since) and (kind is None or e["kind"] == kind)
        ]
        return found[: max(0, limit)]

    @staticmethod
    def _state_view(conn: SpokeConnection) -> dict[str, Any]:
        state = conn.state or {}
        pending = state.get("pending_prompts") or []
        return {
            "state": state_label(conn),
            "state_detail": state.get("detail") or conn.state_error,
            "error_kind": state.get("error_kind"),
            "paused": bool(state.get("paused")),
            "run": state.get("run"),
            "last_run": state.get("last_run"),
            "pending_prompt_count": len(pending),
            "session_active": bool(state.get("session_active")),
            "connection_id": state.get("connection_id"),
            # "STAR" or "Vantage": what that spoke's VENUS is installed for (absent on older spokes).
            "instrument_type": state.get("installed_instrument_type"),
            # Stop/resume state of call_sdk_command steps (absent on older spokes).
            "command_control": state.get("command_control"),
            # idle / running / error / hold / paused / terminated, pushed by the spoke as it
            # changes (absent on older spokes).
            "status": state.get("status"),
            "status_pushed_at": conn.last_push_at,
            "operator_ui": state.get("operator_ui"),
            "state_checked_at": conn.state_checked_at,
            # Newest first. What went wrong on the instrument, kept after the spoke has recovered
            # (the spoke's own "last_error" above is only about reaching it).
            "recent_errors": list(reversed(conn.error_log))[:ERROR_VIEW_SIZE],
            # Session operator prompts a command is blocked on (answer: resolve_operator_prompt).
            "session_prompts": state.get("pending_operator_prompts") or [],
        }

    def pending_interventions(self) -> list[dict[str, Any]]:
        """Every prompt currently waiting for a human, across all spokes, from the last poll of
        each. A spoke that has since become unreachable contributes nothing: the hub cannot
        answer for it, and showing a stale prompt as answerable would be worse than hiding it."""
        found: list[dict[str, Any]] = []
        for conn in self._connections.values():
            if not conn.connected or not conn.state:
                continue
            script = (conn.state.get("run") or {}).get("script")
            for prompt in conn.state.get("pending_prompts") or []:
                found.append({"spoke_id": conn.config.id, "script": script, **prompt})
        return found

    def command_holds(self) -> list[dict[str, Any]]:
        """Every spoke whose call_sdk_command stream is held (a step that failed with a Cancel,
        or a stop) and waiting for recovery and resume / resume_from / release, from the last
        poll of each. Kept apart from pending_interventions: there is no prompt to answer here --
        whoever drives the commands recovers and resumes."""
        found: list[dict[str, Any]] = []
        for conn in self._connections.values():
            if not conn.connected or not conn.state:
                continue
            control = conn.state.get("command_control") or {}
            hold = control.get("hold")
            if control.get("state") in ("held", "resuming") and hold:
                found.append(
                    {
                        "spoke_id": conn.config.id,
                        "connection_id": conn.state.get("connection_id"),
                        "state": control.get("state"),
                        **hold,
                    }
                )
        return found

    def status(self) -> list[dict[str, Any]]:
        return [
            {
                "id": conn.config.id,
                "url": conn.config.url,
                "connected": conn.connected,
                "last_seen": conn.last_seen,
                "last_error": conn.last_error,
                **self._state_view(conn),
            }
            for conn in self._connections.values()
        ]

    async def aclose(self) -> None:
        """No persistent connections to release -- kept as a no-op for __main__'s symmetry
        (connect_all()/aclose() bracketing serve()) and in case a future shared resource
        (e.g. a pooled httpx client) needs teardown.
        """

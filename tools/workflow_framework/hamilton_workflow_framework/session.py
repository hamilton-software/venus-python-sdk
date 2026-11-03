"""Owns a single StarClient or VantageClient lifecycle for one WebSocket connection.

Generalized from the hamilton-star-demo-app's original DemoSession -- nothing in
this module is STAR-app-specific; it only touches hamilton_venus-level concepts
(StarClient, VantageClient, OperatorEscalationContext, RecoveryAction, ...). Apps
subclass ``WorkflowSession`` only if they need extra per-app state; the
operator-escalation bridge itself (the trickiest part) works unmodified for any app.

Which client class start_session() constructs is picked by instrument_type (either
passed explicitly per call, or falling back to WorkflowBackendConfig.default_instrument_type)
-- see start_session()'s docstring. The ``star`` property name is kept as-is regardless
of which client is actually active, so every existing ``session.star.<method>()`` call
site across apps keeps working unchanged; only the type hint became a union.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from hamilton_venus import OperatorEscalationContext, RecoveryAction, StarClient, VantageClient
from hamilton_venus.config import RunLogConfig, load_config
from hamilton_venus.error_handling.access_actions import access_action_recovery, access_actions
from hamilton_venus.models import DetailedErrorRecovery, ErrorData, ErrorRecovery, InstrumentType, RecoveryActionDescriptor, RunState
from hamilton_venus.standalone_devices import find_standalone_device

from hamilton_workflow_framework.config import WorkflowBackendConfig
from hamilton_workflow_framework.trace_streamer import TraceStreamer

_logger = logging.getLogger("hamilton_workflow_framework.session")

_KNOWN_RECOVERY_ACTIONS = {a.value for a in RecoveryAction}

# VENUS's own system-wide simulation setting -- read/written directly against the
# local Vector API, same host:port every StarClient/VantageClient in this process
# connects to by default. This is deliberately separate from the `simulate`
# constructor kwarg below: `simulate` only controls how VENUS *executes* a method,
# not which instrument (real or simulated) answers a connect. Ported from
# python_script_manager_app/backend/script_runner.py's `_sync_system_simulation_mode`,
# which found this the hard way -- unchecking a run's simulate toggle kept
# connecting to the simulated device (serial 0000) regardless, because nothing was
# syncing this system-wide setting to match.
_VECTOR_API_BASE = "http://localhost:42400/api/vector/v3"
_VECTOR_API_HEADERS = {"accept": "text/plain; x-api-version=3.0"}

# RunState values meaning VENUS is actively mid-method -- entering (or exiting) a
# StarClient/VantageClient while one of these is active silently aborts it (see
# hamilton_venus._internal._async_instrument_client._cleanup_stale_method/stop).
# check_run_state()/abort_and_clear_run_control() below exist to catch that ahead
# of time instead of letting the SDK do it unannounced.
BUSY_RUN_STATES = frozenset(
    {RunState.RUNNING, RunState.ABORTING, RunState.PAUSING, RunState.PAUSED, RunState.STARTING, RunState.TERMINATING}
)

# Called synchronously, on the SDK's dedicated operator-escalation worker thread,
# before the session blocks waiting for a UI response -- for observers that only
# want to *see* the escalation (e.g. logging it into a monitoring timeline), not
# decide the recovery action. Must not block or raise.
EscalationObserver = Callable[[OperatorEscalationContext], None]


def _response_action(response: object) -> object:
    """What an operator answered, for the resolved-prompt message."""
    if isinstance(response, dict):
        return response.get("action") if response.get("kind") == "action" else response.get("channel_actions")
    return response


def _known_action_names(descriptors: list[RecoveryActionDescriptor]) -> list[str]:
    """Server-advertised action names, filtered to ones the UI can actually submit.

    Descriptors like "Execute" are protocol-internal wrappers the resolver applies
    automatically when submitting per-channel selections -- not something an operator
    picks directly -- so anything that isn't a RecoveryAction value is dropped here.
    """
    names: list[str] = []
    for descriptor in descriptors:
        name = descriptor.name.lower()
        if name in _KNOWN_RECOVERY_ACTIONS and name not in names:
            names.append(name)
    return names


def _channel_rows_with_actions(error: ErrorData) -> list[dict[str, Any]]:
    """Group an error's per-channel details by exact message for the operator
    prompt -- matching python_script_manager_app/backend/script_runner.py's
    ``_channel_rows_with_actions`` (which this was ported from) so both apps
    offer the identical "one dropdown per error type" recovery UI.

    ``error.message`` is frequently just the raw code (e.g. "P1:02/66") -- the
    actual description lives in ``error.title`` (the operation that failed) and,
    for multi-channel errors, in each ``detailed_errors[i].message`` (e.g.
    "Squeezer drive not initialized."). Multiple channels overwhelmingly share
    the exact same message for the exact same error *type* within one event, so
    one error type gets one dropdown covering every channel it affects, not a
    separate dropdown per channel that would just be set identically anyway. A
    channel with a genuinely different message (a different failure kind within
    the same escalation) lands in its own separate group.

    Each group carries the union of its member details' own server-advertised
    recovery-action id/name pairs (not the error-wide RecoveryAction-filtered
    list ``_known_action_names`` produces -- different error types can genuinely
    advertise different options) plus a default: "repeat" if the server
    advertises it for this group (the most commonly-useful blind retry), else
    whichever action id the first detail's own ``default_recovery_action_id``
    names, else no default.
    """
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for detail in error.detailed_errors or []:
        if not detail.message:
            continue
        channel = next((a.value for a in (detail.attributes or []) if a.name == "channel"), None)
        if detail.message not in groups:
            groups[detail.message] = {
                "channels": [],
                "detail_uuids": [],
                "action_ids_seen": set(),
                "actions": [],
                "fallback_default": detail.default_recovery_action_id,
            }
            order.append(detail.message)
        group = groups[detail.message]
        if channel:
            group["channels"].append(channel)
        group["detail_uuids"].append(detail.uuid)
        for a in detail.recovery_actions or []:
            if (a.name or "").lower() == "execute" or a.id in group["action_ids_seen"]:
                continue
            group["action_ids_seen"].add(a.id)
            group["actions"].append({"id": a.id, "name": a.name})

    rows = []
    for message in order:
        group = groups[message]
        repeat_id = next((a["id"] for a in group["actions"] if a["name"].lower() == "repeat"), None)
        default_id = repeat_id if repeat_id is not None else group["fallback_default"]
        rows.append(
            {
                "channels": group["channels"],
                "message": message,
                "detail_uuids": group["detail_uuids"],
                "actions": group["actions"],
                "default_action_id": default_id,
            }
        )
    return rows


def _find_execute_action_id(error: ErrorData) -> int:
    """The numeric id VENUS wants as ``ErrorRecovery.selected_action_id`` whenever
    per-channel selections are being submitted (a fixed protocol-internal wrapper
    meaning "apply the detailed_error_recoveries below", not something an operator
    picks). -1 (matching the SDK's own fallback) if this VENUS version doesn't
    advertise it. Mirrors script_runner.py's ``_find_execute_action_id``.
    """
    for descriptor in error.recovery_actions or []:
        if (descriptor.name or "").lower() == "execute":
            return descriptor.id
    return -1


def _per_detail_action_ids(action_name: str, error: ErrorData) -> dict[str, int] | None:
    """Resolve *action_name* (e.g. "cancel"/"abort") to the server-side action id every one
    of *error*'s ``detailed_errors`` should carry, so it can be submitted as an explicit
    ``ErrorRecovery`` instead of a plain top-level ``RecoveryAction``.

    Cancel/Abort are error-wide, top-level-only concepts -- a single channel can never be
    individually cancelled or aborted, so they are never genuinely present in any one
    channel's *own* ``recovery_actions`` (confirmed against a live VENUS instance: reusing a
    per-channel-specific id, or expecting one to be individually advertised, both fail).
    What a live VENUS instance actually rejects is a per-channel error submitted *without*
    ``detailed_error_recoveries`` at all ("The detailed error recoveries are missing"), which
    is what the SDK's own resolver does for ABORT whenever a top-level id exists
    (``_error_profile_resolver.py::_submit_abort``). So every detail gets the *same*
    top-level action id here -- the operator's one error-wide choice, applied uniformly --
    rather than trying to find (or fabricate) a per-channel-specific one.

    Returns ``None`` (meaning: fall back to the plain top-level ``RecoveryAction`` path) only
    when there are no detailed errors at all, or *action_name* has no server id anywhere on
    this error (nothing to apply).
    """
    if not error.detailed_errors:
        return None

    def _find(actions: list[Any] | None) -> int | None:
        for descriptor in actions or []:
            if (descriptor.name or "").lower() == action_name:
                return descriptor.id
        return None

    top_level_id = _find(error.recovery_actions)
    if top_level_id is None:
        return None
    return {detail.uuid: top_level_id for detail in error.detailed_errors}


def _describe_error(error: ErrorData) -> tuple[str, list[dict[str, Any]]]:
    """Split an error into (title, channel_errors groups) for the operator prompt.

    Falls back to a single actionless group carrying ``error.message`` when there
    are no per-channel details at all (a top-level-only error), same as
    script_runner.py's ``_on_operator_escalation``.
    """
    title = error.title or error.message or error.code or "Unknown instrument error."

    rows = _channel_rows_with_actions(error)
    if not rows and error.message and error.message != error.code:
        rows = [{"channels": [], "message": error.message, "detail_uuids": [], "actions": [], "default_action_id": None}]

    return title, rows


def _summarize_for_log(title: str, channel_errors: list[dict[str, Any]]) -> str:
    if not channel_errors:
        return title
    parts = [
        f"ch{','.join(row['channels'])}: {row['message']}" if row["channels"] else row["message"]
        for row in channel_errors
    ]
    return f"{title} ({'; '.join(parts)})"


def recovery_from_operator_response(
    error: ErrorData,
    response: dict[str, Any] | None,
    log: Callable[[str], None] | None = None,
) -> RecoveryAction | ErrorRecovery | None:
    """Turn an operator's answer to an ``operator_prompt`` into what the SDK's escalation
    callback must return: a plain ``RecoveryAction``, a fully-populated ``ErrorRecovery`` (for
    per-channel selections, or an error-wide action applied to every channel explicitly), or
    ``None`` -- which the SDK treats as ABORT.

    An access action (unlock/lock door, raise/lower load tray -- ``{"kind": "action",
    "action": "<access action key>"}``) is the exception: it comes back as an ``ErrorRecovery``
    with ``selected_action_is_recovery=False``, which the SDK submits without answering the
    error and then invokes the escalation callback again with the republished error.

    *response* is either ``{"kind": "action", "action": "<name>"}`` (one choice applied
    uniformly) or ``{"kind": "channels", "channel_actions": {detail_uuid: action_id}}``
    (independent per-channel picks). Anything missing, empty or unrecognised resolves to
    ``None`` (ABORT), the safe default. *log*, if given, receives a plain-text line for each
    decision so the round trip is visible to whoever is watching.

    Shared by ``WorkflowSession._handle_operator_escalation`` and by the MCP server's script
    runner, so both convert an operator's answer identically.
    """

    def _log(text: str) -> None:
        if log is not None:
            log(text)

    error_uuid = error.uuid

    if response and response.get("kind") == "channels":
        selections = response.get("channel_actions") or {}
        if not selections:
            _log(f"Empty per-channel selection for {error_uuid}; submitting ABORT")
            return None
        now_str = datetime.now(timezone.utc).isoformat()
        detailed_recoveries = [
            DetailedErrorRecovery(date=now_str, uuid=detail_uuid, selected_action_id=int(action_id))
            for detail_uuid, action_id in selections.items()
        ]
        _log(f"Operator applied per-error-type recovery selections for {error_uuid}; handing back to SDK")
        return ErrorRecovery(
            date=now_str,
            uuid=error_uuid,
            selected_action_id=_find_execute_action_id(error),
            selected_action_is_recovery=True,
            detailed_error_recoveries=detailed_recoveries,
        )

    action = response.get("action") if response else None
    if not action:
        _log(f"No operator action chosen for {error_uuid}; submitting ABORT")
        return None
    access_recovery = access_action_recovery(error, action)
    if access_recovery is not None:
        _log(f"Operator requested {action.lower()!r} for {error_uuid}; the error stays open")
        return access_recovery
    try:
        resolved = RecoveryAction(action.lower())
    except ValueError:
        _log(f"Operator chose unrecognized action {action!r} for {error_uuid}; submitting ABORT")
        return None

    # Prefer an explicit per-channel ErrorRecovery over the plain RecoveryAction for a
    # genuinely per-channel escalation -- see _per_detail_action_ids's docstring for why
    # a plain RecoveryAction can leave VENUS's per-channel error state stuck waiting even
    # though the SDK's resolver accepted it. Falls back to the plain RecoveryAction (the
    # SDK's own top-level-vs-per-channel handling) only when there's nothing per-channel
    # to resolve, or *action* has no id anywhere on this error at all.
    per_detail_ids = _per_detail_action_ids(resolved.value, error)
    if per_detail_ids:
        now_str = datetime.now(timezone.utc).isoformat()
        _log(
            f"Operator chose {resolved.value!r} for {error_uuid}; applying to each of "
            f"{len(per_detail_ids)} channel(s) explicitly"
        )
        # Cancel/Abort's own server id goes at the top level too (not the "Execute"
        # wrapper id) -- see _per_detail_action_ids's docstring: this is an error-wide
        # choice, not a set of independent per-channel picks the resolver needs to
        # "execute". Every detail carries the same id, since one channel's uuid is as
        # good as another's for identifying which id to use.
        top_level_id = next(iter(per_detail_ids.values()))
        return ErrorRecovery(
            date=now_str,
            uuid=error_uuid,
            selected_action_id=top_level_id,
            selected_action_is_recovery=True,
            detailed_error_recoveries=[
                DetailedErrorRecovery(date=now_str, uuid=detail_uuid, selected_action_id=action_id)
                for detail_uuid, action_id in per_detail_ids.items()
            ],
        )

    if error.detailed_errors and not per_detail_ids:
        # action has no id anywhere on this error (not even at the top level) -- nothing
        # to apply. Logged in full (not just names) so a recurrence gives enough to
        # diagnose what VENUS actually expects here, rather than guessing further.
        top_level_summary = ", ".join(f"{a.name}:{a.id}" for a in (error.recovery_actions or []))
        _log(
            f"{resolved.value!r} has no id anywhere on error {error_uuid} "
            f"({len(error.detailed_errors)} channel(s)); falling back to the SDK's own "
            f"top-level submission (known to be rejected by VENUS for per-channel errors "
            f"missing detailed_error_recoveries -- see session.py's "
            f"_per_detail_action_ids). Top-level recovery_actions: [{top_level_summary}]; "
            f"per-channel recovery_actions: "
            + "; ".join(
                f"{d.uuid}=[{', '.join(f'{a.name}:{a.id}' for a in (d.recovery_actions or []))}]"
                for d in error.detailed_errors
            )
        )

    _log(f"Operator chose {resolved.value!r} for {error_uuid}; handing back to SDK to submit to VENUS")
    return resolved


LOG_QUEUE_LIMIT = 5000


class _DropOldestQueue(asyncio.Queue):
    """The event queue a UI or an agent drains. Nothing may be draining it (an unattended
    orchestrator never reads events), and it is never closed with the session, so an unbounded
    one grows for as long as the process runs: past the limit the oldest event is dropped."""

    def __init__(self, limit: int = LOG_QUEUE_LIMIT) -> None:
        super().__init__()
        self._limit = limit

    def _put(self, item: Any) -> None:
        if len(self._queue) >= self._limit:
            self._queue.popleft()
            self._unfinished_tasks -= 1
        super()._put(item)


class WorkflowSession:
    """Owns at most one live StarClient/VantageClient at a time, plus its trace streaming."""

    def __init__(
        self,
        backend_config: WorkflowBackendConfig,
        *,
        escalation_observers: list[EscalationObserver] | None = None,
    ) -> None:
        self._backend_config = backend_config
        self._star: StarClient | VantageClient | None = None
        self._simulate: bool = backend_config.default_simulate
        self._session_name: str | None = None
        self._instrument_type: InstrumentType = backend_config.default_instrument_type
        self._instrument_connected: bool = False
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._own_run_guid: str = ""
        self.session_id: str = uuid.uuid4().hex
        self.log_queue: asyncio.Queue[dict] = _DropOldestQueue()
        self._trace_streamer = TraceStreamer(self.log_queue)
        self._escalation_observers = escalation_observers or []
        # Keyed by error uuid. Populated by _handle_operator_escalation (called on the
        # SDK's dedicated operator-escalation worker thread) and resolved by
        # resolve_operator_prompt (called on this session's asyncio loop, in response
        # to a WS message from the UI). concurrent.futures.Future is used rather than
        # asyncio.Future because it is safe to set from a different thread.
        self._pending_operator_prompts: dict[str, concurrent.futures.Future] = {}
        # The operator_prompt message for each pending prompt (same keys), so a spoke can report
        # "blocked on a prompt" without draining log_queue.
        self._pending_prompt_messages: dict[str, dict] = {}
        # Called on this session's loop with each operator_prompt / operator_prompt_resolved
        # message, independent of log_queue (which get_recent_events drains).
        self._prompt_listeners: list[Callable[[dict], None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        # Pure-Python, no-VENUS device clients (HHC, ODTC, ...) -- keyed by their
        # hamilton_venus.standalone_devices.StandaloneDeviceSpec.prefix, lazily
        # constructed by resolve_command_target() on first use and reused for the
        # rest of this session's lifetime (so e.g. an hhc_connect'ed device_id
        # survives across later hhc_get_status calls). Independent of self._star --
        # these need no VENUS session at all.
        self._device_clients: dict[str, object] = {}

    def add_escalation_observer(self, observer: EscalationObserver) -> None:
        """Register an escalation observer after construction -- useful when the
        observer itself needs a reference to this session (e.g.
        monitoring.make_escalation_event_observer(session)), which can't be built
        before the session exists to pass to the constructor.
        """
        self._escalation_observers.append(observer)

    def add_operator_prompt_listener(self, listener: Callable[[dict], None]) -> None:
        """Register a callback for operator prompts. It receives the ``operator_prompt`` message
        when the SDK raises one and an ``operator_prompt_resolved`` message
        (``error_uuid``, ``action``, ``timestamp``) when it is answered or abandoned, always on
        this session's asyncio loop."""
        self._prompt_listeners.append(listener)

    @property
    def pending_operator_prompts(self) -> list[dict]:
        """The operator_prompt messages still waiting for an answer, oldest first."""
        return list(self._pending_prompt_messages.values())

    def _notify_prompt_listeners(self, message: dict) -> None:
        for listener in self._prompt_listeners:
            try:
                listener(message)
            except Exception:
                _logger.exception("Operator prompt listener raised for uuid=%s", message.get("error_uuid"))

    def _resolved_message(self, error_uuid: str, action: object) -> dict:
        return {
            "type": "operator_prompt_resolved",
            "error_uuid": error_uuid,
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @property
    def simulate(self) -> bool:
        return self._simulate

    @property
    def session_name(self) -> str | None:
        """The name the active session runs under in VENUS (run control, run history, log
        file names), or None for the default: the running program's own name."""
        return self._session_name

    @property
    def instrument_type(self) -> InstrumentType:
        """Which instrument the active (or most recently started) session is/was for."""
        return self._instrument_type

    def is_connected(self) -> bool:
        """Whether the instrument itself is connected (not just the VENUS session started).

        A StarClient can be running (see :meth:`start_session`) without the instrument
        being connected yet -- that's the whole point of the deck-selection step.
        """
        return self._instrument_connected

    @property
    def star(self) -> StarClient | VantageClient:
        if self._star is None:
            raise RuntimeError("StarClient is not connected. Call start_session() first.")
        return self._star

    @property
    def connection_id(self) -> str | None:
        """A fresh identifier for the currently open StarClient/VantageClient connection,
        or None if no session is active.

        Unlike self.session_id (fixed for this WorkflowSession object's whole process
        lifetime), this changes every time start_session() builds a new client -- it's
        just the client's own _session_id (already freshly regenerated per instance by
        _base_instrument_client.py, the same field session.py's own run-log-path lookup
        already reaches into below). Lets a caller confirm a later call is still talking
        to the connection a specific start_session() opened, not one a different,
        unrelated start_session() call has since replaced it with -- see
        mcp_server.hamilton_venus_mcp.server's expected_connection_id guard.
        """
        return self._star._session_id if self._star is not None else None  # noqa: SLF001

    def resolve_command_target(self, method_name: str) -> object:
        """The object *method_name* should be called on: a cached standalone
        device client (see :mod:`hamilton_venus.standalone_devices`) for a
        pure-Python, no-VENUS command like ``hhc_connect``/``odtc_get_status``,
        else :attr:`star`.

        Device clients are constructed lazily, on first use, and cached for
        this session's lifetime (see :attr:`_device_clients`) -- unlike
        :attr:`star`, this never requires :meth:`start_session` to have been
        called, since these devices need no VENUS session at all.
        """
        spec = find_standalone_device(method_name)
        if spec is None:
            return self.star
        client = self._device_clients.get(spec.prefix)
        if client is None:
            client = spec.client_cls(simulate=self._simulate)
            self._device_clients[spec.prefix] = client
        return client

    async def start_session(
        self, simulate: bool, instrument_type: InstrumentType | None = None, session_name: str | None = None
    ) -> None:
        """Tear down any existing client and start a fresh one, without connecting
        to the instrument yet.

        auto_connect is disabled so the caller can load a saved deck (via
        :meth:`load_deck`) before finally calling :meth:`connect_instrument`.
        Neither client has an in-place simulate<->real toggle; switching always
        means exit-then-enter a new context.

        instrument_type selects StarClient vs VantageClient. When omitted, falls back
        to whatever this session is already using (initially
        ``backend_config.default_instrument_type``) -- apps that are single-instrument
        for their whole process lifetime (one demo_app build per instrument) never need
        to pass this; callers that want per-session choice (e.g. mcp_server) do.

        session_name names the run in VENUS (the SDK's ``method_display_name``), so sessions
        can be told apart in run control and run history. None keeps the default: the
        running program's name (``hamilton-venus-mcp`` for the MCP server), the same way a
        script's file name names its run.
        """
        await self._teardown()
        self._simulate = simulate
        self._session_name = session_name or None
        if instrument_type is not None:
            self._instrument_type = instrument_type
        self._loop = asyncio.get_running_loop()

        await self._sync_system_simulation_mode(simulate)

        run_log_dir = self._backend_config.run_log_root
        run_log_dir.mkdir(parents=True, exist_ok=True)

        client_cls = StarClient if self._instrument_type == InstrumentType.STAR else VantageClient
        sdk_config = None
        if self._session_name:
            sdk_config = load_config()
            sdk_config.method.method_display_name = self._session_name
        star = client_cls(
            config=sdk_config,
            simulate=simulate,
            auto_connect=False,
            logging_level=logging.INFO,
            venus_trace_logging=True,
            run_log=RunLogConfig(
                enabled=True,
                output_dir=str(run_log_dir),
                console_capture=True,
                include_com_trace=self._backend_config.com_trace_enabled,
            ),
            on_operator_error_escalation=self._handle_operator_escalation,
        )

        self._trace_streamer.attach_logging()
        await asyncio.to_thread(star.__enter__)
        self._star = star
        # Captured so _run_heartbeat can tell "VENUS run-state is RUNNING because
        # my own session is fine" apart from "VENUS run-state is RUNNING again
        # because a DIFFERENT session's method replaced mine after mine was
        # aborted out from under me" -- run-state alone can't distinguish those,
        # since both read identically as RUNNING.
        self._own_run_guid = await self.check_run_guid() or ""

        jsonl_glob = f"run_{star._session_id}_*.jsonl"  # noqa: SLF001 - documented, filename-discovery only
        await self._trace_streamer.start_tailing(run_log_dir, jsonl_glob)

    async def _sync_system_simulation_mode(self, simulate: bool) -> None:
        """Sync VENUS's system-wide simulation mode to match *simulate*.

        Checks first via GET and only PUTs on a mismatch, to avoid toggling
        instrument state on every single session start. Best-effort: any failure
        (httpx unavailable, VENUS unreachable, unexpected response) is logged and
        swallowed rather than blocking session start -- the subsequent
        ``client_cls(simulate=...)`` connect still proceeds either way, just
        possibly against whichever device VENUS's system setting was already on.
        """
        try:
            import httpx
        except Exception as exc:
            self._push_log("WARNING", f"Could not import httpx -- VENUS system-wide simulation mode not synced: {exc}")
            return
        url = f"{_VECTOR_API_BASE}/system/configuration/simulation"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                get_resp = await client.get(url, headers=_VECTOR_API_HEADERS)
                get_resp.raise_for_status()
                current = get_resp.text.strip().strip('"').lower() == "true"
                if current == simulate:
                    self._push_log("INFO", f"VENUS system-wide simulation mode already {current!r} -- matches this session.")
                    return
                put_resp = await client.put(
                    url,
                    headers=_VECTOR_API_HEADERS,
                    params={"simulationMode": str(simulate).lower()},
                )
                put_resp.raise_for_status()
                self._push_log("INFO", f"VENUS system-wide simulation mode changed: {current!r} -> {simulate!r}.")
        except Exception as exc:
            self._push_log("WARNING", f"Could not sync VENUS system-wide simulation mode: {exc}")

    async def check_run_state(self) -> RunState | None:
        """Query VENUS's execution run-state directly over REST, without going
        through any StarClient/VantageClient instance -- entering or exiting one
        is exactly what silently aborts a stale run (see the SDK's
        ``_cleanup_stale_method``/``stop``), so callers use this to check
        *before* that happens, not after.

        Returns None (fail-open: callers should treat this the same as "nothing
        to report") if VENUS is unreachable or the check itself fails for any
        reason -- this must never be the thing that blocks a connect attempt.
        """
        try:
            import httpx
        except Exception as exc:
            self._push_log("WARNING", f"Could not import httpx -- VENUS run-state not checked: {exc}")
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{_VECTOR_API_BASE}/execution/run-state", headers=_VECTOR_API_HEADERS)
                resp.raise_for_status()
                return RunState.from_api_value(int(resp.text.strip().strip('"')))
        except Exception as exc:
            self._push_log("WARNING", f"Could not check VENUS run-state: {exc}")
            return None

    async def check_run_guid(self) -> str | None:
        """Query VENUS's current-run-data directly over REST for the VENUS run
        control GUID of whatever method is currently loaded/running ("" if
        none). Returns None if VENUS is unreachable or the check fails
        (fail-open, same as check_run_state).
        """
        try:
            import httpx
        except Exception as exc:
            self._push_log("WARNING", f"Could not import httpx -- VENUS run GUID not checked: {exc}")
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{_VECTOR_API_BASE}/execution/current-run-data", headers=_VECTOR_API_HEADERS)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            self._push_log("WARNING", f"Could not check VENUS current-run-data: {exc}")
            return None
        return str(data.get("runGuid") or "") if isinstance(data, dict) else ""

    async def owns_current_run(self) -> bool | None:
        """True if VENUS's currently active/busy run is this session's own (the
        one captured in start_session()) -- False if it's a different run (or
        this session never captured one), None if the guid check itself failed
        (fail-open, same as check_run_state/check_run_guid).

        Used to tell a deliberate "Terminate" (disconnecting a session that is
        itself running a method it started) apart from the actual silent-abort
        risk run_control_busy exists to catch -- ending *your own* connection
        is expected to end *your own* run, so that case shouldn't trigger the
        same warning a genuinely different, unrelated busy run should.
        """
        if not self._own_run_guid:
            return False
        current_guid = await self.check_run_guid()
        if current_guid is None:
            return None
        return current_guid == self._own_run_guid

    async def abort_and_clear_run_control(self) -> None:
        """Explicitly abort and unload whatever VENUS is currently running, then
        wait for it to settle.

        Only ever called after the operator has confirmed this via the
        run_control_busy prompt (see routes_ws.py's _confirm_if_run_control_busy)
        -- never unconditionally. Mirrors the sequence the SDK's own
        ``_cleanup_stale_method`` performs internally, except done explicitly
        here (with progress logged to the UI) *before* a StarClient/VantageClient
        is ever entered, so that by the time the SDK does its own stale-method
        check, there's nothing left to silently abort.
        """
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            self._push_log("INFO", "Aborting the instrument's current run...")
            try:
                await client.post(f"{_VECTOR_API_BASE}/execution/abort", headers=_VECTOR_API_HEADERS)
            except Exception as exc:
                self._push_log("WARNING", f"Abort request failed: {exc}")

            deadline = asyncio.get_event_loop().time() + 30.0
            while asyncio.get_event_loop().time() < deadline:
                state = await self.check_run_state()
                if state is None or state not in BUSY_RUN_STATES:
                    break
                await asyncio.sleep(1.0)
            else:
                self._push_log("WARNING", "Timed out waiting for the aborted run to settle -- unloading anyway.")

            self._push_log("INFO", "Unloading the previous method...")
            try:
                await client.post(f"{_VECTOR_API_BASE}/execution/unload-method", headers=_VECTOR_API_HEADERS)
            except Exception as exc:
                self._push_log("WARNING", f"Unload request failed: {exc}")

        self._push_log("INFO", "Instrument is now clear.")

    async def load_deck(self, deck_name: str | None, previous: bool) -> None:
        """Load a saved deck by name, the last-used deck, or leave the deck blank.

        Pass ``deck_name=None, previous=False`` for a blank deck.
        """
        if deck_name is None and not previous:
            return
        await asyncio.to_thread(self.star.deck_load, deck_name, previous=previous)

    async def connect_instrument(self, initialize: bool = False) -> None:
        """Connect the instrument runtime. Must run after :meth:`start_session`."""
        await asyncio.to_thread(self.star.instrument_connect, initialize=initialize)
        self._instrument_connected = True
        self._heartbeat_task = asyncio.create_task(self._run_heartbeat())

    async def _run_heartbeat(self) -> None:
        """Periodically confirm VENUS is still responding, and still running
        *this* session's own method, while connected.

        Addresses the flip side of check_run_state()/abort_and_clear_run_control()
        above: those catch VENUS already being busy *before* we touch it; this
        catches something happening to VENUS/our run *after* we're connected --
        either VENUS itself going away (Run Control crashing), or -- less
        obviously but confirmed to happen in practice -- another app's own
        run_control_busy "Abort" clearing *our* running method to make room for
        its own, which leaves run-state reading RUNNING again throughout (now
        for the other app's method), so run-state alone can't tell the two
        apart. check_run_guid() can: this session's own run GUID is captured
        once in start_session(), and any change (including going empty) means
        our method is no longer the one actually running, regardless of what
        run-state itself reports. Without this, the UI has no way to learn
        either happened and just sits there as if still connected/idle.

        Pushes one "lost" connection_state warning, then stops -- a one-shot
        signal, not a retry loop; the user reconnecting starts a fresh
        heartbeat (and captures a fresh run GUID).
        """
        consecutive_unreachable = 0
        try:
            while True:
                await asyncio.sleep(3.0)
                state = await self.check_run_state()
                if state is None:
                    consecutive_unreachable += 1
                    if consecutive_unreachable < 2:
                        continue
                    self._push_log(
                        "ERROR", "VENUS did not respond to a health check -- the instrument connection may have crashed."
                    )
                    self._push_connection_lost("VENUS did not respond -- the instrument connection may have crashed.")
                    return
                consecutive_unreachable = 0

                if not self._own_run_guid:
                    continue  # nothing captured to compare against (e.g. check_run_guid failed at connect time)
                current_guid = await self.check_run_guid()
                if current_guid is not None and current_guid != self._own_run_guid:
                    self._push_log(
                        "ERROR",
                        "VENUS run control is no longer running this session's method (aborted or replaced by another "
                        "connection) -- this connection is no longer valid.",
                    )
                    self._push_connection_lost(
                        "VENUS run control was aborted or replaced by another connection -- reconnect to resume."
                    )
                    return
        except asyncio.CancelledError:
            pass

    def _push_connection_lost(self, detail: str) -> None:
        self.log_queue.put_nowait(
            {"type": "connection_state", "simulate": self._simulate, "state": "lost", "detail": detail}
        )

    async def close(self) -> None:
        await self._teardown()

    async def _teardown(self) -> None:
        self._instrument_connected = False
        self._own_run_guid = ""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        await self._trace_streamer.stop_tailing()
        self._trace_streamer.detach_logging()
        # Must happen before star.__exit__(): that call blocks in a worker thread and,
        # if an operator prompt is still open, so is the SDK's escalation worker thread
        # waiting on it -- resolving these first (as ABORT) lets both unwind cleanly.
        self._fail_pending_operator_prompts("session torn down")
        if self._star is not None:
            star = self._star
            self._star = None
            try:
                await asyncio.to_thread(star.__exit__, None, None, None)
            except Exception:
                _logger.exception("Error while tearing down StarClient")
        # Standalone device clients (HHC, ODTC, ...) can exist independently of
        # self._star (see resolve_command_target) -- close them unconditionally
        # so a session restart never leaks a stale COM worker subprocess.
        device_clients = list(self._device_clients.values())
        self._device_clients.clear()
        for client in device_clients:
            try:
                await asyncio.to_thread(client.close)
            except Exception:
                _logger.exception("Error while tearing down %s", type(client).__name__)

    def _fail_pending_operator_prompts(self, reason: str) -> None:
        pending = list(self._pending_operator_prompts.items())
        self._pending_operator_prompts.clear()
        self._pending_prompt_messages.clear()
        for error_uuid, future in pending:
            if not future.done():
                text = f"Resolving pending operator prompt as ABORT ({reason}): {error_uuid}"
                _logger.warning(text)
                self._push_log("WARNING", text)
                future.set_result({"kind": "action", "action": RecoveryAction.ABORT.value})

    def push_message_threadsafe(self, message: dict) -> None:
        """Push an arbitrary WS message onto log_queue from any thread (e.g. an
        escalation_observers callback running on the SDK's dedicated
        operator-escalation worker thread -- see monitoring.sample_tracker's
        error-event observer). Safe to call even if the session's loop has
        since closed (the message is silently dropped).
        """
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self.log_queue.put_nowait, message)

    def _push_log(self, level: str, text: str, *, threadsafe: bool = False) -> None:
        """Push a log entry the UI's console pane will render.

        Plain ``logging`` calls in this module are invisible to the UI --
        TraceStreamer only forwards the ``hamilton_venus`` / ``hamilton_venus.traces``
        loggers (see trace_streamer.py), not this module's own logger -- so anything
        the operator needs to see (what was sent to the UI, what came back, what got
        submitted to VENUS) has to go directly through this queue instead.

        Pass ``threadsafe=True`` when calling from the SDK's escalation worker thread
        rather than this session's own asyncio loop.
        """
        entry = {
            "type": "log",
            "source": "backend",
            "level": level,
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if threadsafe:
            loop = self._loop
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(self.log_queue.put_nowait, entry)
        else:
            self.log_queue.put_nowait(entry)

    # -- operator escalation -----------------------------------------------------
    #
    # Registered as StarClient's on_operator_error_escalation callback. It runs
    # synchronously on the SDK's dedicated operator-escalation worker thread (see
    # hamilton_venus._internal._operator_escalation_bridge.OperatorEscalationBridge),
    # not on this session's asyncio loop -- so blocking here is fine, and is the whole
    # point: it holds the instrument's error resolution open until a human responds
    # through the UI, instead of the SDK silently deferring to VENUS's built-in
    # operator dialog, which has no console to appear on in this headless/remote
    # deployment and would otherwise leave both sides waiting forever.

    def _handle_operator_escalation(self, context: OperatorEscalationContext) -> RecoveryAction | ErrorRecovery | None:
        for observer in self._escalation_observers:
            try:
                observer(context)
            except Exception:
                _logger.exception("Escalation observer raised for uuid=%s", context.error.uuid)

        error = context.error
        error_uuid = error.uuid
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._pending_operator_prompts[error_uuid] = future

        loop = self._loop
        if loop is None or loop.is_closed():
            _logger.warning("_handle_operator_escalation: no active event loop for uuid=%s; aborting", error_uuid)
            self._pending_operator_prompts.pop(error_uuid, None)
            return None

        title, channel_errors = _describe_error(error)
        top_level = _known_action_names(context.top_level_actions)
        message = {
            "type": "operator_prompt",
            "error_uuid": error_uuid,
            "code": error.code,
            "title": title,
            "channel_errors": channel_errors,
            "top_level_actions": top_level,
            "access_actions": access_actions(error),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._pending_prompt_messages[error_uuid] = message
        loop.call_soon_threadsafe(self.log_queue.put_nowait, message)
        loop.call_soon_threadsafe(self._notify_prompt_listeners, message)
        self._push_log(
            "WARNING",
            f"Operator action required ({error.code}): {_summarize_for_log(title, channel_errors)} "
            f"[top-level options: {', '.join(top_level) or 'none advertised'}]",
            threadsafe=True,
        )

        try:
            response = future.result()
        finally:
            self._pending_operator_prompts.pop(error_uuid, None)
            self._pending_prompt_messages.pop(error_uuid, None)
            if not loop.is_closed():
                loop.call_soon_threadsafe(
                    self._notify_prompt_listeners, self._resolved_message(error_uuid, _response_action(response))
                )

        # Logged immediately on unblocking (before the SDK resolver has done anything
        # with it) so the round trip is visible even if what happens next -- server-id
        # lookup, the actual submit_error_recovery POST -- is silent or slow.
        self._push_log("WARNING", f"UI responded {response!r} for {error_uuid}; resolving with the SDK now", threadsafe=True)

        return recovery_from_operator_response(
            error, response, lambda text: self._push_log("WARNING", text, threadsafe=True)
        )

    def resolve_operator_prompt(
        self, error_uuid: str, action: str | None, channel_actions: dict[str, int] | None = None
    ) -> bool:
        """Called from the WS dispatch loop when the UI responds to an operator_prompt.

        Exactly one of `action` (one choice applied uniformly -- the always-available
        Abort/Cancel-style buttons) or `channel_actions` (detail_uuid -> chosen server
        action id, independent per-error-group dropdown picks) is expected to be set;
        `channel_actions` wins if both somehow are, since a non-empty per-channel
        selection is the more specific answer -- mirrors script_runner.py's own
        `resolve_operator_prompt`. Both `action` and `channel_actions` are handed back
        to the SDK's escalation callback verbatim (see `_handle_operator_escalation`),
        which submits whichever recovery/abort choice the operator made to VENUS --
        neither "cancel" nor "abort" are ever handled locally/client-side only.

        Returns False if the uuid is unknown or already resolved (e.g. the prompt was
        answered twice, or resolved by session teardown before the UI response arrived).
        """
        future = self._pending_operator_prompts.get(error_uuid)
        if future is None or future.done():
            self._push_log("WARNING", f"operator_prompt_response for unknown/stale uuid={error_uuid}")
            return False
        self._push_log("WARNING", f"WS response received: action={action!r} channel_actions={channel_actions!r} for {error_uuid}")
        if channel_actions:
            future.set_result({"kind": "channels", "channel_actions": channel_actions})
        else:
            future.set_result({"kind": "action", "action": action})
        return True

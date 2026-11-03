"""Generic WebSocket message schemas shared by every workflow app.

Every message is a JSON object with a "type" field. None of the shapes here
mention STAR-specific concepts (tip pools, carriers, plates, ...) -- an app with
its own lookup messages (e.g. demo_app's GetTipPools/TipPools) or tracking
messages (see hamilton_workflow_framework.consumables/.monitoring) defines its
own extra message classes and concatenates them with the tuples below to build
its own ``ClientMessage``/server-message unions, e.g.:

    from hamilton_workflow_framework.ws_protocol import (
        BASE_CLIENT_MESSAGES, StepIn, make_envelope_model,
    )

    ClientMessage = Annotated[
        Union[*BASE_CLIENT_MESSAGES, GetTipPools, GetCarriers, ...],
        Field(discriminator="type"),
    ]
    _ClientEnvelope = make_envelope_model(ClientMessage)

    def parse_client_message(raw: dict) -> ClientMessage:
        return _ClientEnvelope.model_validate({"message": raw}).message
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

# --------------------------------------------------------------------------
# Shared shapes
# --------------------------------------------------------------------------


class StepIn(BaseModel):
    step_id: str
    command_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


def make_envelope_model(message_union: Any) -> type[BaseModel]:
    """Build a one-field pydantic model wrapping *message_union* so it can be
    validated with ``EnvelopeModel.model_validate({"message": raw})``. A plain
    model class can't be defined against a union that isn't known until an app
    concatenates the framework's base message tuple with its own, so this
    builds it dynamically instead.
    """
    return create_model("_ClientEnvelope", message=(message_union, ...))


def parse_message(raw: dict[str, Any], envelope_model: type[BaseModel]) -> Any:
    """Validate an incoming JSON dict against an envelope built by make_envelope_model."""
    return envelope_model.model_validate({"message": raw}).message


# --------------------------------------------------------------------------
# Client -> Server (generic)
# --------------------------------------------------------------------------


class ConnectWithDeck(BaseModel):
    """Starts a StarClient, loads the chosen deck (or none, for a blank deck),
    then connects the instrument. The saved-deck list itself comes from a fast
    local directory listing (see /api/saved-decks), not a live instrument query,
    so there's nothing to pre-start before the user picks an option.
    """

    type: Literal["connect_with_deck"] = "connect_with_deck"
    simulate: bool
    deck: str | None = None
    previous: bool = False


class Disconnect(BaseModel):
    type: Literal["disconnect"] = "disconnect"


class LoadSteps(BaseModel):
    type: Literal["load_steps"] = "load_steps"
    steps: list[StepIn] = Field(default_factory=list)


class Run(BaseModel):
    type: Literal["run"] = "run"


class RunFrom(BaseModel):
    type: Literal["run_from"] = "run_from"
    step_id: str


class Stop(BaseModel):
    type: Literal["stop"] = "stop"


class Pause(BaseModel):
    """Suspend the active run once its in-flight step finishes -- never aborts a
    step that's already running. No-op if nothing is running (see ExecutionEngine.request_pause)."""

    type: Literal["pause"] = "pause"


class Resume(BaseModel):
    """Release a run suspended by Pause. No-op if not currently paused."""

    type: Literal["resume"] = "resume"


class RunImmediate(BaseModel):
    type: Literal["run_immediate"] = "run_immediate"
    command_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class Ping(BaseModel):
    type: Literal["ping"] = "ping"


class OperatorPromptResponse(BaseModel):
    """Reply to a server-pushed `operator_prompt`. Exactly one of `action` (a
    single `ErrorType.error_types.RecoveryAction` value, e.g. "repeat", "abort",
    applied uniformly -- the always-available Abort/Cancel-style buttons -- or the
    ``key`` of one of the prompt's ``access_actions``) or
    `channel_actions` (detail_uuid -> chosen server-side action id, independent
    per-error-group dropdown picks) is expected to be set. Both None means the
    operator dismissed the prompt without a clear choice.
    """

    type: Literal["operator_prompt_response"] = "operator_prompt_response"
    error_uuid: str
    action: str | None = None
    channel_actions: dict[str, int] | None = None


class RunControlBusyResponse(BaseModel):
    """Reply to a server-pushed `run_control_busy` (see that message's docstring).
    `action` is `"abort"` (explicitly abort + unload the existing run, then
    proceed with whatever triggered the check) or `"cancel"` (do nothing --
    leave the existing run untouched and don't proceed).
    """

    type: Literal["run_control_busy_response"] = "run_control_busy_response"
    prompt_id: str
    action: Literal["abort", "cancel"]


BASE_CLIENT_MESSAGES: tuple[type[BaseModel], ...] = (
    ConnectWithDeck,
    Disconnect,
    LoadSteps,
    Run,
    RunFrom,
    Stop,
    Pause,
    Resume,
    RunImmediate,
    Ping,
    OperatorPromptResponse,
    RunControlBusyResponse,
)


# --------------------------------------------------------------------------
# Client -> Server (optional -- a script-editor tab, not every app has one)
# --------------------------------------------------------------------------


class RunScript(BaseModel):
    type: Literal["run_script"] = "run_script"
    source: str


class StopScript(BaseModel):
    type: Literal["stop_script"] = "stop_script"


class GenerateCodeRequest(BaseModel):
    type: Literal["generate_code_request"] = "generate_code_request"
    steps: list[StepIn] | None = None


# --------------------------------------------------------------------------
# Server -> Client (generic; documents the wire shape -- these are constructed
# as plain dicts at the send sites, not instantiated, so apps are free to add
# fields as long as "type" stays a stable discriminator)
# --------------------------------------------------------------------------


class Hello(BaseModel):
    type: Literal["hello"] = "hello"
    session_id: str
    simulate: bool
    connected: bool


class ConnectionState(BaseModel):
    type: Literal["connection_state"] = "connection_state"
    simulate: bool
    # "cancelled": the user picked "Cancel" on a run_control_busy prompt, so the
    # connect/disconnect that triggered it never happened. "lost": the
    # heartbeat (WorkflowSession._run_heartbeat) found VENUS unresponsive after
    # a successful connect -- distinct from a user-initiated "disconnected".
    state: Literal["connecting", "connected", "disconnecting", "disconnected", "error", "cancelled", "lost"]
    detail: str | None = None


class CommandsCatalog(BaseModel):
    type: Literal["commands_catalog"] = "commands_catalog"
    commands: list[dict[str, Any]]


class SerialNumber(BaseModel):
    type: Literal["serial_number"] = "serial_number"
    serial_number: str | None = None


class StepResult(BaseModel):
    type: Literal["step_result"] = "step_result"
    step_id: str
    command_id: str
    status: Literal["running", "success", "error", "skipped"]
    response: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    message: str = ""


class RunState(BaseModel):
    type: Literal["run_state"] = "run_state"
    state: Literal["idle", "running", "pausing", "paused", "stopping", "stopped", "completed"]


class Log(BaseModel):
    type: Literal["log"] = "log"
    source: Literal["console", "http", "signalr", "cmd_comms", "sdk_log", "trace", "backend", "script"]
    level: str | None = None
    text: str
    timestamp: str


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    message: str
    detail: str | None = None


class RecoveryActionChoice(BaseModel):
    """One server-advertised recovery action an operator can pick for a channel
    group -- the numeric ``id`` is what round-trips back in ``channel_actions``
    (a real server-side action id, not a ``RecoveryAction`` the SDK maps for us)."""

    id: int
    name: str


class OperatorPromptChannelError(BaseModel):
    """One error-message group -- every channel that hit the exact same message
    for this escalation shares one dropdown of that group's own server-advertised
    recovery-action choices (id/name pairs), rather than a separate dropdown per
    channel that would usually just be set identically anyway. A channel with a
    genuinely different message (a different failure kind within the same
    escalation) lands in its own separate group.
    """

    channels: list[str] = Field(default_factory=list)
    message: str
    detail_uuids: list[str] = Field(default_factory=list)
    actions: list[RecoveryActionChoice] = Field(default_factory=list)
    default_action_id: int | None = None


class OperatorPromptAccessAction(BaseModel):
    """An instrument access action VENUS currently lists for the error (unlock/lock door,
    raise/lower load tray). The UI answers with ``OperatorPromptResponse(action=key)``; that
    does not resolve the error, so the prompt is pushed again once the action is carried out.
    """

    id: int
    key: str
    label: str


class OperatorPrompt(BaseModel):
    """Pushed when a hardware error has exhausted its automatic recovery actions and
    the SDK has escalated to the registered operator callback (see
    ``WorkflowSession._handle_operator_escalation``). The SDK blocks the instrument's
    error-resolution thread until a matching ``OperatorPromptResponse`` arrives, so
    the UI should surface this immediately and not let it get lost among log lines.

    ``title`` and ``channel_errors`` are kept separate (rather than one flattened
    string) so the UI can render each error-message group as its own row (with its
    own recovery-action dropdown) instead of a run-on paragraph that reads as if
    the whole error were about one channel. ``top_level_actions`` are the always-
    available, uniformly-applied buttons (Abort/Cancel-style) shown alongside the
    per-group dropdowns -- there is deliberately no separate "per_channel_actions"
    field; each group's own ``actions`` already carries whatever that specific
    error type advertises, which can differ between groups. ``access_actions`` are
    shown as extra buttons that leave the prompt open.
    """

    type: Literal["operator_prompt"] = "operator_prompt"
    error_uuid: str
    code: str | None = None
    title: str | None = None
    channel_errors: list[OperatorPromptChannelError] = Field(default_factory=list)
    top_level_actions: list[str] = Field(default_factory=list)
    access_actions: list[OperatorPromptAccessAction] = Field(default_factory=list)
    timestamp: str


class RunControlBusy(BaseModel):
    """Pushed instead of silently proceeding whenever a connect, disconnect, or
    run would otherwise cause the SDK to silently abort a VENUS run already in
    progress (see WorkflowSession.check_run_state/abort_and_clear_run_control --
    the SDK's own StarClient/VantageClient enter/exit does this abort
    unconditionally and without warning if not caught ahead of time here).

    `context` is what triggered the check, so the UI can phrase the prompt
    appropriately ("Connecting will abort it" vs "Disconnecting will abort it"
    vs "Starting this script will abort it"). `state` is the VENUS RunState
    member name (e.g. "Running", "Paused") the instrument was found in.

    The caller blocks awaiting a matching RunControlBusyResponse -- there is no
    server-side timeout/auto-decision, since "do nothing until the operator
    answers" is the only safe default here.
    """

    type: Literal["run_control_busy"] = "run_control_busy"
    prompt_id: str
    context: Literal["connect", "disconnect", "run"]
    state: str


class Pong(BaseModel):
    type: Literal["pong"] = "pong"


BASE_SERVER_MESSAGES: tuple[type[BaseModel], ...] = (
    Hello,
    ConnectionState,
    CommandsCatalog,
    SerialNumber,
    StepResult,
    RunState,
    Log,
    ErrorMessage,
    OperatorPrompt,
    RunControlBusy,
    Pong,
)


# --------------------------------------------------------------------------
# Server -> Client (optional -- a script-editor tab, not every app has one)
# --------------------------------------------------------------------------


class ScriptState(BaseModel):
    type: Literal["script_state"] = "script_state"
    state: Literal["running", "completed", "stopped", "error"]
    detail: str | None = None


class ScriptLine(BaseModel):
    """Emitted once per executed line of a running script, for live highlighting
    in the editor (see an app's script_runner.py's sys.settrace-based line tracer)."""

    type: Literal["script_line"] = "script_line"
    line: int


class GeneratedCode(BaseModel):
    type: Literal["generated_code"] = "generated_code"
    code: str

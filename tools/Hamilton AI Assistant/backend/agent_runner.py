"""The agent: one Claude Agent SDK conversation, streamed to every connected page.

One AgentRunner serves the whole backend (like the Script Manager's ScriptRunner), so a
relaunched window reconnects to the same conversation: it gets a "replay" of every event so
far, then live events. The engine is locked down to the hamilton-venus MCP server's tools
(no shell, files or web), its own config folder, and the Hamilton skills.

People stay in charge of the instrument through two kinds of cards on the page:
- approval cards, once per session: taking control of the live instrument (or of a
  standalone device) waits until the user approves it, and that approval covers the rest of
  the session (tool_policy / hardware_policy). Choosing "live" in start_session's form is the
  same approval;
- form cards: questions the hamilton-venus server asks (MCP elicitation), such as
  start_session's simulation/live and deck layout choice.
Every conversation is also written to an audit file (one JSON line per event); the
Conversations view lists them and reopens one (conversations.py).

The MCP server is the local spoke, a network spoke or a hub (connection.py). Through a hub
each spoke has its own instrument session, so session state and grants are kept per target
spoke ("" for a direct server).
"""

from __future__ import annotations

import asyncio
import getpass
import json
import logging
import os
import re
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny
from hamilton_venus_mcp.hardware_policy import LIVE_SESSION, ONCE, session_status_in, simulated_after

from backend import connection, elicitation_bridge
from backend.auth_methods import INHERITED_CREDENTIALS, AuthError, AuthMethods
from backend import conversations as conversation_store
from backend.config import HAMILTON_SKILLS, BackendConfig
from backend.secret_store import ApiKeyStore, SecretStore
from backend.settings_store import SettingsStore
from backend.tool_policy import ALL_SPOKES, decide, instrument_calls, is_hub_tool, scoped, short_name

_logger = logging.getLogger(__name__)

# Development only: use this PC user's own Claude login instead of an API key (and their
# Claude config folder). Never set on customer installs.
DEV_LOGIN_ENV = "HAMILTON_AI_ASSISTANT_USE_CLAUDE_LOGIN"

SYSTEM_PROMPT = """You are the Hamilton AI Assistant. You help laboratory scientists run a Hamilton \
STAR or Vantage liquid handler through the hamilton-venus tools (the VENUS Python SDK).

- The user decides simulation vs the live instrument and which deck layout to use: never choose \
for them. start_session asks them itself with a form in this app; pass only what they told you.
- Control of the live instrument is approved once per session in the app (by choosing live in \
the start form, or on an approval card); after that, run the session's commands normally. If the \
user denies an approval, do not retry it; ask what they want instead.
- Use the Hamilton skills when they apply: labware and carrier compatibility, liquid handling \
rules, liquid class choice, tip counter setup after adding tip racks, and writing scripts. \
Open a skill's own files (template.py, reference/*.md) with Read, using the skill's base \
directory; there is no shell, and Read works only inside the skills folder.
- Before a sequence of pipetting or transport steps, say briefly what you are about to do. \
After it, report what happened, including any errors and how they were resolved.
- Keep answers short and plain; the user is at the instrument, not reading code.
- The instrument server's own instructions are only a summary: before doing something new \
(deck building, transport, liquid classes, tip counters, scripts, ...), read its full guide \
with get_usage_guide(search=...).
- CO-RE grips are a separate tool, not part of the instrument configuration: \
instrument_get_configuration never lists them (its gripper is the iSWAP / IPG arm device), so \
never conclude from it that the system has none. When the user says the system has CO-RE \
grips, they are fitted but not yet in the layout: check get_transport_tool_ids and add them \
(add_1ml_core_grip for Legacy 1 mL channels, add_qcg for Fluid Motion channels or a Vantage). \
If you don't know whether the system has them, ask.
- After start_session (and the deck choice) call connect_instrument before anything that needs \
the instrument: instrument_get_configuration, deck building, pipetting. Looking things up \
(search_labware, find_liquid_classes, get_registered_tip_types, the guide) needs no connection. \
The deck view appears by itself once the instrument is connected.
- Carrier widths come from search_labware's width_tracks; never assume them.
- The app names each instrument session in VENUS after the conversation's title; only pass \
start_session's session_name when the user asks for a specific name."""

HUB_PROMPT = """

You are connected through a Hamilton MCP hub: each instrument is a spoke. Call list_spokes, and \
ask the user which instrument to use unless they said. Run instrument tools on it with \
call_tool_on(spoke_id, tool_name, arguments); raise call_timeout_s above the default for long \
commands. The hub cannot show the app's forms, so ask simulation or live and the deck layout in \
the chat before start_session, and pass the answers."""

# Told to the assistant (not shown on the page) with the first message after a conversation is
# reopened: the MCP server that held its instrument session ended with the app.
RESUMED_NOTE = (
    "[Note from the app: this conversation was reopened. Any instrument session from before has "
    "been closed; start a new one with start_session before running instrument commands.]\n\n"
)

# Instrument tools that make their spoke the one the user is watching (session pill, deck viewer).
FOCUS_TOOLS = ("start_session", "select_deck_layout", "connect_instrument", "call_sdk_command", "run_script")
# A conversation's title: shown in the app, and (cleaned up) the session's name in VENUS.
TITLE_CHARS = 80
VENUS_NAME_CHARS = 64  # hamilton_venus_mcp.server.SESSION_NAME_MAX
_NOT_IN_VENUS_NAME = re.compile(r"[^A-Za-z0-9_\- ]+")

# What the assistant is doing with each in-flight tool, for the status strip.
_TOOL_ACTIVITY = {
    "start_session": "Starting the session",
    "select_deck_layout": "Loading the deck layout",
    "connect_instrument": "Connecting the instrument",
    "close_session": "Closing the session",
    "run_script": "Starting a script run",
    "get_run_events": "Following the script run",
    "resume_commands": "Resuming held commands",
    "stop_commands": "Stopping commands",
    "venus_abort": "Aborting the VENUS method",
    "venus_pause": "Pausing VENUS",
    "venus_resume": "Resuming VENUS",
}


def venus_session_name(title: str | None) -> str | None:
    """*title* as a VENUS session name: letters, digits, spaces, '-' and '_' only, at most 64."""
    if not title:
        return None
    name = " ".join(_NOT_IN_VENUS_NAME.sub(" ", title).split())[:VENUS_NAME_CHARS].strip()
    return name or None


# What a spoke reports (hamilton_venus_mcp.server.SPOKE_STATUSES).
SPOKE_STATUSES = ("idle", "running", "error", "hold", "paused", "terminated")

MAX_RESULT_CHARS = 4000

elicitation_bridge.install()


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
        else:
            parts.append(json.dumps(item, default=str))
    return "\n".join(parts)


def _json_dict(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _new_session() -> dict[str, Any]:
    return {"simulated": None, "connected": False, "instrument_type": None, "deck_layout": None, "session_name": None}


def _windows_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


class AgentRunner:
    def __init__(
        self,
        config: BackendConfig,
        settings: SettingsStore,
        api_keys: ApiKeyStore,
        tokens: dict[str, SecretStore] | None = None,
        auth: AuthMethods | None = None,
    ) -> None:
        self._config = config
        self._settings = settings
        self._api_keys = api_keys
        self._auth = auth or AuthMethods(api_keys)
        self._tokens = tokens or {}
        self._client: ClaudeSDKClient | None = None
        self._events: list[dict[str, Any]] = []
        self._subscribers: set[Callable[[dict[str, Any]], None]] = set()
        self._turn_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        # Open approval / form cards: card id -> (kind, the future the engine is waiting on).
        self._pending: dict[str, tuple[str, asyncio.Future]] = {}
        # Instrument session per target spoke ("" = the direct server), as far as the tool
        # results tell: simulated (True), live (False) or unknown/none (None); connected once
        # connect_instrument (or select_deck_layout) said so; instrument type and deck layout.
        self._sessions: dict[str, dict[str, Any]] = {}
        # The spoke the user is watching: the one the assistant last worked on.
        self._focus = ""
        self._tool_calls: dict[str, tuple[str, dict[str, Any], bool]] = {}
        # Control the user granted: hardware_policy.LIVE_SESSION (this live session) and
        # "device:<prefix>" entries (standalone devices), until the session or conversation
        # ends -- scoped to a hub spoke as "<grant>@<spoke>" (tool_policy.scoped).
        self._granted: set[str] = set()
        self._audit_path: Path | None = None
        # The engine's own session id (for resuming), and the one to resume on the next connect.
        self._engine_session_id: str | None = None
        self._resume_session_id: str | None = None
        self._resumed_note_pending = False
        # Last script run the assistant started or checked, and the spoke's operator page.
        self._last_run: dict[str, Any] | None = None
        self._operator_ui: str | None = None
        # What the local spoke last pushed (connection.SPOKE_EVENTS_PATH).
        self._spoke_status: dict[str, Any] | None = None
        # The conversation's title, and whether the user gave it ("user") or it came from the
        # first message ("auto"). A user's title always names the VENUS session.
        self._title: str | None = None
        self._title_source: str | None = None
        # Open approval / form cards: card id -> what the user is asked (for the status strip).
        self._card_labels: dict[str, str] = {}
        elicitation_bridge.set_handler(self._answer_form)

    # -- subscribers -------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._turn_task is not None and not self._turn_task.done()

    def subscribe(self, send: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        """Register a page; returns the replay it should render first."""
        self._subscribers.add(send)
        return {"type": "replay", "events": list(self._events), "busy": self.busy}

    def unsubscribe(self, send: Callable[[dict[str, Any]], None]) -> None:
        self._subscribers.discard(send)

    def broadcast(self, event: dict[str, Any]) -> None:
        """Send a live-only event (not part of the conversation) to every page."""
        self._emit(event, keep=False)

    def _emit(self, event: dict[str, Any], *, keep: bool = True) -> None:
        event = {"t": time.time(), **event}
        if keep:
            self._events.append(event)
            self._audit(event)
        for send in list(self._subscribers):
            try:
                send(event)
            except Exception:  # a page that went away; its socket handler unsubscribes it
                _logger.debug("Dropping event for a closed page", exc_info=True)

    # -- audit -------------------------------------------------------------------------

    def _audit(self, event: dict[str, Any]) -> None:
        try:
            if self._audit_path is None:
                folder = self._config.conversations_dir
                folder.mkdir(parents=True, exist_ok=True)
                self._audit_path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4().hex[:6]}.jsonl"
            line = {
                "time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(event["t"])),
                "windows_user": _windows_user(),
                **{k: v for k, v in event.items() if k != "t"},
            }
            with self._audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, default=str) + "\n")
        except OSError:
            _logger.warning("Could not write the conversation audit file", exc_info=True)

    # -- engine setup ------------------------------------------------------------------

    def auth_status(self) -> dict[str, Any]:
        dev_login = os.environ.get(DEV_LOGIN_ENV) == "1"
        method = self._auth.active(self._settings.get())
        state = method.status()
        return {"ready": dev_login or bool(state["ready"]), "dev_login": dev_login, "auth_method": method.id,
                "auth_who": state.get("who"), "auth_problem": state.get("problem")}

    def _prepare_workspace(self) -> None:
        """The engine's working folder holds only the Hamilton skills (project skills)."""
        skills_dir = self._config.workspace_dir / ".claude" / "skills"
        sources = self._config.skill_sources()
        if not sources:
            _logger.warning("No Hamilton skills found next to the SDK; the agent runs without them.")
            return
        for name in HAMILTON_SKILLS:
            source = next((s / name for s in sources if (s / name / "SKILL.md").is_file()), None)
            if source is None:
                _logger.warning("Skill %s not found in %s", name, ", ".join(map(str, sources)))
                continue
            target = skills_dir / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)

    def _options(self) -> ClaudeAgentOptions:
        settings = self._settings.get()
        env: dict[str, str] = {}
        engine_settings: dict[str, Any] = {}
        if os.environ.get(DEV_LOGIN_ENV) != "1":
            engine_auth = self._auth.active(settings).engine_auth(settings)  # AuthError when not signed in
            self._config.engine_home.mkdir(parents=True, exist_ok=True)
            env = {**dict.fromkeys(INHERITED_CREDENTIALS, ""), **engine_auth.env,
                   "CLAUDE_CONFIG_DIR": str(self._config.engine_home)}
            engine_settings = engine_auth.settings
        server_name, server = connection.mcp_server(settings, self._config, self._tokens)
        self._prepare_workspace()
        prompt = SYSTEM_PROMPT + (HUB_PROMPT if settings.get("connection") == "hub" else "")
        return ClaudeAgentOptions(
            system_prompt=prompt,
            # Skill and Read, so the Hamilton skills and their own files (template.py,
            # reference/*.md) can be opened: no shell, web, or files elsewhere. With tools=[] the
            # skills are listed but can't be read. The SDK allows the listed skills by name; any
            # other skill, and a Read outside the skills folder, is refused in _can_use_tool.
            tools=["Skill", "Read"],
            mcp_servers={server_name: server},
            strict_mcp_config=True,
            setting_sources=["project"],
            skills=list(HAMILTON_SKILLS),
            cwd=str(self._config.workspace_dir),
            model=settings.get("model") or None,
            resume=self._resume_session_id,
            can_use_tool=self._can_use_tool,
            include_partial_messages=True,
            env=env,
            settings=json.dumps(engine_settings) if engine_settings else None,
            stderr=lambda line: _logger.debug("[engine] %s", line),
        )

    async def _ensure_client(self) -> ClaudeSDKClient:
        if self._client is None:
            options = self._options()
            client = ClaudeSDKClient(options=options)
            try:
                await client.connect()
            except Exception:
                if options.resume is None:
                    raise
                # The engine's saved session is gone (another PC user, cleared data, ...):
                # carry on with a fresh one; the page still shows the history.
                _logger.warning("Could not resume engine session %s", options.resume, exc_info=True)
                self._resume_session_id = None
                self._emit({"type": "notice", "message": "The assistant could not reload its memory of this "
                            "conversation, so it starts afresh. The history above is for reference."})
                client = ClaudeSDKClient(options=self._options())
                await client.connect()
            self._resume_session_id = None
            self._client = client
        return self._client

    # -- approvals and forms -------------------------------------------------------------

    async def _wait_for_card(self, card_id: str, kind: str, label: str = "") -> Any:
        future = asyncio.get_running_loop().create_future()
        self._pending[card_id] = (kind, future)
        self._card_labels[card_id] = label
        try:
            return await future
        finally:
            self._pending.pop(card_id, None)
            self._card_labels.pop(card_id, None)

    def _skill_file(self, tool_input: dict[str, Any]) -> bool:
        """A Read of a file inside the Hamilton skills folder (a skill's template or reference)."""
        skills_dir = (self._config.workspace_dir / ".claude" / "skills").resolve()
        try:
            path = Path(str(tool_input.get("file_path", ""))).resolve()
        except (OSError, ValueError):
            return False
        return path.is_relative_to(skills_dir) and path.is_file()

    async def _can_use_tool(self, tool_name: str, tool_input: dict[str, Any], context: Any):
        if tool_name == "Read":
            if self._skill_file(tool_input):
                return PermissionResultAllow(updated_input=tool_input)
            reason = "Read is only for the Hamilton skills' own files (their templates and references)."
            self._emit({"type": "tool_refused", "name": "Read", "input": tool_input, "reason": reason})
            return PermissionResultDeny(message=reason)
        simulated = {target: state["simulated"] for target, state in self._sessions.items()}
        decision = decide(tool_name, tool_input, simulated, self._granted)
        name = short_name(tool_name)
        named = self._with_session_name(name, tool_input, is_hub_tool(tool_name))
        if decision.action == "allow":
            return PermissionResultAllow(updated_input=named)
        if decision.action == "refuse":
            self._emit({"type": "tool_refused", "name": name, "input": tool_input, "reason": decision.reason})
            return PermissionResultDeny(message=decision.reason)
        card_id = uuid.uuid4().hex
        self._emit({"type": "approval_request", "id": card_id, "name": name, "input": tool_input,
                    "reason": decision.reason, "grants": decision.grants})
        approved = await self._wait_for_card(card_id, "approval", f"approve {name}") is True
        self._emit({"type": "approval_resolved", "id": card_id, "approved": approved, "by": _windows_user(),
                    "grants": decision.grants})
        if approved:
            if decision.grants != ONCE:
                self._granted.add(decision.grants)
            return PermissionResultAllow(updated_input=named)
        return PermissionResultDeny(message="The user denied this command in the app. Do not retry it; ask what they want instead.")

    async def _answer_form(self, request: dict[str, Any]) -> dict[str, Any]:
        """An MCP form from the hamilton-venus server, shown as a form card."""
        card_id = uuid.uuid4().hex
        self._emit({
            "type": "form_request",
            "id": card_id,
            "server": request.get("mcp_server_name"),
            "message": request.get("message", ""),
            "schema": request.get("requested_schema") or {},
            "property_order": request.get("property_order"),
        })
        question = str(request.get("message") or "").strip().splitlines()
        answer = await self._wait_for_card(card_id, "form", question[0] if question else "answer a question")
        if not isinstance(answer, dict) or answer.get("action") not in ("accept", "decline", "cancel"):
            answer = {"action": "cancel"}
        result = {"action": answer["action"]}
        if answer["action"] == "accept":
            result["content"] = answer.get("content") or {}
            # start_session's opening form asks the session's name: it titles the conversation.
            name = result["content"].get("session_name")
            if isinstance(name, str) and name.strip():
                self.set_title(name, notify=False)
        self._emit({"type": "form_resolved", "id": card_id, "by": _windows_user(), **result})
        return result

    def answer_card(self, card_id: str, value: Any) -> None:
        """The page answered an approval (True/False) or a form ({"action", "content"})."""
        _, future = self._pending.get(card_id, (None, None))
        if future is None or future.done():
            raise RuntimeError("That question was already answered or has expired.")
        future.set_result(value)

    def _cancel_cards(self) -> None:
        for kind, future in list(self._pending.values()):
            if not future.done():
                future.set_result(False if kind == "approval" else {"action": "cancel"})

    # -- conversation ------------------------------------------------------------------

    async def send(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        async with self._lock:
            if self.busy:
                raise RuntimeError("The assistant is still working on the last message. Wait, or press Stop.")
            self._emit({"type": "user_message", "text": text, "by": _windows_user()})
            if self._title is None:
                self.set_title(text.splitlines()[0][:60], source="auto")
            try:
                client = await self._ensure_client()
            except Exception as exc:
                self._emit({"type": "error", "message": str(exc)})
                return
            if self._resumed_note_pending:
                self._resumed_note_pending = False
                text = RESUMED_NOTE + text
            self._turn_task = asyncio.create_task(self._run_turn(client, text))
            self._emit({"type": "busy", "busy": True}, keep=False)

    async def _run_turn(self, client: ClaudeSDKClient, text: str) -> None:
        try:
            await client.query(text)
            async for message in client.receive_response():
                self._handle_message(message)
        except Exception as exc:
            _logger.exception("Agent turn failed")
            self._emit({"type": "error", "message": f"The assistant stopped with an error: {exc}"})
        finally:
            self._emit({"type": "busy", "busy": False}, keep=False)

    def _handle_message(self, message: Any) -> None:
        if isinstance(message, StreamEvent):
            event = message.event
            if event.get("type") == "content_block_delta" and event.get("delta", {}).get("type") == "text_delta":
                self._emit({"type": "text_delta", "text": event["delta"].get("text", "")}, keep=False)
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text:
                    self._emit({"type": "assistant_text", "text": block.text})
                elif isinstance(block, ToolUseBlock):
                    name = short_name(block.name)
                    self._tool_calls[block.id] = (name, block.input, is_hub_tool(block.name))
                    self._emit({"type": "tool_use", "id": block.id, "name": name, "input": block.input})
            if message.error:
                self._emit({"type": "error", "message": f"Model error: {message.error}"})
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    text = _text_of(block.content)
                    self._emit({
                        "type": "tool_result",
                        "id": block.tool_use_id,
                        "is_error": bool(block.is_error),
                        "content": text[:MAX_RESULT_CHARS] + ("…" if len(text) > MAX_RESULT_CHARS else ""),
                    })
                    call = self._tool_calls.pop(block.tool_use_id, None)
                    if call is not None and not block.is_error:
                        self._track_session(call, text)
        elif isinstance(message, ResultMessage):
            self._note_engine_session(message.session_id)
            self._emit({
                "type": "turn_done",
                "is_error": message.is_error,
                "subtype": message.subtype,
                "cost_usd": message.total_cost_usd,
                "duration_ms": message.duration_ms,
            })
        elif isinstance(message, SystemMessage) and message.subtype == "init":
            self._note_engine_session(message.data.get("session_id"))
            servers = message.data.get("mcp_servers") or []
            failed = [s.get("name") for s in servers if s.get("status") != "connected"]
            if failed:
                self._emit({"type": "error", "message": f"The Hamilton MCP server did not start: {', '.join(failed)}"})

    def _note_engine_session(self, session_id: Any) -> None:
        """Remember the engine's session id in the audit file, so the conversation can be resumed."""
        if isinstance(session_id, str) and session_id and session_id != self._engine_session_id:
            self._engine_session_id = session_id
            self._emit({"type": "engine_session", "session_id": session_id})

    def _target_results(
        self, name: str, tool_input: dict[str, Any], hub: bool, result_text: str
    ) -> list[tuple[str, str, dict[str, Any], str]]:
        """(target, instrument tool, its arguments, its result text) for each spoke call a
        successful tool result covers -- one for a direct server, one per spoke via a hub."""
        calls = instrument_calls(name, tool_input, hub)
        if not hub:
            return [(target, inner, arguments, result_text) for target, inner, arguments in calls]
        result = _json_dict(result_text)
        if not calls or result is None:
            return []
        _, inner, arguments = calls[0]
        if name == "call_tool_on":
            payloads = {calls[0][0]: result}
        else:  # broadcast_tool_call: {spoke_id: result}
            payloads = {target: payload for target, payload in result.items() if isinstance(payload, dict)}
        return [
            (target, inner, arguments, json.dumps(payload))
            for target, payload in payloads.items()
            if payload.get("status") != "error"  # the hub's envelope for a failed spoke call
        ]

    def _track_session(self, call: tuple[str, dict[str, Any], bool], result_text: str) -> None:
        """Keep each target's session (simulated/live, connected, instrument, deck layout) up to
        date from successful tool results, for the approval rules, the status panel and the deck
        viewer."""
        name, tool_input, hub = call
        for target, inner, arguments, text in self._target_results(name, tool_input, hub, result_text):
            if target != ALL_SPOKES:
                self._track_target(target, inner, arguments, text)

    def _track_target(self, target: str, tool: str, tool_input: dict[str, Any], text: str) -> None:
        state = self._sessions.setdefault(target, _new_session())
        live_grant = scoped(LIVE_SESSION, target)
        before = (dict(state), live_grant in self._granted, self._focus)
        state["simulated"] = simulated_after(tool, tool_input, text, state["simulated"])
        # A live session that start_session opened is itself the grant: it took either an
        # approved card or the user choosing "live" in start_session's own form.
        if tool == "start_session":
            self._granted.discard(live_grant)
            if state["simulated"] is False:
                self._granted.add(live_grant)
        elif tool == "close_session":
            self._granted.discard(live_grant)
            state.update(instrument_type=None, deck_layout=None, session_name=None)
        if tool in ("start_session", "close_session"):
            state["connected"] = False
        result = _json_dict(text)
        if tool in ("connect_instrument", "select_deck_layout", "start_session") and result is not None:
            if result.get("connected") is True:
                state["connected"] = True
            for key in ("instrument_type", "deck_layout", "session_name"):
                if result.get(key):
                    state[key] = result[key]
        if tool == "get_session_status":
            status = session_status_in(text)
            if status is not None:
                state["connected"] = bool(status.get("instrument_connected"))
                state["instrument_type"] = status.get("instrument_type") or state["instrument_type"]
        if tool in ("run_script", "get_run") and result is not None and result.get("run_id"):
            self._last_run = {"target": target, **{k: result.get(k) for k in ("run_id", "script", "status", "simulate")}}
            operator_ui = result.get("operator_ui")
            if isinstance(operator_ui, dict) and operator_ui.get("url"):
                self._operator_ui = operator_ui["url"]
        if tool in FOCUS_TOOLS:
            self._focus = target
        if before != (state, live_grant in self._granted, self._focus):
            self._emit({"type": "session_state", "target": target, **state,
                        "live_control": live_grant in self._granted, "focus": self._focus})

    def session_view(self) -> dict[str, Any]:
        """The instrument sessions, for the status panel."""
        return {
            "focus": self._focus,
            "sessions": {
                target: {**state, "live_control": scoped(LIVE_SESSION, target) in self._granted}
                for target, state in self._sessions.items()
            },
            "last_run": self._last_run,
            "operator_ui": self._operator_ui,
            "spoke_status": self._spoke_status,
            "conversation_id": self.conversation_id,
            "title": self._title,
            "activity": self.activity(),
        }

    def activity(self) -> str | None:
        """What the conversation is doing right now, in words: waiting for the user, running a
        command, or thinking; None when idle."""
        for label in self._card_labels.values():
            return f"Waiting for you: {label}"
        running = []
        for name, tool_input, hub in self._tool_calls.values():
            for _, inner, arguments in instrument_calls(name, tool_input, hub) or [("", name, tool_input)]:
                if inner in ("call_sdk_command", "poll_sdk_command_until"):
                    command = arguments.get("name") or "a command"
                    running.append(f"Running {command}" if inner == "call_sdk_command" else f"Waiting on {command}")
                elif inner in _TOOL_ACTIVITY:
                    running.append(_TOOL_ACTIVITY[inner])
        if running:
            return running[-1]
        return "The assistant is thinking" if self.busy else None

    # -- title ---------------------------------------------------------------------------

    @property
    def title(self) -> str | None:
        return self._title

    def set_title(self, title: str, *, source: str = "user", notify: bool = True) -> None:
        """Name the conversation. It names the VENUS session from the next start_session on."""
        title = " ".join(str(title).split())[:TITLE_CHARS]
        if not title or (title == self._title and source == self._title_source):
            return
        self._title, self._title_source = title, source
        self._emit({"type": "title", "title": title, "source": source, "by": _windows_user()})
        if notify and source == "user" and any(s.get("simulated") is not None for s in self._sessions.values()):
            self._emit({"type": "notice", "message": "VENUS shows the new title from the next session start."})

    def _with_session_name(self, tool: str, tool_input: dict[str, Any], hub: bool) -> dict[str, Any] | None:
        """start_session's input with the title the user gave the conversation as its VENUS
        session name (pre-filled in start_session's form, where it can still be changed), or None
        to leave the input as it is. A title taken from the first message is not used: a
        sentence makes a poor run name."""
        name = venus_session_name(self._title) if self._title_source == "user" else None
        if name is None:
            return None
        if hub and tool == "call_tool_on" and tool_input.get("tool_name") == "start_session":
            arguments = tool_input.get("arguments") if isinstance(tool_input.get("arguments"), dict) else {}
            return {**tool_input, "arguments": {**arguments, "session_name": name}}
        elif not hub and tool == "start_session":
            return {**tool_input, "session_name": name}
        return None

    def on_spoke_event(self, payload: dict[str, Any]) -> None:
        """A status change the local spoke pushed (idle / running / error / hold / paused /
        terminated); shown live, not part of the conversation."""
        if payload.get("type") != "status" or payload.get("status") not in SPOKE_STATUSES:
            return
        self._spoke_status = {k: payload.get(k) for k in ("status", "detail", "source")}
        self._spoke_status["at"] = time.time()
        self.broadcast({"type": "spoke_status", **self._spoke_status})

    @property
    def conversation_id(self) -> str | None:
        return self._audit_path.stem if self._audit_path is not None else None

    async def stop(self) -> None:
        self._cancel_cards()
        if self._client is not None and self.busy:
            await self._client.interrupt()
            self._emit({"type": "notice", "message": "Stopped."})

    def _reset_state(self) -> None:
        self._events.clear()
        self._audit_path = None
        self._sessions.clear()
        self._focus = ""
        self._tool_calls.clear()
        self._granted.clear()
        self._engine_session_id = self._resume_session_id = None
        self._resumed_note_pending = False
        self._last_run = self._operator_ui = self._spoke_status = None
        self._title = self._title_source = None
        self._card_labels.clear()

    async def new_conversation(self) -> None:
        """End the engine (its MCP server, and with it any open instrument session, goes
        with it) and start over with an empty conversation and a new audit file."""
        async with self._lock:
            await self._close_client()
            self._reset_state()
            self._emit({"type": "reset"}, keep=False)

    async def resume(self, conversation_id: str) -> None:
        """Reopen a past conversation: its events go back on the page, new ones are appended to
        its audit file, and the engine resumes its own session on the next message. Whatever
        instrument session it had is closed (its MCP server ended with it)."""
        async with self._lock:
            if self.busy:
                raise RuntimeError("The assistant is still working. Wait, or press Stop, before opening another conversation.")
            try:
                path = conversation_store.conversation_path(self._config.conversations_dir, conversation_id)
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            events, session_id = conversation_store.load(path)
            await self._close_client()
            self._reset_state()
            self._events.extend(events)
            # Its instrument sessions ended with it: the page shows none (not kept in the audit file).
            for target in {str(e.get("target") or "") for e in events if e.get("type") == "session_state"}:
                self._events.append({"type": "session_state", "target": target, **_new_session(),
                                     "live_control": False, "focus": ""})
            for event in events:
                if event.get("type") == "title" and event.get("title"):
                    self._title, self._title_source = event["title"], event.get("source") or "user"
            self._audit_path = path
            self._engine_session_id = self._resume_session_id = session_id
            self._resumed_note_pending = True
            for send in list(self._subscribers):
                try:
                    send({"type": "replay", "events": list(self._events), "busy": False})
                except Exception:
                    _logger.debug("Dropping replay for a closed page", exc_info=True)
            self._emit({"type": "notice", "message": "Conversation reopened. Its instrument session was closed "
                        "when it ended; ask the assistant to start a new one."})

    async def _close_client(self) -> None:
        self._cancel_cards()
        if self._turn_task is not None and not self._turn_task.done():
            self._turn_task.cancel()
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                _logger.warning("Disconnecting the agent engine failed", exc_info=True)

    async def shutdown(self) -> None:
        await self._close_client()

"""The one place SDK Studio talks to the MCP spoke.

Everything the UI does to the instrument -- connect, run a card, stop, resume, list the SDK's
commands -- goes through a spoke's tools via orchestrator_client, so Studio, the AI Assistant
and scripts all share the same session, command journal and hold-on-error behavior.

By default Studio starts (or reuses) a spoke on 127.0.0.1; a hub or remote spoke URL can be
set instead. The calls are blocking: the routes run them in worker threads.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from orchestrator_client import local_spoke, orchestrator_session as osess

from backend import capabilities as caps

DEFAULT_CALL_TIMEOUT_S = 60.0


class BridgeError(RuntimeError):
    """A spoke call failed; the message is safe to show the user."""


class SpokeBridge:
    def __init__(self, *, spoke_port: int = local_spoke.DEFAULT_PORT, url: str | None = None, spoke_id: str | None = None):
        self._spoke_port = spoke_port
        self._remote_url = url
        self.spoke_id = spoke_id
        self.connection_id: str | None = None
        self.simulate: bool | None = None
        self.instrument_type: str | None = None
        self.instrument_connected = False
        self.capabilities: dict[str, Any] | None = None
        self.serial_number: str | None = None
        self._lock = threading.Lock()

    # -- spoke ---------------------------------------------------------------------------------

    @property
    def url(self) -> str:
        return self._remote_url or local_spoke.local_url(self._spoke_port)

    @property
    def is_local(self) -> bool:
        return self._remote_url is None

    def ensure_spoke(self) -> dict[str, Any]:
        """Start the local spoke if it is not running (a remote URL is assumed to be up)."""
        if not self.is_local:
            return {"running": True, "url": self.url}
        try:
            # The spoke embeds VENUS's COM trace in each session's run log only when told to at start-up.
            return local_spoke.start_local_spoke(self._spoke_port, env={"HAMILTON_MCP_COM_TRACE": "1"})
        except osess.OrchestratorCallError as exc:
            raise BridgeError(str(exc)) from exc

    def _tool(self, name: str, arguments: dict[str, Any] | None = None, *, timeout_s: float = DEFAULT_CALL_TIMEOUT_S) -> Any:
        try:
            return osess._dispatch(self.url, self.spoke_id, name, arguments or {}, timeout_s=timeout_s)  # noqa: SLF001
        except osess.OrchestratorCallError as exc:
            raise BridgeError(str(exc)) from exc

    # -- session -------------------------------------------------------------------------------

    def venus_run_state(self) -> Any:
        """VENUS's current run state, for the "is something already running?" gate: starting a
        session aborts whatever method VENUS is running, including someone else's."""
        return self._tool("get_venus_run_state")

    def status(self) -> dict[str, Any]:
        return self._tool("get_session_status")

    def start_session(
        self,
        *,
        simulate: bool,
        instrument_type: str = "STAR",
        deck_name: str | None = None,
        load_previous_deck: bool = False,
        hold_on_error: bool = True,
    ) -> dict[str, Any]:
        """Open a session on the spoke WITHOUT connecting the instrument. Commands that need the
        instrument fail until connect_instrument runs (from the Connect Instrument card or the
        Connect button); the user decides when."""
        with self._lock:
            self.ensure_spoke()
            arguments: dict[str, Any] = {
                "simulate": simulate,
                "deck_name": deck_name,
                "load_previous_deck": load_previous_deck,
                # Studio asked the user already: say "blank" outright so the spoke never prompts.
                "blank_deck": deck_name is None and not load_previous_deck,
                "instrument_type": str(osess.InstrumentType(instrument_type)),
            }
            if hold_on_error:
                arguments["hold_on_error"] = True
            result = self._tool("start_session", arguments, timeout_s=200.0)
            self.connection_id = result.get("connection_id")
            self.simulate = simulate
            self.instrument_type = str(instrument_type)
            self.instrument_connected = False
            self.capabilities = None
            self.serial_number = None
            return result

    def connect_instrument(self, *, initialize: bool = True) -> dict[str, Any]:
        """Connect the instrument for the open session (optionally initializing it)."""
        if self.connection_id is None:
            raise BridgeError("Start a session first.")
        result = self._tool(
            "connect_instrument",
            {"initialize": initialize, "expected_connection_id": self.connection_id},
            timeout_s=300.0,
        )
        self.instrument_connected = bool(result.get("connected", True))
        if self.instrument_connected:
            self.capabilities = self._read_capabilities()
            self.serial_number = None if self.simulate else self._read_serial_number()
        return result

    def _read_serial_number(self) -> str | None:
        """The connected instrument's serial number (shown beside "Live"); None when it cannot be read."""
        try:
            response = self.run_command("instrument_get_serial_number", {}, recovery=True)
        except Exception:  # noqa: BLE001 - the pill just shows "Live"
            return None
        serial = (caps.return_parameters(response) or {}).get("serialNumber")
        return str(serial).strip() or None if serial else None

    def _read_capabilities(self) -> dict[str, Any] | None:
        """What this instrument has fitted (channels, heads, gripper), so the palette can hide the rest.
        None when it cannot be read; nothing is hidden then."""
        try:
            response = self.run_command("instrument_get_configuration", {}, recovery=True)
        except Exception:  # noqa: BLE001 - the palette just shows everything
            return None
        return caps.from_configuration(caps.return_parameters(response))

    def connect(self, *, connect_instrument: bool = True, initialize: bool = True, **session: Any) -> dict[str, Any]:
        """Start a session and, unless told not to, connect the instrument too."""
        result = self.start_session(**session)
        if connect_instrument:
            result = {**result, **self.connect_instrument(initialize=initialize)}
        return result

    def disconnect(self) -> None:
        with self._lock:
            if self.connection_id is None and self.simulate is None:
                return
            osess.finish(self.url, self.spoke_id, expected_connection_id=self.connection_id)
            self.connection_id = None
            self.simulate = None
            self.instrument_connected = False
            self.capabilities = None
            self.serial_number = None

    # -- catalog -------------------------------------------------------------------------------

    def list_commands(self) -> list[dict[str, Any]]:
        return self._tool("list_sdk_commands")

    def describe_command(self, name: str) -> dict[str, Any]:
        return self._tool("describe_sdk_command", {"name": name})

    # -- commands ------------------------------------------------------------------------------

    def run_command(
        self,
        name: str,
        kwargs: dict[str, Any],
        *,
        recovery: bool = False,
        max_hold_s: float | None = None,
        on_held: Callable[[dict[str, Any]], None] | None = None,
    ) -> Any:
        """One card. Raises BridgeError on a failed command; a held step (hold-on-error) is
        waited on until it is resumed or released."""
        try:
            return osess.run_command(
                self.url,
                self.spoke_id,
                name,
                kwargs,
                expected_connection_id=self.connection_id,
                recovery=recovery,
                max_hold_s=max_hold_s,
                on_held=on_held,
                call_timeout_s=600.0,
            )
        except osess.OrchestratorCallError as exc:
            raise BridgeError(str(exc)) from exc

    def stop(self) -> dict[str, Any]:
        return self._tool("stop_commands")

    def resume(self) -> dict[str, Any]:
        return self._tool("resume_commands", timeout_s=600.0)

    def resume_from(self, step: int) -> dict[str, Any]:
        return self._tool("resume_commands_from", {"step": step}, timeout_s=600.0)

    def import_script(self, name: str, content: str, overwrite: bool = False) -> dict[str, Any]:
        """Store a script in the spoke's script store (validated there, then runnable with run_script)."""
        stem = "".join(c if c.isalnum() or c in " _-." else "_" for c in name.strip()).strip(" .") or "studio_flow"
        file_name = stem if stem.lower().endswith(".py") else f"{stem}.py"
        return self._tool("import_script", {"name": file_name, "content": content, "overwrite": overwrite})

    def spoke_state(self) -> dict[str, Any]:
        return self._tool("get_spoke_state", timeout_s=10.0)

    def resolve_operator_prompt(self, error_uuid: str, action: str | None, channel_actions: dict[str, int] | None = None) -> dict[str, Any]:
        """Answer the operator prompt a command is blocked on (one action for the whole error, or one recovery per channel)."""
        arguments: dict[str, Any] = {"error_uuid": error_uuid}
        if channel_actions:
            arguments["channel_actions"] = channel_actions
        else:
            arguments["action"] = action
        return self._tool("resolve_operator_prompt", arguments)

    def release_hold(self,message: str | None = None) -> dict[str, Any]:
        return self._tool("release_command_hold", {"message": message} if message else {})

    def hold_status(self) -> dict[str, Any]:
        return self._tool("get_command_hold")

    def journal(self, since_step: int = 0) -> list[dict[str, Any]]:
        return osess.journal(self.url, self.spoke_id, since_step=since_step)

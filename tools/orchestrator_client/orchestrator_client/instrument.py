"""Instrument: a typed, object-oriented wrapper over orchestrator_session.run(), so a
card script can write instrument.add_carrier(labware_definition="tip_car_480bc",
left_track=1, labware_id="test") with the exact same keyword arguments the real
StarClient/VantageClient method takes, instead of hand-building a kwargs dict:
run(url, spoke_id, "add_carrier", labware_definition=..., left_track=1, labware_id="test").

Every method on Instrument (see generated_instrument_commands.py's _GeneratedCommands,
mixed in below) is a thin wrapper that calls self.call(name, **kwargs) -- the exact same
dispatch point this class exposes directly as an escape hatch for any command not yet in
the generated set, or if that file is stale relative to a newer SDK. run()/start()/
status()/finish() in orchestrator_session.py remain available too, unchanged, for any
card that prefers the plain function style.

Construct one Instrument per card script (matching the card model: nothing here holds a
connection open across process invocations -- see orchestrator_session.py's own module
docstring). Example:

    instrument = Instrument(URL, SPOKE_ID)
    instrument.start(simulate=True, instrument_type=InstrumentType.STAR)
    instrument.add_carrier(labware_definition="tip_car_480bc", left_track=1, labware_id="test")
    instrument.call("some_not_yet_generated_command", foo=1)   # escape hatch, same as run()
    instrument.finish()

Recovery while a step is held (see orchestrator_session.run's stop / resume notes) uses the
very same typed methods, on a recovery handle:

    recover = instrument.recovery()
    recover.front_cover_unlock()
    recover.tip_eject(channels=CHANNELS, eject_mode="waste")
    recover.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
    instrument.resume()

Stdlib-only, like orchestrator_session.py and generated_instrument_commands.py -- no
hamilton_venus/hamilton_venus_mcp import, so this is safe to run on a thin orchestrator
PC that has neither package installed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import local_spoke, orchestrator_session
from .generated_instrument_commands import _GeneratedCommands
from .orchestrator_session import InstrumentType


class Instrument(_GeneratedCommands):
    def __init__(
        self,
        url: str,
        spoke_id: str | None = None,
        *,
        connection_id: str | None = None,
        call_timeout_s: float = 60.0,
        on_held: Callable[[dict[str, Any]], None] | None = None,
        max_hold_s: float | None = None,
        token: str | None = None,
    ) -> None:
        # The spoke's (or hub's) HAMILTON_MCP_AUTH_TOKEN, sent as a bearer token on every call
        # to this URL. None falls back to the HAMILTON_MCP_AUTH_TOKEN environment variable.
        if token:
            orchestrator_session.set_auth_token(url, token)
        self.url = url
        self.spoke_id = spoke_id
        self.connection_id = connection_id
        self.call_timeout_s = call_timeout_s
        # Passed to every command (see orchestrator_session.run): notify when one is held,
        # and how long to wait for it before giving up (None: until resumed or released).
        self.on_held = on_held
        self.max_hold_s = max_hold_s
        self._recovery = False

    def call(self, name: str, /, **kwargs: Any) -> Any:
        """Escape hatch -- call any SDK command by name, exactly like
        orchestrator_session.run(). Every generated method is a thin wrapper around this
        same call. The SDK arguments travel as one dict (run_command), so none of them --
        "name" included -- can collide with the call's own options. On a recovery handle
        (see recovery()) it is sent as a recovery command."""
        return orchestrator_session.run_command(
            self.url,
            self.spoke_id,
            name,
            kwargs,
            expected_connection_id=self.connection_id,
            call_timeout_s=self.call_timeout_s,
            recovery=self._recovery,
            on_held=self.on_held,
            max_hold_s=self.max_hold_s,
        )

    @classmethod
    def local(
        cls,
        port: int = local_spoke.DEFAULT_PORT,
        *,
        exe: Any = None,
        token: str | None = None,
        env: dict[str, str] | None = None,
        startup_timeout_s: float = 60.0,
        **instrument_kwargs: Any,
    ) -> Instrument:
        """An Instrument for a spoke on this same PC (127.0.0.1:*port*), starting that spoke
        in the background first if it isn't running -- for an orchestrator that runs on the
        instrument PC. Every card can call this: the first one starts the spoke, later ones
        find it running. Nothing on the network can reach it. See local_spoke.py.

            instrument = Instrument.local()
            instrument.start(simulate=True, instrument_type=InstrumentType.VANTAGE, load_previous_deck=True)

        Args:
            port: Local port (default 8000).
            exe / token / env / startup_timeout_s: See local_spoke.start_local_spoke.
            **instrument_kwargs: Passed to Instrument (connection_id, call_timeout_s,
                on_held, max_hold_s).
        """
        local_spoke.start_local_spoke(port, exe=exe, token=token, env=env, startup_timeout_s=startup_timeout_s)
        return cls(local_spoke.local_url(port), None, token=token, **instrument_kwargs)

    @staticmethod
    def local_status(port: int = local_spoke.DEFAULT_PORT) -> dict[str, Any]:
        """Is a local spoke running? (pid, url, uptime, ...) -- never starts one."""
        return local_spoke.local_spoke_status(port)

    @staticmethod
    def local_health(port: int = local_spoke.DEFAULT_PORT, **kwargs: Any) -> dict[str, Any]:
        """Health of the local spoke: process, /ping, MCP round trip, VENUS reachability."""
        return local_spoke.local_spoke_health(port, **kwargs)

    @staticmethod
    def stop_local(port: int = local_spoke.DEFAULT_PORT, **kwargs: Any) -> dict[str, Any]:
        """Stop the local spoke, closing any open session first (see stop_local_spoke)."""
        return local_spoke.stop_local_spoke(port, **kwargs)

    def recovery(self) -> Instrument:
        """A recovery handle: the same Instrument -- same typed SDK methods, same spoke,
        session and timeouts -- except that every command on it is sent as a recovery
        command, which runs while a step is held and is never replayed by resume_from():

            recover = instrument.recovery()
            recover.front_cover_unlock()
            recover.tip_eject(channels=CHANNELS, eject_mode="waste")

        It also works as a block, where this instrument's own calls are recovery commands
        too until the block ends:

            with instrument.recovery():
                instrument.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
        """
        return _RecoveryInstrument(self)

    def stop(self) -> dict[str, Any]:
        return orchestrator_session.stop(self.url, self.spoke_id, call_timeout_s=self.call_timeout_s)

    def resume(self, *, call_timeout_s: float = 600.0) -> dict[str, Any]:
        """Re-run the held step; the workflow's waiting call then gets its result.

        Args:
            call_timeout_s: The re-run happens within this call, so allow for it.
        """
        return orchestrator_session.resume(self.url, self.spoke_id, call_timeout_s=call_timeout_s)

    def resume_from(self, step: int, *, call_timeout_s: float = 600.0) -> dict[str, Any]:
        """Replay the successful steps from *step* up to the held one, then re-run it.

        Args:
            step: First step to replay (see journal()).
            call_timeout_s: Every replayed step runs within this call, so allow for them all.
        """
        return orchestrator_session.resume_from(self.url, self.spoke_id, step, call_timeout_s=call_timeout_s)

    def release_hold(self, message: str | None = None) -> dict[str, Any]:
        return orchestrator_session.release_hold(
            self.url, self.spoke_id, message=message, call_timeout_s=self.call_timeout_s
        )

    def hold_status(self) -> dict[str, Any]:
        return orchestrator_session.hold_status(self.url, self.spoke_id, call_timeout_s=self.call_timeout_s)

    def journal(self, since_step: int = 0) -> list[dict[str, Any]]:
        return orchestrator_session.journal(
            self.url, self.spoke_id, since_step=since_step, call_timeout_s=self.call_timeout_s
        )

    def start(
        self,
        *,
        simulate: bool = True,
        instrument_type: InstrumentType | None = None,
        deck_name: str | None = None,
        load_previous_deck: bool = False,
        initialize: bool = True,
        hold_on_error: bool = False,
        error_profile: str | None = None,
        session_name: str | None = None,
        connect_timeout_s: float = 200.0,
    ) -> dict[str, Any]:
        """Open a session on the spoke and connect the instrument (replacing any session
        already open there). self.connection_id is updated from the result, so later calls
        on this same Instrument refuse to act on a different workflow's session.

        Args:
            simulate: Use VENUS's simulator (default). False drives the real instrument.
            instrument_type: InstrumentType.STAR or InstrumentType.VANTAGE. Leave it out to use
                the instrument the spoke's VENUS is installed for; the spoke refuses the other one.
            deck_name: Load this saved deck layout. Mutually exclusive with load_previous_deck.
            load_previous_deck: Load the deck layout VENUS last had open.
                With neither, the deck starts empty.
            initialize: Also initialize the instrument (arm homing etc.) while connecting.
            hold_on_error: Hold a step that fails with a Cancel-answered error instead of
                failing it, so it can be recovered and resumed (see stop() / resume()).
            error_profile: The session's error recovery: "standard" (retry, then the
                operator prompt), "cancel_all" (every error cancelled straight away -- what
                hold_on_error needs), or a full profile as JSON. None keeps the spoke's own.
            session_name: The name the session runs under in VENUS's run control and run
                history, e.g. the workflow's name. None keeps "hamilton-venus-mcp".
            connect_timeout_s: Timeout for starting and connecting; initialization can take
                a minute or more on real hardware.

        Returns:
            The spoke's answer: session_id, connection_id, simulate, instrument_type,
            session_name, hold_on_error, error_profile and connected.
        """
        result = orchestrator_session.start(
            self.url,
            self.spoke_id,
            simulate=simulate,
            deck_name=deck_name,
            load_previous_deck=load_previous_deck,
            instrument_type=instrument_type,
            initialize=initialize,
            connect_timeout_s=connect_timeout_s,
            hold_on_error=hold_on_error,
            error_profile=error_profile,
            session_name=session_name,
        )
        self.connection_id = result.get("connection_id")
        return result

    def status(self, *, call_timeout_s: float = 60.0) -> dict[str, Any]:
        """Whether a session is open on the spoke: session_active, instrument_connected,
        simulate, session_id, connection_id and instrument_type."""
        return orchestrator_session.status(self.url, self.spoke_id, call_timeout_s=call_timeout_s)

    def finish(self, *, connect_timeout_s: float = 200.0) -> None:
        """Close the session (refusing if a different one than this Instrument's is open),
        ending the VENUS method and disconnecting the instrument.

        Args:
            connect_timeout_s: Timeout for closing; it can take a while on real hardware.
        """
        orchestrator_session.finish(
            self.url, self.spoke_id, expected_connection_id=self.connection_id, connect_timeout_s=connect_timeout_s
        )


class _RecoveryInstrument(Instrument):
    """What Instrument.recovery() returns -- see there."""

    def __init__(self, parent: Instrument) -> None:
        super().__init__(
            parent.url,
            parent.spoke_id,
            connection_id=parent.connection_id,
            call_timeout_s=parent.call_timeout_s,
            on_held=parent.on_held,
            max_hold_s=parent.max_hold_s,
        )
        self._recovery = True
        self._parent = parent
        self._parent_was_recovery = parent._recovery

    def __enter__(self) -> _RecoveryInstrument:
        self._parent_was_recovery = self._parent._recovery
        self._parent._recovery = True
        return self

    def __exit__(self, *exc: object) -> None:
        self._parent._recovery = self._parent_was_recovery

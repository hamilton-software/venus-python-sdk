"""_AsyncInstrumentClient — internal async client for Hamilton instruments."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractContextManager
from typing import Any, TextIO

from hamilton_venus._internal._asyncio_compat import _wait_with_timeout
from hamilton_venus._internal._auth import _AccessTokenProvider
from hamilton_venus._internal._error_classifier import ErrorClassifier
from hamilton_venus._internal._error_profile_resolver import ErrorProfileResolver, OperatorEscalationCallback
from hamilton_venus._internal._liquid_class_sync import _LiquidClassSync, liquid_class_names_in
from hamilton_venus._internal._method_file_manager import MethodFileManager
from hamilton_venus._internal._run_log import RunLog
from hamilton_venus._internal._sdk_paths import get_sdk_executor_hsl_path, get_sdk_liquid_class_path
from hamilton_venus._internal._signalr_listener import _SignalRListener
from hamilton_venus.config import RunLogConfig, SdkConfig, load_config
from hamilton_venus.error_handling import STANDARD_PROFILE
from hamilton_venus.error_handling.profile import ErrorProfile
from hamilton_venus.exceptions import (
    MethodError,
    VenusAuthenticationError,
    VenusCommandAbortedError,
    VenusTimeoutError,
)
from hamilton_venus.models import (
    CommandResponse,
    ConnectionState,
    ErrorData,
    ExecutorEvent,
    InstrumentErrorHandled,
    InstrumentType,
    ProgressChangedEvent,
    RunState,
    RuntimeStatusEvent,
)
from hamilton_venus.venus_client import VenusClient

_logger = logging.getLogger(__name__)
_trace_logger = logging.getLogger("hamilton_venus.traces")

_AUTH_MODE_NONE = "none"

# Static error handler key to prevent orphaned handlers if script crashes.
# This key persists across client instances so users can always identify and
# recover handlers even if the SDK client wasn't properly cleaned up.
_ERROR_HANDLER_KEY = "hamiltonvenussdk"

#: Run-message channels cleared before the executor method starts: what an earlier run
#: may have left that the new run could mistake for its own (see _reset_run_message_channels).
_STALE_RUN_MESSAGE_CHANNELS = ("ready", "action", "action-response")

_FAILURE_EVENTS: dict[ExecutorEvent, ExecutorEvent] = {
    ExecutorEvent.INITIALIZED: ExecutorEvent.INITIALIZE_FAILED,
}


class _AsyncInstrumentClient:
    """Internal async client for Hamilton instruments.

    Combines :class:`VenusClient` (REST) and :class:`_SignalRListener` (events)
    into a single interface for connection orchestration and command execution.

    .. warning::
        This is an internal implementation detail used by the synchronous clients
        (:class:`~hamilton_venus.StarClient`, :class:`~hamilton_venus.VantageClient`).
        Use those clients directly unless you specifically need async/await
        support and understand the implications.

    Parameters
    ----------
    config:
        SDK configuration. When *None*, :func:`load_config` is called to
        resolve configuration from the environment or defaults.
    simulate:
        When *True*, the instrument method is loaded in simulation mode.
        Defaults to *False*.
    venus_trace_logging:
        When *True*, Venus runtime trace messages received via SignalR are
        printed to stderr regardless of the application's logging
        configuration. Defaults to *False*.
    """

    def __init__(
        self,
        config: SdkConfig | None = None,
        *,
        simulate: bool = False,
        venus_trace_logging: bool = False,
        run_log: RunLog | None = None,
        run_log_config: RunLogConfig | None = None,
        error_profile: ErrorProfile | None = None,
        on_operator_error_escalation: OperatorEscalationCallback | None = None,
        instrument_type: InstrumentType = InstrumentType.STAR,
    ) -> None:
        self._config = config or load_config()
        self._simulate = simulate
        self._venus_trace_logging = venus_trace_logging
        self._instrument_type = instrument_type
        self._auth_provider = self._build_auth_provider()
        tls_verify: bool | str = self._config.tls.verify
        self._venus = VenusClient(
            base_url=self._config.base_url,
            timeout=self._config.timeouts.http,
            max_retries=self._config.network.max_retries,
            retry_backoff=self._config.network.retry_backoff,
            command_timeout=self._config.timeouts.command,
            auth_provider=None,
            verify=tls_verify,
        )
        self._listener = _SignalRListener(
            base_url=self._config.base_url,
        )
        # The method does not import liquid classes itself; custom ones a command uses
        # are pushed first (once per session, and again after their JSON changes).
        self._liquid_class_sync = _LiquidClassSync(
            get_sdk_liquid_class_path(),
            instrument_type.value.upper(),
            self._push_liquid_classes,
        )

        # Wire run log to sub-components
        self._run_log = run_log
        if run_log is not None:
            rl_config = run_log_config or self._config.run_log
            self._venus.set_run_log(run_log)
            self._venus.set_run_log_config(rl_config)
            self._venus._command_dispatcher.set_run_log(run_log)
            self._venus._command_dispatcher.set_run_log_config(rl_config)
            self._listener.set_run_log(run_log)
            self._listener.set_run_log_config(rl_config)

        self._status_event = asyncio.Event()
        self._seen_events: dict[ExecutorEvent, RuntimeStatusEvent] = {}
        self._method_file_manager = MethodFileManager()
        # Stable across start/stop cycles — the same key is reused so
        # VENUS always identifies this client instance as the registered handler.
        self._error_handler_key: str = _ERROR_HANDLER_KEY
        self._error_handler_registered = False

        dispatcher = self._venus._command_dispatcher
        self._error_resolver: ErrorProfileResolver = ErrorProfileResolver(
            venus_client=self._venus,
            deadline_control=dispatcher,
            profile=error_profile if error_profile is not None else STANDARD_PROFILE,
            classifier=ErrorClassifier(),
            error_handler_key=self._error_handler_key,
            on_operator_error_escalation=on_operator_error_escalation,
        )
        _logger.info(
            "_AsyncInstrumentClient init: operator escalation callback provided=%s",
            on_operator_error_escalation is not None,
        )

        # Wire SignalR events to internal handlers
        # so send_command can wait for queue events via SignalR.
        self._listener.on_runtime_status(self._on_runtime_status)
        self._listener.on_progress(self._on_progress)
        self._listener.on_run_message_queued(self._venus.notify_run_message_queued)
        self._listener.on_instrument_error(self._on_instrument_error)
        self._listener.on_instrument_error_notification(self._on_instrument_error_notification)
        self._listener.on_device_error_handled(self._on_device_error_handled)

        self._trace_handler: logging.StreamHandler[TextIO] | None = None
        if venus_trace_logging:
            self._trace_handler = logging.StreamHandler()
            self._trace_handler.setLevel(logging.INFO)
            self._trace_handler.setFormatter(logging.Formatter("%(message)s"))
            _trace_logger.addHandler(self._trace_handler)
            _trace_logger.setLevel(logging.INFO)
            _trace_logger.propagate = False
            self._listener.on_runtime_trace(self._on_runtime_trace)

    def _build_auth_provider(self) -> _AccessTokenProvider | None:
        # Build auth provider only if credentials are available
        try:
            self._config.auth.validate_credentials()
            return _AccessTokenProvider(
                self._config.auth,
                timeout=self._config.timeouts.http,
                verify=self._config.tls.verify,
            )
        except ValueError:
            # Credentials not available yet; will be checked if auth is needed
            return None

    def _apply_auth_provider(self) -> None:
        self._venus._auth_provider = self._auth_provider

    async def _ensure_auth_provider_configured(self) -> None:
        # Probe auth mode without any auth headers attached.
        # VenusClient is always initialized with auth_provider=None, so no save/restore needed.
        authentication_mode = await self._venus.get_authentication_mode()
        normalized_mode = authentication_mode.strip().lower()

        if normalized_mode == _AUTH_MODE_NONE:
            _logger.info(
                "VENUS authentication mode is %s; continuing without authenticated transport",
                authentication_mode,
            )
            return

        _logger.info(
            "VENUS authentication mode is %s; enabling authenticated transport",
            authentication_mode,
        )

        if self._auth_provider is not None:
            self._apply_auth_provider()
            return

        # Auth is required but provider not yet built — credentials must be present
        try:
            self._config.auth.validate_credentials()
        except ValueError as exc:
            raise VenusAuthenticationError(
                "VENUS authentication is required, but credentials are missing. "
                "Set HAMILTON_VENUS_AUTH_USERNAME and HAMILTON_VENUS_AUTH_PASSWORD "
                "environment variables, or configure them in SdkConfig."
            ) from exc

        self._auth_provider = _AccessTokenProvider(
            self._config.auth,
            timeout=self._config.timeouts.http,
            verify=self._config.tls.verify,
        )
        self._apply_auth_provider()

    # -- properties -----------------------------------------------------------

    @property
    def venus(self) -> VenusClient:
        """The underlying low-level :class:`VenusClient` used for REST calls."""
        return self._venus

    @property
    def error_resolver(self) -> ErrorProfileResolver:
        """The active error-profile resolver used for instrument error handling."""
        return self._error_resolver

    @property
    def connection_state(self) -> ConnectionState:
        """Current SignalR connection state."""
        return self._listener.state

    @property
    def liquid_class_sync(self) -> _LiquidClassSync:
        """This session's record of the custom liquid classes pushed to VENUS."""
        return self._liquid_class_sync

    async def _push_liquid_classes(self, names: list[str]) -> CommandResponse:
        return await self._venus.send_command(
            category="System",
            action_name="liquidClass.pushLiquidClasses",
            parameters={"names": names},
        )

    async def _before_command(self, category: str, action_name: str, parameters: dict[str, Any]) -> None:
        names = liquid_class_names_in(parameters)
        if names:
            await self._liquid_class_sync.ensure(names)

    def override_command_timeout(self, timeout: float | None) -> AbstractContextManager[None]:
        """Temporarily override the default command timeout for a block of commands."""
        return self._venus.override_command_timeout(timeout)

    # -- lifecycle ------------------------------------------------------------

    async def start(
        self,
        *,
        auto_connect: bool = True,
        deck_name: str | None = None,
    ) -> None:
        """Start the client infrastructure, load and start the configured method.

        1. Detects whether VENUS requires authenticated transport when auth mode
           is left on automatic detection.
        2. Starts the SignalR listener and waits for ``CONNECTED`` state.
        3. Sets VENUS's system-wide simulation mode to the *simulate* flag (so
           the instrument or the firmware simulator answers accordingly), loads
           the method from the fixed SDK install location with the same flag,
           waits for ``ExecutorEvent.INITIALIZED``, clears the ``ready`` /
           ``action`` / ``action-response`` channels an earlier run may have left,
           then starts it.
        4. Polls the ``ready`` channel until this run's executor reports readiness.
        5. If *deck_name* is provided, loads the named saved deck.
        6. If *auto_connect* is enabled, calls ``instrument_connect(initialize=False)``
           before returning.

        Raises
        ------
        VenusTimeoutError
            If the SignalR connection or the method start does not complete
            within the configured timeout windows.
        """
        await self._ensure_auth_provider_configured()
        self._venus.set_before_command(self._before_command)
        self._seen_events.clear()
        timeout = self._config.timeouts.startup
        listener_started = False
        worker_started = False
        try:
            await self._listener.start()
            listener_started = True
            await self._venus._command_dispatcher.start_communication_worker()
            worker_started = True
            try:
                await _wait_with_timeout(self._wait_for_connected(), timeout)
            except TimeoutError as exc:
                raise VenusTimeoutError(f"SignalR connection did not reach CONNECTED state within {timeout}s") from exc
            _logger.info("_AsyncInstrumentClient connected to %s", self._config.base_url)

            method_path = str(get_sdk_executor_hsl_path())
            await self._cleanup_stale_method()
            self._seen_events.clear()
            # Any ABORTED/TERMINATED event received during stale cleanup must
            # not bleed into the new method session's commands.
            self._venus.reset_command_state()

            try:
                await self._venus.register_error_handler(self._error_handler_key)
                self._error_handler_registered = True
                _logger.info("Registered as error handler (key=%s)", self._error_handler_key)
            except Exception as reg_err:
                detail = getattr(reg_err, "cmd_result_message", "") or str(reg_err)
                _logger.warning(
                    "Failed to register as error handler (key=%s): %s; continuing without error handler",
                    self._error_handler_key,
                    detail,
                )
                _logger.debug("Error handler registration failed", exc_info=True)
            method_path = self._method_file_manager.prepare(
                method_path,
                self._config.method.method_display_name,
            )
            # The simulate flag on load_method only sets how VENUS executes the
            # method; the system-wide setting picks the device it talks to (the
            # instrument or the firmware simulator), so set both to match.
            await self._venus.set_simulation(self._simulate)
            _logger.info("Loading method %s (simulate=%s)", method_path, self._simulate)
            await self._venus.load_method(
                method_path,
                simulate=self._simulate,
                parent_window_handle=self._config.method.parent_window_handle,
            )
            await self._wait_for_event(ExecutorEvent.INITIALIZED, timeout=timeout)
            await self._inject_instrument_type()
            await self._inject_status_communication()
            await self._inject_idle_communication()
            await self._inject_bearer_token()
            # Before the executor runs: a 'ready' left by an earlier run would otherwise
            # look like this run's, and a command sent on it is wiped when the executor
            # clears its channels at start-up, leaving both sides waiting for each other.
            stale_ready_id = await self._reset_run_message_channels()
            _logger.info("Starting method %s", method_path)
            await self._venus.start_method()
            _logger.info("Method %s started", method_path)

            await self._wait_for_ready(stale_message_id=stale_ready_id)

            if self._run_log is not None:
                try:
                    run_data = await self._venus.get_current_run_data()
                    run_guid = str(run_data.get("runGuid") or "")
                    method_name = str(run_data.get("methodName") or "")
                    if run_guid:
                        self._run_log.set_run_guid(run_guid, method_name or None)
                        _logger.info(
                            "Linked run log to VENUS run control GUID %s (method=%s)",
                            run_guid,
                            method_name or "<unknown>",
                        )
                    else:
                        _logger.debug("No VENUS run control GUID reported; run log not linked")
                except Exception:
                    _logger.warning(
                        "Failed to fetch VENUS run control GUID for run log linkage",
                        exc_info=True,
                    )

            if deck_name:
                _logger.info("Loading saved deck: %s", deck_name)
                await self._venus.send_command(
                    category="Deck Layout",
                    action_name="deck.loadDeck",
                    parameters={"deck": deck_name, "previous": False},
                )

            if auto_connect:
                _logger.info("Auto-connect enabled; connecting to instrument after start")
                await self._venus.send_command(
                    category="Instrument",
                    action_name="status.connect",
                    parameters={"initialize": False},
                )
            else:
                _logger.info("Auto-connect disabled; skipping instrument connection after start")
        except Exception:
            if self._error_handler_registered:
                await self._try_unregister_error_handler()
            if worker_started:
                await self._venus._command_dispatcher.stop_communication_worker()
            if listener_started:
                await self._listener.stop()
            raise

    async def _inject_instrument_type(self) -> None:
        """Push the instrument type into the loaded method as a variable.

        Sets the HSL global variable ``instrumentType`` so the method knows
        which instrument model is running it.  Always called after the method
        is initialized and before it is started.
        """
        try:
            _logger.debug("_inject_instrument_type: setting instrumentType=%r", self._instrument_type.value)
            await self._venus.set_method_variables(["instrumentType"], [self._instrument_type.value])
            _logger.debug("Injected instrumentType into method variables")
        except Exception:
            _logger.warning("Failed to inject instrumentType into method variables", exc_info=True)

    async def _inject_status_communication(self) -> None:
        """Tell the loaded method whether to post its per-command status messages.

        Sets the HSL global variable ``disableStatusCommunication`` from
        ``config.method.disable_status_communication``. Sent as 1/0, not a JSON
        boolean: the method compares it against its own integer TRUE. A method
        without the variable keeps its built-in default.
        """
        value = 1 if self._config.method.disable_status_communication else 0
        try:
            _logger.debug("_inject_status_communication: setting disableStatusCommunication=%r", value)
            await self._venus.set_method_variables(["disableStatusCommunication"], [value])
            _logger.debug("Injected disableStatusCommunication into method variables")
        except Exception:
            _logger.warning("Failed to inject disableStatusCommunication into method variables", exc_info=True)

    async def _inject_idle_communication(self) -> None:
        """Tell the loaded method whether to post its per-command idle flag.

        Sets the HSL global variable ``disableIdleCommunication`` from
        ``config.method.disable_idle_communication``, as 1/0 like
        :meth:`_inject_status_communication`. When disabled, :meth:`status_is_idle`
        answers from this client's own state instead of the ``idle`` channel.
        """
        value = 1 if self._config.method.disable_idle_communication else 0
        try:
            _logger.debug("_inject_idle_communication: setting disableIdleCommunication=%r", value)
            await self._venus.set_method_variables(["disableIdleCommunication"], [value])
            _logger.debug("Injected disableIdleCommunication into method variables")
        except Exception:
            _logger.warning("Failed to inject disableIdleCommunication into method variables", exc_info=True)

    async def _inject_bearer_token(self) -> None:
        """Push the current bearer token into the loaded method as a variable.

        Sets the HSL global variable ``bearerToken`` so the running executor
        can attach it as an ``Authorization`` header on its own HTTP requests.
        Only called when an auth provider is active; silently skipped otherwise.
        """
        if self._auth_provider is None:
            return
        try:
            auth_headers = await self._auth_provider.get_auth_headers()
            _logger.debug("_inject_bearer_token: raw auth_headers keys=%r", list(auth_headers.keys()))
            auth_value = auth_headers.get("Authorization", "")
            _logger.debug(
                "_inject_bearer_token: Authorization header value (first 20 chars)=%r",
                auth_value[:20] if auth_value else "<empty>",
            )
            parts = auth_value.split(" ", 1)
            token = parts[1] if len(parts) == 2 else auth_value
            _logger.debug(
                "_inject_bearer_token: extracted token (first 20 chars)=%r, calling set_method_variables",
                token[:20] if token else "<empty>",
            )
            await self._venus.set_method_variables(["bearerToken"], [token])
            _logger.debug("Injected bearerToken into method variables")
        except Exception:
            _logger.warning("Failed to inject bearerToken into method variables", exc_info=True)

    async def _cleanup_stale_method(self) -> None:
        """Abort and unload any method left over from a previous session."""
        try:
            run_state = await self._venus.get_run_state()
            if run_state == RunState.NOT_INITIALIZED:
                return
            if run_state in (RunState.RUNNING, RunState.PAUSED, RunState.PAUSING):
                _logger.info("Aborting stale method (state=%s)", run_state.name)
                await self._venus.abort_method()
                await self._wait_for_event(
                    ExecutorEvent.TERMINATED,
                    timeout=self._config.timeouts.disconnect,
                )
            _logger.info("Unloading stale method")
            await self._venus.unload_method()
        except VenusTimeoutError:
            _logger.debug("Stale method cleanup timed out waiting for TERMINATED; continuing")
        except Exception:
            _logger.warning("Error during stale method cleanup", exc_info=True)

    async def _try_unregister_error_handler(self) -> None:
        try:
            await self._venus.unregister_error_handler(self._error_handler_key)
            self._error_handler_registered = False
            _logger.info("Unregistered error handler (key=%s)", self._error_handler_key)
        except Exception as unreg_err:
            detail = getattr(unreg_err, "cmd_result_message", "") or str(unreg_err)
            _logger.debug("Error handler unregistration failed: %s", detail, exc_info=True)

    async def stop(self) -> None:
        """Terminate and unload the running method, then shut down.

        1. If a method is loaded, terminates it and waits for
           ``ExecutorEvent.TERMINATED``, then unloads it.
        2. Stops the SignalR listener and closes the HTTP client.

        Safe to call multiple times.
        """
        try:
            run_state = await self._venus.get_run_state()
            if run_state in (RunState.RUNNING, RunState.PAUSED, RunState.PAUSING):
                _logger.info("Terminating running method")
                await self._venus.send_command(
                    category="Instrument",
                    action_name="status.terminate",
                    parameters={}
                )
                await self._wait_for_event(
                    ExecutorEvent.TERMINATED,
                    timeout=self._config.timeouts.disconnect,
                )
            if run_state != RunState.NOT_INITIALIZED:
                try:
                    _logger.info("Unloading method")
                    await self._venus.unload_method()
                except Exception:
                    _logger.debug("Unload failed (method may already be unloaded)", exc_info=True)
        except VenusCommandAbortedError as exc:
            detail = str(exc)
            if "ExecutorEvent.TERMINATED" in detail:
                _logger.debug(
                    "Method teardown observed already-terminated state; continuing cleanup"
                )
            else:
                _logger.warning("Error during method teardown", exc_info=True)
        except Exception:
            _logger.warning("Error during method teardown", exc_info=True)
        finally:
            self._method_file_manager.cleanup()

        if self._error_handler_registered:
            await self._try_unregister_error_handler()

        await self._venus._command_dispatcher.stop_communication_worker()
        await self._listener.stop()
        await self._venus.aclose()
        if self._trace_handler is not None:
            _trace_logger.removeHandler(self._trace_handler)
            self._trace_handler = None
        _logger.info("_AsyncInstrumentClient stopped")

    async def __aenter__(self) -> _AsyncInstrumentClient:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()

    # -- internal execution helpers -------------------------------------------

    async def _wait_for_event(
        self,
        target: ExecutorEvent,
        *,
        timeout: float | None = None,
    ) -> RuntimeStatusEvent:
        """Wait internally for a runtime status event with the given executor event."""
        _logger.debug("_wait_for_event: waiting for %r (timeout=%r)", target, timeout)
        failure_event = _FAILURE_EVENTS.get(target)
        while True:
            self._status_event.clear()
            if target in self._seen_events:
                event = self._seen_events[target]
                _logger.debug("_wait_for_event: received %r", event)
                return event
            if failure_event is not None and failure_event in self._seen_events:
                failed = self._seen_events[failure_event]
                _logger.debug("_wait_for_event: received failure event %r while waiting for %r", failed, target)
                raise MethodError(
                    f"Received ExecutorEvent.{failure_event.name} while waiting for "
                    f"ExecutorEvent.{target.name}: {failed.message}",
                )
            try:
                await _wait_with_timeout(self._status_event.wait(), timeout)
            except TimeoutError as exc:
                raise VenusTimeoutError(f"Timed out waiting for ExecutorEvent.{target.name}") from exc
            if target in self._seen_events:
                event = self._seen_events[target]
                _logger.debug("_wait_for_event: received %r", event)
                return event
            if failure_event is not None and failure_event in self._seen_events:
                failed = self._seen_events[failure_event]
                raise MethodError(
                    f"Received ExecutorEvent.{failure_event.name} while waiting for "
                    f"ExecutorEvent.{target.name}: {failed.message}",
                )

    # -- instrument commands --------------------------------------------------

    async def status_is_connected(self) -> bool:
        """Check if the instrument is connected and responding."""
        data = await self._venus.peek_channel("connected")
        return bool(data.get("isConnected", False)) if data else False

    async def status_is_idle(self) -> bool:
        """Check if the instrument is idle.

        With ``config.method.disable_idle_communication`` (the default) the method
        no longer posts to the ``idle`` channel, so the answer comes from this
        client: idle whenever none of its commands is in flight. That is all the
        channel ever reported to a caller of this client, without the brief false
        "not idle" while VENUS caught up after a response.
        """
        if self._config.method.disable_idle_communication:
            return not self._venus._command_dispatcher.command_active
        data = await self._venus.peek_channel("idle")
        return bool(data.get("isIdle", False)) if data else False

    # -- private callbacks ----------------------------------------------------

    async def _on_runtime_status(self, event: RuntimeStatusEvent) -> None:
        self._seen_events[event.event] = event
        transitioned = self._venus.notify_runtime_status(event.event, event.message)
        self._status_event.set()
        _logger.debug("RuntimeStatus: %s (%s)", event.event.name, event.message)
        if transitioned and event.event == ExecutorEvent.PAUSED:
            _logger.warning("Method was paused externally, resume method to continue.")
        elif transitioned and event.event == ExecutorEvent.RUNNING:
            _logger.warning("Method resumed, continuing.")

    async def _on_progress(self, event: ProgressChangedEvent) -> None:
        _logger.debug("Progress: %.1f%% — %s", event.progress_percentage, event.method_name)

    async def _on_instrument_error(self, error: ErrorData) -> None:
        await self._error_resolver.on_instrument_error(error)

    async def _on_instrument_error_notification(self, notification: str) -> None:
        _logger.info("InstrumentErrorNotification received: %s", notification)
        await self._error_resolver.on_instrument_error_notification(notification)

    async def _on_device_error_handled(self, handled: InstrumentErrorHandled) -> None:
        await self._error_resolver.on_device_error_handled(handled)

    async def _on_runtime_trace(self, arguments: list[Any]) -> None:
        payload = arguments[0] if arguments else ""
        trace_message = payload.get("runtimeTrace", str(payload)) if isinstance(payload, dict) else str(payload)
        _trace_logger.info("VenusTrace: %s", trace_message)

    async def _wait_for_connected(self) -> None:
        while self._listener.state != ConnectionState.CONNECTED:
            fatal_error = self._listener.fatal_error
            if fatal_error is not None:
                raise fatal_error
            await asyncio.sleep(0.1)

    async def _reset_run_message_channels(self) -> str | None:
        """Clear the run-message queues an earlier run may have left, before the method starts.

        A run that ended without clearing ``ready`` leaves an ``isReady`` message behind.
        Mistaken for the new run's, it let the first command be sent before the executor
        started; the executor then deletes its channels (``InitializeStatusChannels``),
        that command included, and Python and VENUS each wait for the other.

        Deletes ``ready``, ``action`` and ``action-response`` (the executor clears these
        itself at start-up). Returns the ``messageId`` of a ``ready`` message still
        queued afterwards (the delete failed), for :meth:`_wait_for_ready` to ignore;
        otherwise ``None``. Never raises.
        """
        for channel in _STALE_RUN_MESSAGE_CHANNELS:
            try:
                await self._venus.delete_channel(channel)
            except Exception as e:
                _logger.debug("delete_channel(%r) failed: %s", channel, e)
        try:
            leftover = await self._venus.peek_channel_message("ready")
        except Exception as e:
            _logger.debug("peek_channel_message('ready') failed: %s", e)
            return None
        if leftover is None:
            return None
        message_id, data = leftover
        if data.get("isReady") is not True or not message_id:
            return None
        _logger.warning(
            "A 'ready' message from an earlier run (id %s) could not be cleared; waiting for this run's",
            message_id,
        )
        return message_id

    async def _wait_for_ready(self, stale_message_id: str | None = None) -> None:
        """Poll ``ready`` until the runtime reports ready.

        With *stale_message_id*, a ``ready`` carrying that id (left by an earlier run)
        does not count: only a new message does.
        """
        timeout = self._config.timeouts.startup
        _logger.debug("Polling 'ready' channel for runtime readiness (timeout=%.1fs)", timeout)
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            for abort_event in (ExecutorEvent.ABORTING, ExecutorEvent.ABORTED, ExecutorEvent.TERMINATED):
                if abort_event in self._seen_events:
                    seen = self._seen_events[abort_event]
                    raise MethodError(
                        f"Method aborted while waiting for runtime readiness "
                        f"(event=ExecutorEvent.{abort_event.name}): {seen.message}"
                    )
            try:
                if stale_message_id is None:
                    data = await self._venus.peek_channel("ready")
                else:
                    message = await self._venus.peek_channel_message("ready")
                    data = None if message is None or message[0] == stale_message_id else message[1]
            except Exception as e:
                _logger.debug("peek_channel('ready') failed: %s", e)
                if asyncio.get_event_loop().time() >= deadline:
                    raise VenusTimeoutError(f"Runtime did not become ready within {timeout}s") from e
                await asyncio.sleep(0.1)
                continue
            if data and data.get("isReady") is True:
                _logger.debug("Runtime reported ready")
                return
            if asyncio.get_event_loop().time() >= deadline:
                raise VenusTimeoutError(f"Runtime did not become ready within {timeout}s")
            await asyncio.sleep(0.1)


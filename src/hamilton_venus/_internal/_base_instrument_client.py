"""_InstrumentSyncClientBase — shared synchronous client base for Hamilton instruments.

Holds the instrument-neutral lifecycle, logging, run-log, and command plumbing
shared by :class:`~hamilton_venus.StarClient` and
:class:`~hamilton_venus.VantageClient`. Subclasses resolve their own config
section (``star_client`` / ``vantage_client``) and pass the resolved values to
:meth:`_InstrumentSyncClientBase.__init__`.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Coroutine, Iterator
from contextlib import AbstractContextManager, contextmanager
from types import MappingProxyType
from typing import Any, TypeVar

from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient
from hamilton_venus._internal._base_sync_client import _BaseSyncClient
from hamilton_venus._internal._console_proxy import ConsoleProxy
from hamilton_venus._internal._error_profile_resolver import OperatorEscalationCallback
from hamilton_venus._internal._liquid_class_sync import liquid_class_names
from hamilton_venus._internal._operator_escalation_bridge import OperatorEscalationBridge
from hamilton_venus._internal._operator_prompts import LiquidReloadPromptCallback, TipReloadPromptCallback
from hamilton_venus._internal._run_log import RunLog
from hamilton_venus.config import RunLogConfig, SdkConfig
from hamilton_venus.constants import FLUID_MOTION_CHANNEL_TYPE, LEGACY_CHANNEL_TYPE, MAX_CHANNELS
from hamilton_venus.error_handling.presets import BUILTIN_ERROR_PROFILES
from hamilton_venus.error_handling.profile import ErrorProfile
from hamilton_venus.error_handling.profile_loaders import profile_from_json_file
from hamilton_venus.exceptions import VenusCommandAbortedError, VenusCommandUnsupportedError
from hamilton_venus.models import CommandResponse, ConfigurationResponse, ConnectionState, InstrumentType
from hamilton_venus.models.position import LabwareLayoutSpec

_logger = logging.getLogger(__name__)
_SDK_ROOT_LOGGER_NAME = "hamilton_venus"

# Channel action prefix -> ConfigurationArm attribute holding that module's channel info.
_CHANNEL_CONFIG_ATTRS = {
    "channels.1mL": "channels_1_ml",
    "channels.5mL": "channels_5_ml",
    "channels.MagPip": "channels_mag_pip",
}

# STAR gripper-tool layout action -> (channel type its 1 mL channels must be, tool label).
# Fluid Motion and Legacy channels cannot be mixed, so each type takes exactly one gripper.
_GRIPPER_TOOL_ACTIONS = {
    "labware.addQCG": (FLUID_MOTION_CHANNEL_TYPE, "a QCG"),
    "labware.add1mLCoreGrip": (LEGACY_CHANNEL_TYPE, "a CO-RE gripper"),
}

# Actions the Vantage hardware cannot perform, though the shared mixins expose them.
VANTAGE_UNSUPPORTED_ACTIONS = frozenset({"transport.1mL.presentAndScan", "transport.iswap.presentAndScan"})

# Actions the STAR hardware cannot perform, though the shared mixins expose them.
STAR_UNSUPPORTED_ACTIONS = frozenset({"frontCover.isLocked"})

# Action-name prefix -> (feature key, label) for commands that need optional hardware.
# A feature is only enforced once the instrument configuration has been read.
_FEATURE_ACTION_PREFIXES = {
    "mph96.": ("mph96", "an MPH96 head"),
    "autoload.": ("autoload", "an autoload"),
    "transport.iswap.": ("gripper", "an iSWAP/IPG gripper"),
}


_Self = TypeVar("_Self", bound="_InstrumentSyncClientBase")
_T = TypeVar("_T")
_ERROR_PROFILES: MappingProxyType[str, ErrorProfile] = BUILTIN_ERROR_PROFILES


def _resolve_error_profile(
    error_profile: ErrorProfile | None,
    *,
    error_profile_name: str,
    error_profile_path: str,
    config_section: str = "star_client",
) -> ErrorProfile:
    if error_profile is not None:
        return error_profile
    if error_profile_path:
        return profile_from_json_file(error_profile_path)
    try:
        return _ERROR_PROFILES[error_profile_name]
    except KeyError as exc:
        supported = ", ".join(sorted(_ERROR_PROFILES))
        raise ValueError(
            f"Unsupported {config_section}.error_profile_name {error_profile_name!r}. "
            f"Supported values: {supported}."
        ) from exc


def _validate_shutdown_timeout(shutdown_timeout: float | None) -> None:
    if shutdown_timeout is None:
        return
    if isinstance(shutdown_timeout, bool) or not isinstance(shutdown_timeout, int | float):
        raise TypeError("shutdown_timeout must be a number greater than 0")
    if shutdown_timeout <= 0:
        raise ValueError("shutdown_timeout must be greater than 0")


def _validate_logging_level(logging_level: int | None) -> None:
    if logging_level is None:
        return
    if isinstance(logging_level, bool) or not isinstance(logging_level, int):
        raise TypeError("logging_level must be an int greater than or equal to 0, or None")
    if logging_level < 0:
        raise ValueError("logging_level must be greater than or equal to 0")


class _InstrumentSyncClientBase(_BaseSyncClient):
    """Shared synchronous client base wrapping :class:`_AsyncInstrumentClient`.

    Expects already-resolved settings — subclasses look up their own config
    section and call ``super().__init__(...)`` with the resolved values.
    """

    def __init__(
        self,
        config: SdkConfig,
        *,
        auto_connect: bool,
        deck_name: str | None,
        simulate: bool,
        shutdown_timeout: float | None,
        logging_level: int | None,
        venus_trace_logging: bool,
        run_log: bool | RunLogConfig | None,
        error_profile: ErrorProfile,
        on_operator_error_escalation: OperatorEscalationCallback | None,
        on_tip_reload_prompt: TipReloadPromptCallback | None,
        on_liquid_reload_prompt: LiquidReloadPromptCallback | None,
        instrument_type: InstrumentType,
    ) -> None:
        _validate_shutdown_timeout(shutdown_timeout)
        _validate_logging_level(logging_level)

        default = _BaseSyncClient._DEFAULT_SHUTDOWN_TIMEOUT
        resolved_timeout = shutdown_timeout if shutdown_timeout is not None else default
        super().__init__(thread_name="hamilton-venus-sync", shutdown_timeout=resolved_timeout)
        self._config = config
        self._auto_connect = auto_connect
        self._deck_name = deck_name
        self._simulate = simulate
        self._instrument: _AsyncInstrumentClient | None = None
        # Channel totals per action prefix (e.g. "channels.1mL"), read from the
        # instrument configuration on connect. Empty until then.
        self._channel_limits: dict[str, int] = {}
        # Optional-hardware availability ("mph96", "autoload", "gripper") from the same
        # configuration read. Empty until then, in which case nothing is rejected.
        self._feature_support: dict[str, bool] = {}
        # Channel type ("Fluid Motion" / "Legacy") per action prefix, when every arm that
        # has the module reports the same one. Fluid Motion channels use the 4-channel QCG,
        # Legacy channels the 2-channel CO-RE gripper.
        self._channel_types: dict[str, str] = {}
        self._logging_level = logging_level
        self._logging_handler: logging.Handler | None = None
        self._venus_trace_logging = venus_trace_logging
        self._run_log: RunLog | None = None
        self._run_log_start_time: float | None = None
        self._console_proxy: ConsoleProxy | None = None
        self._session_id: str = uuid.uuid4().hex
        self._labware_spec_cache: dict[str, LabwareLayoutSpec] = {}
        self._labware_spec_lock = threading.Lock()
        self._error_profile = error_profile
        self._instrument_type = instrument_type
        self._com_trace_tailer: Any = None
        self._operator_escalation_bridge = OperatorEscalationBridge(
            on_operator_error_escalation,
            shutdown_timeout=self._shutdown_timeout,
        )
        _logger.info(
            "%s init: operator escalation callback provided=%s",
            type(self).__name__,
            on_operator_error_escalation is not None,
        )
        self.on_tip_reload_prompt: TipReloadPromptCallback | None = on_tip_reload_prompt
        _logger.info(
            "%s init: tip reload prompt callback provided=%s",
            type(self).__name__,
            on_tip_reload_prompt is not None,
        )
        self.on_liquid_reload_prompt: LiquidReloadPromptCallback | None = on_liquid_reload_prompt
        _logger.info(
            "%s init: liquid reload prompt callback provided=%s",
            type(self).__name__,
            on_liquid_reload_prompt is not None,
        )

        # Resolve RunLogConfig
        if isinstance(run_log, RunLogConfig):
            self._run_log_config = run_log
        elif run_log is True:
            self._run_log_config = RunLogConfig(enabled=True)
        elif run_log is False:
            self._run_log_config = RunLogConfig(enabled=False)
        else:
            self._run_log_config = self._config.run_log

    # -- context manager with automatic logging --------------------------------

    def __enter__(self: _Self) -> _Self:
        if self._logging_level is not None:
            handler = logging.StreamHandler()
            handler.setLevel(self._logging_level)
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            sdk_logger = logging.getLogger(_SDK_ROOT_LOGGER_NAME)
            sdk_logger.addHandler(handler)
            sdk_logger.setLevel(min(sdk_logger.level or logging.WARNING, self._logging_level))
            self._logging_handler = handler

        if self._run_log_config.enabled:
            from hamilton_venus import __version__

            self._run_log = RunLog(
                self._run_log_config,
                self._session_id,
                __version__,
            )
            self._run_log_start_time = time.monotonic()
            self._run_log.record(
                "SDK",
                "Out",
                "session_start",
                {
                    "sdk_version": __version__,
                    "script_name": self._run_log.script_name,
                    "config": {
                        "include_http": self._run_log_config.include_http,
                        "include_signalr": self._run_log_config.include_signalr,
                        "console_capture": self._run_log_config.console_capture,
                        "redact_auth": self._run_log_config.redact_auth,
                        "output_dir": str(self._run_log.output_dir),
                    },
                    "simulate": self._simulate,
                },
            )
            if getattr(self._run_log_config, "include_com_trace", False):
                self._snapshot_com_trace()
            if self._run_log_config.console_capture:
                self._console_proxy = ConsoleProxy(self._run_log)
                self._console_proxy.install()

        return super().__enter__()

    def _snapshot_com_trace(self) -> None:
        """Record the VENUS ``.trc`` file's current size so ``__exit__`` can
        embed only the bytes appended while this session is open. Best effort:
        any failure just disables the capture."""
        try:
            from hamilton_venus._internal._com_trace import (
                ComTraceTailer,
                resolve_logfiles_dir,
            )

            logfiles_dir = resolve_logfiles_dir(
                self._run_log_config.com_trace_logfiles_dir, self._config.base_url
            )
            self._com_trace_tailer = ComTraceTailer(
                logfiles_dir, self._instrument_type, self._simulate
            )
            if self._run_log is not None:
                self._run_log.record(
                    "SDK",
                    "In",
                    "com_trace_snapshot",
                    {
                        "path": str(self._com_trace_tailer.path),
                        "start_offset": self._com_trace_tailer.start_offset,
                        "logfiles_dir": logfiles_dir,
                    },
                )
        except Exception as exc:
            _logger.warning("COM trace snapshot failed: %s", exc)
            self._com_trace_tailer = None

    def _embed_com_trace(self) -> None:
        """Read the ``.trc`` bytes appended since :meth:`_snapshot_com_trace`
        and record them as chunked ``com_trace`` entries. Best effort."""
        if self._com_trace_tailer is None or self._run_log is None:
            return
        try:
            from hamilton_venus._internal._com_trace import iter_line_batches

            lines = self._com_trace_tailer.read_new_lines(flush_partial=True)
            cap = self._run_log_config.com_trace_max_bytes
            truncated = False
            if cap > 0:
                kept: list[str] = []
                running = 0
                for line in reversed(lines):
                    running += len(line.encode("utf-8", "replace")) + 1
                    if running > cap:
                        truncated = True
                        break
                    kept.append(line)
                lines = list(reversed(kept))
            payload_cap = self._run_log_config.max_payload_bytes
            chunk_cap = min(payload_cap // 2, 262_144) if payload_cap else 262_144
            batches = list(
                iter_line_batches(lines, max_bytes=max(1, chunk_cap), max_lines=2_000)
            )
            for idx, batch in enumerate(batches):
                self._run_log.record(
                    "SDK",
                    "In",
                    "com_trace",
                    {
                        "path": str(self._com_trace_tailer.path),
                        "chunk_index": idx,
                        "chunk_count": len(batches),
                        "start_offset": self._com_trace_tailer.start_offset,
                        "end_offset": self._com_trace_tailer.offset,
                        "line_count": len(batch),
                        "truncated": truncated and idx == 0,
                        "lines": batch,
                    },
                )
        except Exception as exc:
            _logger.warning("COM trace capture failed: %s", exc)
        finally:
            self._com_trace_tailer = None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit the context manager, finalizing run log and cleanup.

        Parameters
        ----------
        exc_type:
            Exception type if an exception occurred, otherwise None.
        exc_value:
            Exception instance if an exception occurred, otherwise None.
        exc_tb:
            Traceback object if an exception occurred, otherwise None.
        """
        try:
            super().__exit__(exc_type, exc_value, exc_tb)
        finally:
            if self._console_proxy is not None:
                self._console_proxy.uninstall()
                self._console_proxy = None
            if self._run_log is not None:
                duration = time.monotonic() - self._run_log_start_time if self._run_log_start_time is not None else 0.0
                reason = "error" if exc_type is not None else "normal"
                self._run_log.record(
                    "SDK",
                    "Out",
                    "session_end",
                    {
                        "reason": reason,
                        "duration_seconds": round(duration, 3),
                        "entry_count": self._run_log.entry_count,
                        "error_type": exc_type.__name__ if exc_type else None,
                        "error_message": str(exc_value) if exc_value else None,
                    },
                )
                # After super().__exit__() has disconnected the instrument, so
                # VENUS has flushed its trace; before finalize() closes the log.
                self._embed_com_trace()
                self._run_log.finalize(reason=reason)
                self._run_log = None
            if self._logging_handler is not None:
                sdk_logger = logging.getLogger(_SDK_ROOT_LOGGER_NAME)
                sdk_logger.removeHandler(self._logging_handler)
                self._logging_handler = None

    # -- abort-safe command execution -----------------------------------------

    def _run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """Execute *coro* on the background event loop, triggering shutdown on method abort.

        Wraps :meth:`_BaseSyncClient._run` so that any :class:`VenusCommandAbortedError`
        raised by an in-flight command automatically calls :meth:`stop` before
        re-raising. This ensures cleanup even when callers do not catch the exception.
        """
        try:
            return super()._run(coro)
        except VenusCommandAbortedError:
            _logger.warning(
                "VenusCommandAbortedError: method was aborted while a command was in-flight; "
                "triggering automatic client shutdown"
            )
            self.stop()
            raise

    # -- abstract hook implementations ----------------------------------------

    async def _async_start(self) -> None:
        _logger.info("%s starting (simulate=%s)", type(self).__name__, self._simulate)
        resolver_callback = self._operator_escalation_bridge.resolver_callback
        _logger.info(
            "%s _async_start: resolver callback registered=%s",
            type(self).__name__,
            resolver_callback is not None,
        )
        self._instrument = _AsyncInstrumentClient(
            self._config,
            simulate=self._simulate,
            venus_trace_logging=self._venus_trace_logging,
            run_log=self._run_log,
            run_log_config=self._run_log_config,
            error_profile=self._error_profile,
            on_operator_error_escalation=resolver_callback,
            instrument_type=self._instrument_type,
        )
        self._instrument.venus.set_command_guard(self._check_command_supported)
        await self._instrument.start(auto_connect=self._auto_connect, deck_name=self._deck_name)
        if self._auto_connect:
            await self._load_instrument_config()
        _logger.info("%s started", type(self).__name__)

    def _check_command_supported(self, category: str, action_name: str) -> None:
        """Reject commands for hardware the instrument configuration says is not there."""
        if self._instrument_type is InstrumentType.Vantage and action_name in VANTAGE_UNSUPPORTED_ACTIONS:
            raise VenusCommandUnsupportedError(f"{action_name} is not supported on a Vantage")
        if self._instrument_type is InstrumentType.STAR and action_name in STAR_UNSUPPORTED_ACTIONS:
            raise VenusCommandUnsupportedError(f"{action_name} is not supported on a STAR")
        for prefix, (feature, label) in _FEATURE_ACTION_PREFIXES.items():
            if action_name.startswith(prefix) and self._feature_support.get(feature) is False:
                raise VenusCommandUnsupportedError(
                    f"{action_name} requires {label}, but the instrument configuration does not report one"
                )
        if self._instrument_type is InstrumentType.STAR and action_name in _GRIPPER_TOOL_ACTIONS:
            required_type, label = _GRIPPER_TOOL_ACTIONS[action_name]
            actual_type = self._channel_types.get("channels.1mL")
            if actual_type is not None and actual_type != required_type:
                raise VenusCommandUnsupportedError(
                    f"{action_name} adds {label}, which needs {required_type} channels, "
                    f"but the instrument configuration reports {actual_type} 1mL channels"
                )

    async def _load_instrument_config(self) -> None:
        """Query the instrument configuration and cache what it says the hardware supports.

        Caches the per-module channel totals and which optional hardware (MPH96 head,
        autoload, iSWAP/IPG gripper) is present. Best effort: on any failure the caches
        are left as-is, channel validation falls back to
        :data:`~hamilton_venus.constants.MAX_CHANNELS`, and no command is rejected for
        missing hardware. Called after the instrument connects (``start`` with
        auto-connect, and ``instrument_connect``).
        """
        try:
            response = await self._connected_instrument.venus.send_command(
                category="Instrument",
                action_name="configuration.getConfiguration",
            )
            params = ConfigurationResponse.model_validate(response.model_dump(by_alias=True)).return_parameters
        except Exception:
            _logger.warning(
                "Could not read channel counts from the instrument configuration; "
                "using the SDK ceiling of %d channels",
                MAX_CHANNELS,
                exc_info=True,
            )
            return

        limits: dict[str, int] = {}
        for action_prefix, arm_attr in _CHANNEL_CONFIG_ATTRS.items():
            # A command runs on a single arm, so the largest arm total is the
            # loosest count any valid request could reach.
            totals = [
                info.total
                for arm in (params.left_arm, params.right_arm)
                if arm is not None and (info := getattr(arm, arm_attr)) is not None and info.total
            ]
            if totals:
                limits[action_prefix] = max(totals)
        self._channel_limits = limits
        arms = [arm for arm in (params.left_arm, params.right_arm) if arm is not None]
        channel_types: dict[str, str] = {}
        for action_prefix, arm_attr in _CHANNEL_CONFIG_ATTRS.items():
            types = {info.type for arm in arms if (info := getattr(arm, arm_attr)) is not None}
            # Skip a module whose arms disagree (or report no type) rather than guess.
            if len(types) == 1 and (channel_type := next(iter(types))):
                channel_types[action_prefix] = channel_type
        self._channel_types = channel_types
        self._feature_support = {
            "mph96": any(arm.mph96 not in (None, False) for arm in arms),
            "autoload": params.autoload is True,
            "gripper": any(arm.gripper is not None and bool(arm.gripper.type) for arm in arms),
        }
        _logger.info(
            "Instrument configuration: channel limits %s, channel types %s, optional hardware %s",
            limits,
            channel_types,
            self._feature_support,
        )

    async def _async_stop(self) -> None:
        _logger.info("%s stopping", type(self).__name__)
        if self._instrument is not None:
            await self._instrument.stop()
            self._instrument = None
        _logger.info("%s stopped", type(self).__name__)

    # -- private helper -------------------------------------------------------

    @property
    def _connected_instrument(self) -> _AsyncInstrumentClient:
        """Return the underlying async client, raising if not started."""
        if self._instrument is None:
            raise RuntimeError("Client is not started. Call start() or use 'with' statement.")
        return self._instrument

    # -- labware definition cache --------------------------------------------

    def get_labware_spec(self, labware_id: str) -> LabwareLayoutSpec:
        """Return the cached :class:`LabwareLayoutSpec` for *labware_id*.

        On a cache miss the SDK fetches the labware definition from the
        connected deck (via
        :meth:`~hamilton_venus.mixins.labware_commands.LabwareCommandsMixin.labware_get_params_from_id`)
        and stores the derived layout for the lifetime of this client.
        The deck layout is treated as immutable for a given client
        session, so cached entries are never evicted automatically;
        terminate the client and start a new one to pick up deck changes.

        Args:
            labware_id: Labware instance name as defined on the deck.

        Returns:
            The :class:`LabwareLayoutSpec` derived from the labware's
            VENUS definition.

        Raises:
            VenusCommandFailedError: If the labware id is not present on
                the deck.

        Note:
            The cache is a plain, case-sensitive dict keyed by exactly the
            *labware_id* passed in. VENUS stores every labware id lower-cased
            regardless of the case it was added with (see
            ``deck_labware_commands``'s module docstring), so calling this with
            two different casings for the same physical labware (e.g. once as
            typed in a script and once as read back from a tracking event) will
            silently create two separate cache entries and issue two lookups
            instead of one. Callers that mix a typed id with an id read back
            from VENUS should normalize both to the same case first.
        """
        cached = self._labware_spec_cache.get(labware_id)
        if cached is not None:
            return cached
        with self._labware_spec_lock:
            cached = self._labware_spec_cache.get(labware_id)
            if cached is not None:
                return cached
            response = self.labware_get_params_from_id(labware_id)  # type: ignore[attr-defined]
            spec = LabwareLayoutSpec.from_definition(response.return_parameters.definition)
            self._labware_spec_cache[labware_id] = spec
            return spec

    def register_labware_definition(self, labware_id: str, spec: LabwareLayoutSpec) -> None:
        """Pre-populate or override the cached :class:`LabwareLayoutSpec` for *labware_id*.

        Useful for unit tests that exercise position-resolution logic
        without a connected deck, and for the rare case where a caller
        needs to override the deck's geometry for a specific labware
        instance.  Overwrites any existing cache entry.
        """
        with self._labware_spec_lock:
            self._labware_spec_cache[labware_id] = spec

    # -- properties -----------------------------------------------------------

    @property
    def connection_state(self) -> ConnectionState:
        """Current SignalR connection state."""
        return self._connected_instrument.connection_state

    @property
    def simulate(self) -> bool:
        """Whether this client runs its VENUS method in simulation mode.

        This is the ``simulate`` value the client was constructed with, so a script
        can branch on it rather than on its own flag -- including when a runner
        (e.g. the Script Manager) sets ``simulate`` on the client for it.
        """
        return self._simulate

    # -- context managers for command configuration ----------------------------

    def set_command_timeout(self, timeout: float | None) -> AbstractContextManager[None]:
        """Context manager to override command timeout for a block of commands.

        All commands executed within this context will use the specified timeout,
        overriding the client's configured command timeout. This is useful when
        certain operations require longer than the default timeout, or when a
        command requires user input and should wait indefinitely.

        Parameters
        ----------
        timeout:
            Command timeout in seconds. Must be greater than 0, or ``None`` to
            wait indefinitely (no timeout).

        Returns
        -------
        Context manager.

        Raises
        ------
        ValueError
            If timeout is not greater than 0 (when not ``None``).

        Examples
        --------
        Execute commands with a longer timeout::

            with star.set_command_timeout(120.0):
                star.instrument_init()  # Uses 120 second timeout
                star.instrument_get_configuration()  # Also uses 120 second timeout

        Disable timeout for commands requiring user input::

            with star.set_command_timeout(None):
                star.send_command("user", "prompt", {"message": "Load plate"})

        The context manager restores the original timeout after exiting::

            star.instrument_is_idle()  # Back to default timeout
        """
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be greater than 0")

        return self._connected_instrument.override_command_timeout(timeout)

    @contextmanager
    def use_error_profile(self, profile: ErrorProfile) -> Iterator[None]:
        """Context manager to temporarily switch the active error profile.

        Parameters
        ----------
        profile:
            Error profile to activate for the duration of the block.

        Examples
        --------
        ::

            from hamilton_venus.error_handling import STANDARD_PROFILE

            with star.use_error_profile(STANDARD_PROFILE):
                star.aspirate(...)  # Uses STANDARD_PROFILE error handling
        """
        resolver = self._connected_instrument.error_resolver
        previous = resolver.active_profile
        resolver.set_active_profile(profile)
        try:
            yield
        finally:
            resolver.set_active_profile(previous)

    @contextmanager
    def _liquid_classes_for_command(self, *liquid_classes: Any) -> Iterator[None]:
        """Push a compound command's custom liquid classes once, up front, then skip
        the per-command check for them until the command returns -- it uses the same
        liquid class(es) throughout. Each argument is a name or a per-channel list."""
        names = [name for value in liquid_classes for name in liquid_class_names(value)]
        sync = self._connected_instrument.liquid_class_sync
        self._run(sync.ensure(names))
        with sync.hold(names):
            yield

    # -- command execution ----------------------------------------------------

    def send_command(
        self,
        category: str,
        action_name: str,
        parameters: dict[str, Any] | None = None,
    ) -> CommandResponse:
        """Send a structured command to the instrument.

        This is an advanced fallback API for commands that do not yet have a
        dedicated SDK helper.

        Parameters
        ----------
        category:
            Command category (e.g. ``"System"``, ``"Layout"``, ``"Channels"``).
        action_name:
            Dot-separated action name e.g. ``"instrument.isConnected"``.
        parameters:
            Action-specific parameters. Defaults to an empty dict.

        Returns
        -------
        CommandResponse
            The parsed response from the instrument.

        Raises
        ------
        VenusError
            If the command fails or the response indicates an error.
        """
        return self._run(
            self._connected_instrument.venus.send_command(category, action_name, parameters),
        )

    def start(self) -> None:
        """Start the client and connect to VENUS."""
        self._operator_escalation_bridge.start()

        try:
            super().start()
        except Exception:
            self._operator_escalation_bridge.stop(f"{type(self).__name__} start failed")
            raise

    def stop(self) -> None:
        """Stop the client and any operator escalation worker."""
        super().stop()
        self._operator_escalation_bridge.stop(
            f"{type(self).__name__} stopped before escalation callback completed"
        )

"""VantageClient — synchronous client for Hamilton Vantage instruments.

Runs the async :class:`_AsyncInstrumentClient` on a background thread so that callers
never need to touch ``asyncio`` directly::

    with VantageClient() as vantage:
        connected = vantage.instrument_is_connected()

For commands that do not yet have dedicated SDK helpers, use
:meth:`VantageClient.send_command` as an advanced fallback.
"""

from __future__ import annotations

from hamilton_venus._internal._base_instrument_client import (
    _InstrumentSyncClientBase,
    _resolve_error_profile,
)
from hamilton_venus._internal._error_profile_resolver import OperatorEscalationCallback
from hamilton_venus._internal._operator_prompts import LiquidReloadPromptCallback, TipReloadPromptCallback
from hamilton_venus.config import RunLogConfig, SdkConfig, load_config
from hamilton_venus.devices import (
    BalanceDeviceCommands,
    HeaterShakerDeviceCommands,
)
from hamilton_venus.error_handling.profile import ErrorProfile
from hamilton_venus.mixins import (
    AutoloadCommandsMixin,
    ChannelCommandsMixin,
    Channels5mLCommandsMixin,
    ChannelsMagPipCommandsMixin,
    CompoundCommandsMixin,
    ConfigurationCommandsMixin,
    DeckCommandsMixin,
    DeckLabwareCommandsMixin,
    DeckStatusCommandsMixin,
    ErrorSimulatorCommandsMixin,
    FirmwareCommandsMixin,
    FrontCoverCommandsMixin,
    LabwareCommandsMixin,
    LabwareDefinitionCommandsMixin,
    LiquidClassCommandsMixin,
    LoadTrayCommandsMixin,
    MaintenanceCommandsMixin,
    MPH96CommandsMixin,
    PipettingArmCommandsMixin,
    SampleTrackingCommandsMixin,
    SplitWellCommandsMixin,
    StatusCommandsMixin,
    StatusLightCommandsMixin,
    TaughtLocationCommandsMixin,
    TeachingCommandsMixin,
    TipPoolCommandsMixin,
    TransportCommandsMixin,
)
from hamilton_venus.models import InstrumentType


class VantageClient(
    _InstrumentSyncClientBase,
    StatusCommandsMixin,
    ConfigurationCommandsMixin,
    MaintenanceCommandsMixin,
    FrontCoverCommandsMixin,
    FirmwareCommandsMixin,
    ErrorSimulatorCommandsMixin,
    PipettingArmCommandsMixin,
    AutoloadCommandsMixin,
    StatusLightCommandsMixin,
    DeckCommandsMixin,
    DeckLabwareCommandsMixin,
    DeckStatusCommandsMixin,
    TipPoolCommandsMixin,
    LabwareCommandsMixin,
    LabwareDefinitionCommandsMixin,
    ChannelCommandsMixin,
    Channels5mLCommandsMixin,
    ChannelsMagPipCommandsMixin,
    MPH96CommandsMixin,
    LiquidClassCommandsMixin,
    LoadTrayCommandsMixin,
    TransportCommandsMixin,
    TaughtLocationCommandsMixin,
    TeachingCommandsMixin,
    SampleTrackingCommandsMixin,
    SplitWellCommandsMixin,
    CompoundCommandsMixin,
    HeaterShakerDeviceCommands,
    BalanceDeviceCommands,
):
    """Synchronous high-level client for Hamilton Vantage instruments.

    Wraps :class:`_AsyncInstrumentClient` and runs all async operations on a dedicated
    background event-loop thread. On start, the configured method is started
    automatically by the underlying async client, then the client waits briefly
    for runtime readiness. Instrument connection is controlled by the
    ``auto_connect`` constructor parameter.
    Supports the regular ``with`` statement::

        with VantageClient(config) as vantage:
            connected = vantage.instrument_is_connected()

    Automatic logging can be enabled by passing ``logging_level``::

        with VantageClient(logging_level=logging.DEBUG) as vantage:
            vantage.instrument_is_connected()  # SDK log output visible on stderr

    Command methods are organized into category mixins:

    - :class:`~hamilton_venus.mixins.StatusCommandsMixin` — connection and initialization
    - :class:`~hamilton_venus.mixins.ConfigurationCommandsMixin` — instrument configuration
    - :class:`~hamilton_venus.mixins.MaintenanceCommandsMixin` — maintenance status and tracking
    - :class:`~hamilton_venus.mixins.FrontCoverCommandsMixin` — front cover control
    - :class:`~hamilton_venus.mixins.FirmwareCommandsMixin` — raw firmware commands
    - :class:`~hamilton_venus.mixins.PipettingArmCommandsMixin` — pipetting arm positioning
    - :class:`~hamilton_venus.mixins.AutoloadCommandsMixin` — autoload carrier management
    - :class:`~hamilton_venus.mixins.StatusLightCommandsMixin` — status light control
    - :class:`~hamilton_venus.mixins.DeckCommandsMixin` — deck persistence commands
    - :class:`~hamilton_venus.mixins.DeckLabwareCommandsMixin` — deck labware placement
    - :class:`~hamilton_venus.mixins.DeckStatusCommandsMixin` — deck layout status queries
    - :class:`~hamilton_venus.mixins.ErrorSimulatorCommandsMixin` — simulated firmware errors
    - :class:`~hamilton_venus.mixins.TipPoolCommandsMixin` — tip pool management
    - :class:`~hamilton_venus.mixins.LabwareCommandsMixin` — deck labware management
    - :class:`~hamilton_venus.mixins.LabwareDefinitionCommandsMixin` — labware definitions
    - :class:`~hamilton_venus.mixins.ChannelCommandsMixin` — 1 mL pipetting commands
    - :class:`~hamilton_venus.mixins.Channels5mLCommandsMixin` — 5 mL pipetting commands
    - :class:`~hamilton_venus.mixins.ChannelsMagPipCommandsMixin` — MagPip (magnetic-bead)
      1 mL pipetting commands (``*_magpip``); Vantage only
    - :class:`~hamilton_venus.mixins.MPH96CommandsMixin` — 96-channel head commands
    - :class:`~hamilton_venus.mixins.LiquidClassCommandsMixin` — liquid class definitions
    - :class:`~hamilton_venus.mixins.LoadTrayCommandsMixin` — load tray raise/lower (Vantage only)
    - :class:`~hamilton_venus.mixins.TransportCommandsMixin` — plate transport (1 mL grip and iSWAP);
      ``transport.5mL.*`` and ``transport.QCG.*`` methods, ``core_present_and_scan`` and
      ``iswap_present_and_scan`` are not available on Vantage hardware
    - :class:`~hamilton_venus.mixins.TaughtLocationCommandsMixin` — record operator taught
      locations into ``Active Layout\\TaughtLocations.json`` (local file; VENUS enforces)
    - :class:`~hamilton_venus.mixins.TeachingCommandsMixin` — teaching needle moves, Z-stall
      wall/bottom searches and automated plate teaching (``teach_well``)
    - :class:`~hamilton_venus.mixins.SplitWellCommandsMixin` — several channels per large well
    - :class:`~hamilton_venus.mixins.SampleTrackingCommandsMixin` — sample tracking (barcodes,
      tracked labware details and volumes)
    - :class:`~hamilton_venus.mixins.CompoundCommandsMixin` — high-level compound commands
      (copy plate, add reagent, hit picking, pool samples, replicate samples, serial dilution)
    - :class:`~hamilton_venus.devices.HeaterShakerDeviceCommands` — Hamilton Heater Shaker (HHS) control
    - :class:`~hamilton_venus.devices.BalanceDeviceCommands` — WXS balance control

    The Hamilton Heater Cooler (HHC) and Inheco ODTC are **not** on this client --
    both are pure-Python, no-VENUS drivers with their own standalone clients
    (:class:`~hamilton_venus.HeaterCoolerClient`, :class:`~hamilton_venus.ODTCClient`)
    that need no ``StarClient``/``VantageClient`` at all.

    Use the typed mixin helpers when available. For assay-specific commands that
    do not yet have a dedicated SDK helper, use :meth:`send_command` as an
    advanced fallback.

    Parameters
    ----------
    config:
        SDK configuration. When *None*, :func:`~hamilton_venus.config.load_config`
        is called to resolve configuration from the environment or defaults.
    auto_connect:
        When *True*, :meth:`start` connects to the instrument automatically
        after the method starts (via ``instrument_connect(initialize=False)``).
        When *None* (the default), falls back to ``config.vantage_client.auto_connect``.
    deck_name:
        When set, :meth:`start` loads the named saved deck before auto-connect
        fires. Defaults to *None*.
    simulate:
        When *True*, the configured method is started in simulation mode.
        Defaults to *False*.
    shutdown_timeout:
        Maximum seconds to wait for async teardown and thread join during
        :meth:`stop`. When *None* (the default), falls back to
        ``config.vantage_client.shutdown_timeout``.
    logging_level:
        When set to a logging level (e.g. ``logging.DEBUG``), a
        :class:`logging.StreamHandler` is attached to the ``hamilton_venus``
        SDK logger for the duration of the ``with`` block. This configures
        logging for the SDK only — not application-level logging. The handler
        is removed automatically on exit. When ``use_config_logging_level`` is
        *False*, this value is used directly (including *None* to disable SDK
        handler attachment).
    use_config_logging_level:
        Controls how ``logging_level`` is resolved. When *True* (default),
        ``logging_level=None`` inherits ``config.vantage_client.logging_level``.
        When *False*, ``logging_level`` is used exactly as provided.
    venus_trace_logging:
        When *True*, Venus runtime trace messages received via the SignalR
        ``NewRuntimeTrace`` event are printed to stderr regardless of the
        application's logging configuration. Uses a dedicated
        ``hamilton_venus.traces`` logger with its own stream handler.
        When *None* (the default), falls back to
        ``config.vantage_client.venus_trace_logging``.
    run_log:
        Enable or disable the structured JSON run log. Pass *True* to enable
        with default settings (creates ``RunLogConfig(enabled=True)``), pass
        *False* to force disable (creates ``RunLogConfig(enabled=False)``), or
        pass a :class:`~hamilton_venus.config.RunLogConfig` instance for full
        control. When *None* (the default), the run-log configuration falls
        back to ``config.run_log`` (i.e. the value from the loaded
        :class:`~hamilton_venus.config.SdkConfig`).
    error_profile:
        Error profile used by the async error resolver. When *None* (the
        default), the client resolves the profile in this order:
        ``error_profile`` argument, ``config.vantage_client.error_profile_path``
        JSON file, then ``config.vantage_client.error_profile_name``.

    """

    def __init__(
        self,
        config: SdkConfig | None = None,
        *,
        auto_connect: bool | None = None,
        deck_name: str | None = None,
        simulate: bool = False,
        shutdown_timeout: float | None = None,
        logging_level: int | None = None,
        use_config_logging_level: bool = True,
        venus_trace_logging: bool | None = None,
        run_log: bool | RunLogConfig | None = None,
        error_profile: ErrorProfile | None = None,
        on_operator_error_escalation: OperatorEscalationCallback | None = None,
        on_tip_reload_prompt: TipReloadPromptCallback | None = None,
        on_liquid_reload_prompt: LiquidReloadPromptCallback | None = None,
        instrument_type: InstrumentType = InstrumentType.Vantage,
    ) -> None:
        resolved_config = config or load_config()
        resolved_shutdown_timeout = (
            resolved_config.vantage_client.shutdown_timeout if shutdown_timeout is None else shutdown_timeout
        )
        resolved_auto_connect = resolved_config.vantage_client.auto_connect if auto_connect is None else auto_connect
        if use_config_logging_level:
            resolved_logging_level = (
                resolved_config.vantage_client.logging_level if logging_level is None else logging_level
            )
        else:
            resolved_logging_level = logging_level
        resolved_venus_trace_logging = (
            resolved_config.vantage_client.venus_trace_logging if venus_trace_logging is None else venus_trace_logging
        )
        resolved_error_profile = _resolve_error_profile(
            error_profile,
            error_profile_name=resolved_config.vantage_client.error_profile_name,
            error_profile_path=resolved_config.vantage_client.error_profile_path,
            config_section="vantage_client",
        )

        super().__init__(
            resolved_config,
            auto_connect=resolved_auto_connect,
            deck_name=deck_name,
            simulate=simulate,
            shutdown_timeout=resolved_shutdown_timeout,
            logging_level=resolved_logging_level,
            venus_trace_logging=resolved_venus_trace_logging,
            run_log=run_log,
            error_profile=resolved_error_profile,
            on_operator_error_escalation=on_operator_error_escalation,
            on_tip_reload_prompt=on_tip_reload_prompt,
            on_liquid_reload_prompt=on_liquid_reload_prompt,
            instrument_type=instrument_type,
        )

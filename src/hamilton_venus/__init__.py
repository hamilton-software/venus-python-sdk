"""Hamilton VENUS Python SDK."""

try:
    from hamilton_venus._version import __version__  # type: ignore[import-not-found]
except ModuleNotFoundError:
    __version__ = "0.0.0.dev0"

from hamilton_venus._internal._error_profile_resolver import (
    OperatorEscalationCallback,
    OperatorEscalationContext,
)
from hamilton_venus._internal._operator_prompts import (
    LiquidReloadPromptCallback,
    LiquidReloadPromptContext,
    TipReloadPromptCallback,
    TipReloadPromptContext,
)
from hamilton_venus.config import (
    AuthConfig,
    MethodConfig,
    NetworkConfig,
    RunLogConfig,
    SdkConfig,
    StarClientConfig,
    TimeoutConfig,
    VantageClientConfig,
    load_config,
)
from hamilton_venus.constants import OVERRIDE_SAFETY_CHECKS
from hamilton_venus.devices import HeaterCoolerClient, InhecoTECClient, MediaFillClient, ODTCClient, TiltModuleClient
from hamilton_venus.error_handling import (
    ALLOWED_ACTIONS,
    STANDARD_PROFILE,
    ErrorEntry,
    ErrorProfile,
)
from hamilton_venus.error_handling.recovery_builder import (
    build_error_recovery,
    build_mixed_recovery,
    build_per_channel_recovery,
    resolve_error_recovery,
    resolve_per_channel_recovery,
)
from hamilton_venus.exceptions import (
    HeaterCoolerError,
    InhecoTECError,
    LabwareTiltedError,
    LiquidClassPushError,
    MediaFillError,
    MethodError,
    ODTCError,
    OperatorCancelledError,
    SplitWellCapacityError,
    TiltModuleError,
    VenusApiContractError,
    VenusAuthenticationError,
    VenusCommandAbortedError,
    VenusCommandFailedError,
    VenusCommandUnsupportedError,
    VenusConnectionError,
    VenusError,
    VenusTimeoutError,
)
from hamilton_venus.models import (
    ActionKind,
    AddReagentIterationResult,
    AddReagentResult,
    AddReagentWellDispense,
    Aspirate2ndPhaseError,
    AspirateError,
    AutoloadError,
    CmdResult,
    CommandRequest,
    CommandResponse,
    CompoundCommandResult,
    ConnectionState,
    CopyPlateResult,
    COREGripTransportError,
    CoverError,
    DispenseError,
    DispenseFlyError,
    EasyAspirateError,
    EasyDispenseError,
    ExecutorEvent,
    GripperError,
    Head96AspirateError,
    Head96DispenseError,
    Head96TipPickUpError,
    HitPickingResult,
    InitializeError,
    InstrumentType,
    LabwareLayoutSpec,
    LastDilutionWaste,
    MagPipError,
    MoveToPositionError,
    NeedleWashError,
    PoolSamplesIterationResult,
    PoolSamplesResult,
    PreAliquotDisposal,
    ProgressChangedEvent,
    RecoveryAction,
    ReplicateSamplesIterationResult,
    ReplicateSamplesResult,
    RunMessageQueuedEvent,
    RunState,
    RuntimeStatusEvent,
    SerialDilutionPlateResult,
    SerialDilutionResult,
    SerialDilutionSeriesResult,
    SerialDilutionStepResult,
    TeachingDirection,
    TeachingMeasureStatus,
    TipEjectError,
    TipPickupError,
    TrackedLabwareType,
    WellOrder,
    XLAspirateError,
    XLDispenseError,
    XLDispenseFlyError,
    XLTipEjectError,
    XLTipPickupError,
    ZSwapGetPlateError,
    ZSwapPlacePlateError,
    ZSwapReadBarcodeError,
)
from hamilton_venus.star_client import StarClient
from hamilton_venus.taught_locations import (
    CarrierSiteOffset,
    LabwarePosition,
    TaughtLocationsFile,
    carrier_site_key,
    clear_taught_locations,
    get_taught_locations,
    get_taught_offset,
    get_taught_position,
    get_taught_positions,
    register_taught_offset,
    register_taught_position,
    remove_taught_offset,
    remove_taught_position,
    resolve_taught_location,
)
from hamilton_venus.teaching import TeachingError, TeachWellResult
from hamilton_venus.vantage_client import VantageClient
from hamilton_venus.venus_client import VenusClient


def recover_run_log(jsonl_path: str) -> str:
    """Convert a crash-surviving ``.jsonl`` run log into the standard finalized ``.json`` format.

    When a run terminates abnormally before the SDK can finalize the log, both
    the ``.jsonl`` streaming file and the ``.meta.json`` sidecar remain on disk.
    This helper reads them, wraps the entries with top-level metadata, writes
    the final ``.json``, and removes the temporary files.

    Parameters
    ----------
    jsonl_path:
        Path to the ``.jsonl`` file left over from a crashed run.

    Returns
    -------
    str
        Path to the newly created finalized ``.json`` file.

    Raises
    ------
    FileNotFoundError
        If *jsonl_path* does not exist.
    ValueError
        If the file contains zero valid log entries.
    """
    from hamilton_venus._internal._run_log import RunLog

    return str(RunLog.recover(jsonl_path))


__all__ = [
    "ALLOWED_ACTIONS",
    "OVERRIDE_SAFETY_CHECKS",
    "STANDARD_PROFILE",
    "ActionKind",
    "AddReagentIterationResult",
    "AddReagentResult",
    "AddReagentWellDispense",
    "Aspirate2ndPhaseError",
    "AspirateError",
    "AuthConfig",
    "AutoloadError",
    "COREGripTransportError",
    "CarrierSiteOffset",
    "CmdResult",
    "CommandRequest",
    "CommandResponse",
    "CompoundCommandResult",
    "ConnectionState",
    "CopyPlateResult",
    "CoverError",
    "DispenseError",
    "DispenseFlyError",
    "EasyAspirateError",
    "EasyDispenseError",
    "ErrorEntry",
    "ErrorProfile",
    "ExecutorEvent",
    "GripperError",
    "Head96AspirateError",
    "Head96DispenseError",
    "Head96TipPickUpError",
    "HeaterCoolerClient",
    "HeaterCoolerError",
    "HitPickingResult",
    "InhecoTECClient",
    "InhecoTECError",
    "InitializeError",
    "InstrumentType",
    "LabwareLayoutSpec",
    "LabwarePosition",
    "LabwareTiltedError",
    "LastDilutionWaste",
    "LiquidClassPushError",
    "LiquidReloadPromptCallback",
    "LiquidReloadPromptContext",
    "MagPipError",
    "MediaFillClient",
    "MediaFillError",
    "MethodConfig",
    "MethodError",
    "MoveToPositionError",
    "NeedleWashError",
    "NetworkConfig",
    "ODTCClient",
    "ODTCError",
    "OperatorCancelledError",
    "OperatorEscalationCallback",
    "OperatorEscalationContext",
    "PoolSamplesIterationResult",
    "PoolSamplesResult",
    "PreAliquotDisposal",
    "ProgressChangedEvent",
    "RecoveryAction",
    "ReplicateSamplesIterationResult",
    "ReplicateSamplesResult",
    "RunLogConfig",
    "RunMessageQueuedEvent",
    "RunState",
    "RuntimeStatusEvent",
    "SdkConfig",
    "SerialDilutionPlateResult",
    "SerialDilutionResult",
    "SerialDilutionSeriesResult",
    "SerialDilutionStepResult",
    "SplitWellCapacityError",
    "StarClient",
    "StarClientConfig",
    "TaughtLocationsFile",
    "TeachWellResult",
    "TeachingDirection",
    "TeachingError",
    "TeachingMeasureStatus",
    "TiltModuleClient",
    "TiltModuleError",
    "TimeoutConfig",
    "TipEjectError",
    "TipPickupError",
    "TipReloadPromptCallback",
    "TipReloadPromptContext",
    "TrackedLabwareType",
    "VantageClient",
    "VantageClientConfig",
    "VenusApiContractError",
    "VenusAuthenticationError",
    "VenusClient",
    "VenusCommandAbortedError",
    "VenusCommandFailedError",
    "VenusCommandUnsupportedError",
    "VenusConnectionError",
    "VenusError",
    "VenusTimeoutError",
    "WellOrder",
    "XLAspirateError",
    "XLDispenseError",
    "XLDispenseFlyError",
    "XLTipEjectError",
    "XLTipPickupError",
    "ZSwapGetPlateError",
    "ZSwapPlacePlateError",
    "ZSwapReadBarcodeError",
    "__version__",
    "build_error_recovery",
    "build_mixed_recovery",
    "build_per_channel_recovery",
    "carrier_site_key",
    "clear_taught_locations",
    "get_taught_locations",
    "get_taught_offset",
    "get_taught_position",
    "get_taught_positions",
    "load_config",
    "recover_run_log",
    "register_taught_offset",
    "register_taught_position",
    "remove_taught_offset",
    "remove_taught_position",
    "resolve_error_recovery",
    "resolve_per_channel_recovery",
    "resolve_taught_location",
]

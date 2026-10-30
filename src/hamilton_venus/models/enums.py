"""Enumerations for the Hamilton VENUS Python SDK."""

from __future__ import annotations

from enum import Enum, IntEnum, StrEnum


class InstrumentType(StrEnum):
    """Identifies the Hamilton instrument model driving this run.

    The string value is injected into the loaded HSL method as the
    ``instrumentType`` global variable before execution starts.
    """

    STAR = "STAR"
    Vantage = "Vantage"
    Nimbus8 = "Nimbus8"
    Nimbus96 = "Nimbus96"


_EXECUTOR_EVENT_STR_MAP: dict[str, int] = {
    "undefined": 0,
    "initialized": 1,
    "initializefailed": 2,
    "terminated": 3,
    "aborted": 4,
    "paused": 5,
    "running": 6,
    "unloaded": 7,
    "starting": 8,
    "processed": 9,
    "aborting": 10,
}


class RunState(IntEnum):
    """Mirrors ``Hamilton.WebAPI.Common.Contracts.Realtime-activity-data.RunState``."""

    NOT_INITIALIZED = 0
    INITIALIZED = 1
    RUNNING = 2
    ABORTING = 3
    ABORTED = 4
    PROCESSED = 5
    PAUSING = 6
    PAUSED = 7
    STARTING = 8
    TERMINATING = 9
    TERMINATED = 10
    UNKNOWN = 11

    @classmethod
    def from_api_value(cls, value: int) -> RunState:
        """Parse an integer run-state, returning ``UNKNOWN`` for unrecognised values."""
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN


class ExecutorEvent(IntEnum):
    """Mirrors ``Hamilton.WebAPI.Common.ExecutorEvent``."""

    UNDEFINED = 0
    INITIALIZED = 1
    INITIALIZE_FAILED = 2
    TERMINATED = 3
    ABORTED = 4
    PAUSED = 5
    RUNNING = 6
    UNLOADED = 7
    STARTING = 8
    PROCESSED = 9
    ABORTING = 10

    @classmethod
    def from_api_value(cls, value: int | str) -> ExecutorEvent:
        """Parse either an integer or a .NET enum-name string."""
        if isinstance(value, int):
            try:
                return cls(value)
            except ValueError:
                return cls.UNDEFINED
        key = value.strip().lower().replace("_", "")
        int_val = _EXECUTOR_EVENT_STR_MAP.get(key)
        if int_val is not None:
            return cls(int_val)
        return cls.UNDEFINED


class ConnectionState(IntEnum):
    """Tracks the SDK's view of the instrument connection lifecycle."""

    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    DISCONNECTING = 3
    ERROR = 4


class WellOrder(Enum):
    """Well ordering for labware operations."""

    COL_ASC = "col-asc"
    COL_DESC = "col-desc"
    ROW_ASC = "row-asc"
    ROW_DESC = "row-desc"
    CUSTOM = "custom"


class PipArmSpeed(Enum):
    """Pipetting arm speed settings."""

    SLOW = "Slow"
    REDUCED = "Reduced"
    STANDARD = "Standard"


class ScanPositions(Enum):
    """Barcode scan position settings for autoload operations."""

    DETECTED = "?"
    ALL = "*"
    SKIP = ""


class Axis(IntEnum):
    """Axis identifiers for movement commands."""

    X = 0
    Y = 1
    Z = 2


class CoordinateMode(IntEnum):
    """Coordinate mode for movement commands."""

    ABSOLUTE = 0
    RELATIVE = 1


class LightColor(IntEnum):
    """Status light color options."""

    WHITE = 0
    RED = 1
    GREEN = 2
    BLUE = 3


class InteriorLightState(IntEnum):
    """Interior light state options (Vantage only)."""

    OFF = 0
    ON = 1
    BLINK = 2
    RAINBOW_DASH = 3


class CoreGripForce(IntEnum):
    """CO-RE gripper force levels."""

    MINIMUM = 0
    DEFAULT = 5
    MAXIMUM = 9


class AspirateMode(IntEnum):
    """Aspiration mode options."""

    NORMAL = 0
    CONSECUTIVE = 1
    ASPIRATE_ALL = 2


class CapacitiveLLD(IntEnum):
    """Capacitive liquid level detection sensitivity levels."""

    OFF = 0
    MAX = 1
    HIGH = 2
    MID = 3
    LOW = 4
    FROM_LABWARE = 5


class PressureLLD(IntEnum):
    """Pressure liquid level detection sensitivity levels."""

    OFF = 0
    MAX = 1
    HIGH = 2
    MID = 3
    LOW = 4
    FROM_LIQUID_CLASS = 5


class DispenseMode(IntEnum):
    """Dispense mode options."""

    JET_PART_VOLUME = 0
    JET_EMPTY_TIP = 1
    SURFACE_PART_VOLUME = 2
    SURFACE_EMPTY_TIP = 3
    DRAIN_TIP_JET_MODE = 4
    FROM_LIQUID_CLASS = 8
    BLOWOUT_TIP = 9


class SideTouch(IntEnum):
    """Side touch detection options."""

    OFF = 0
    ON = 1


class PostDispenseZ(IntEnum):
    """Post-dispense Z movement options."""

    MAX_Z = 0
    RACK_CLEAR = 1


class TadmMode(IntEnum):
    """TADM (Total Aspiration and Dispense Monitoring) operating mode.

    The ``enabled`` field of a :class:`~hamilton_venus.models.TadmSettings`.
    """

    OFF = 0
    RECORDING = 1
    MONITORING = 2


class TadmRecording(IntEnum):
    """Which TADM pressure curves the instrument persists.

    The ``recording`` field of a :class:`~hamilton_venus.models.TadmSettings`.
    """

    NONE = 0
    ERROR_CURVES_ONLY = 1
    ALL_CURVES = 2


class EjectMode(Enum):
    """Tip eject mode options."""

    WASTE = "waste"
    RETURN = "return"
    POSITIONS = "positions"
    TIP_POOL = "tipPool"


class LabwareType(StrEnum):
    """Labware categories, as ``labware.getLabwareTypes`` reports them (see
    ``docs/json_schemas_System.md``).

    No longer passed to ``labware.importLabwareDefinition``: VENUS works out the type from
    the imported file itself.
    """

    ADAPTER = "adapter"
    CARRIER = "carrier"
    LID = "lid"
    PLATE = "plate"
    RESERVOIR = "reservoir"
    TIP_RACK = "tip_rack"
    TUBE = "tube"
    TUBE_RACK = "tube_rack"


class PreAliquotDisposal(StrEnum):
    """Pre-aliquot disposal target for the ``add_reagent`` compound command.

    Selects where the pre-aliquot volume is dispensed before the destination
    dispense:

    * ``SOURCE`` — dispense the pre-aliquot back into the source labware.
    * ``WASTE`` — dispense the pre-aliquot into the deck's ``liquid_waste`` labware.
    """

    SOURCE = "source"
    WASTE = "waste"


class LastDilutionWaste(StrEnum):
    """Disposal strategy for the trailing excess in a serial-dilution series.

    After the final transfer dispense, each series' last dilution well holds
    ``diluent_volume + transfer_volume``.  This selects what happens to the
    trailing ``transfer_volume`` that would otherwise remain as excess:

    * ``NONE`` — leave the excess in the last well (final volume =
      ``diluent_volume + transfer_volume``); no extra command is issued.
    * ``TO_WASTE`` — aspirate the excess and dispense it into a physical waste
      location (``waste_location`` when given, otherwise the deck's fixed
      ``liquid_waste`` labware).  This reuses the mounted transfer tips to move
      the excess, so it is compatible with ``reuse_tips``.
    * ``WITH_TIP_EJECT`` — aspirate the excess and eject the tips with the
      liquid still inside, discarding it into the tip waste.
    """

    NONE = "none"
    TO_WASTE = "to_waste"
    WITH_TIP_EJECT = "with_tip_eject"


class MphPickupSide(IntEnum):
    """MPH96 tip pickup side options."""

    LEFT = 0
    RIGHT = 1
    REAR = 2
    FRONT = 3


class MphPickupMode(StrEnum):
    """MPH96 partial pickup mode options."""

    COLUMNS = "cols"
    ROWS = "rows"


class MPH96Pattern(IntEnum):
    """MPH96 head selection patterns."""

    ALL = 0
    ROWS = 1
    COLUMNS = 2
    QUADRANT = 3
    SINGLE = 4
    CUSTOM = 5


class MPH96PreAirAspirate(IntEnum):
    """MPH96 pre-air aspiration options."""

    DISABLED = 0
    BLOWOUT_MAX = 1
    ASPIRATE_MAX = 2
    CUSTOM_VOLUME = 3


class CoreGripType(IntEnum):
    """Core grip type options."""

    STANDARD = 0
    DEEP = 1


class QCGType(IntEnum):
    """QCG type options."""

    QCG = 0
    QCG_DEEP = 1
    QCG_MID = 2


class PlaceRotation(IntEnum):
    """Plate rotation applied by iSWAP when placing labware.

    Maps the intuitive rotation angle to the integer value required by the API.
    """

    DEGREES_0 = 1
    DEGREES_90 = 2
    DEGREES_180 = 3
    DEGREES_270 = 4


class CMOrientation(IntEnum):
    """iSWAP complex movement orientation: the direction the iSWAP faces,
    toward the hotel. A put facing another way than the get gripped needs the
    matching place rotation, since the labware turns with the iSWAP."""

    FRONT = 1
    RIGHT = 2
    REAR = 3
    LEFT = 4


class GripInverse(Enum):
    """iSWAP grip orientation.

    Selects which side of the labware the gripper approaches from. For labware
    at rotation 0, a narrow grip faces left (``GRIP_FROM_RIGHT``) or right
    (``GRIP_FROM_LEFT``); a wide grip faces the back or the front.
    Maps the human-readable description to the boolean value required by the API.
    """

    GRIP_FROM_LEFT = True
    GRIP_FROM_RIGHT = False


class TrackedLabwareType(Enum):
    """Labware types reported by sample tracking (``labwareType``), usable as filters."""

    TEMPLATE = "Template"
    RACK = "Rack"
    WELL = "Well"
    TIP_RACK = "Tip Rack"
    RESERVOIR_RACK = "Reservoir Rack"


class TeachingDirection(IntEnum):
    """Wall a ``teaching.1mL.measureXY`` search moves toward (the ``direction`` wire value).

    ``PLUS_X`` searches for the right wall, ``MINUS_X`` the left, ``PLUS_Y`` the back
    and ``MINUS_Y`` the front.
    """

    PLUS_X = 1
    MINUS_X = 2
    PLUS_Y = 3
    MINUS_Y = 4


class TeachingMeasureStatus(IntEnum):
    """Result code (``status.code``) of a teaching wall or Z-height search.

    ``NOT_FOUND``: no Z stall inside the search range. ``FOUND``: the wall or bottom
    was found. ``FOUND_EARLY``: the needle stalled before the search height, i.e.
    something is higher than expected (labware taller or offset, an obstacle).
    """

    NOT_FOUND = 0
    FOUND = 1
    FOUND_EARLY = 2


class TiltPivotPoint(StrEnum):
    """Hinge line a labware item is tilted about for ``tilt_labware``.

    ``LEFT_EDGE`` pivots about the labware's left short side (the MFX Tilt Module
    hinge), so a positive angle raises the right side. ``CENTER`` pivots about the
    middle of the footprint, so the right half rises and the left half drops.
    """

    LEFT_EDGE = "LeftEdge"
    CENTER = "Center"


class TiltWellPosition(StrEnum):
    """Where in each well ``tilt_labware`` aims on a tilted plate.

    ``CENTER`` keeps the well centre. ``DEEPEST_POINT`` / ``HIGHEST_POINT`` aim as
    close to the low / high wall as one tip fits, given the tip, the tip end height
    and the wall margins (see :mod:`hamilton_venus.tilt_clearance`). At 0 degrees
    the well centre is always used.
    """

    CENTER = "Center"
    DEEPEST_POINT = "DeepestPoint"
    HIGHEST_POINT = "HighestPoint"


class SplitChannelType(StrEnum):
    """Which channels a ``split_wells`` split is for; also sets the slot pitch."""

    ONE_ML = "1mL"  # 9 mm pitch
    FIVE_ML = "5mL"  # 18 mm pitch


class SplitWellFit(StrEnum):
    """What ``split_wells`` gives up when a well is narrow where the tips go.

    ``POSITION`` keeps the aim: at the centre it uses as many channels as fit
    there; at a wall (a tilted well's deepest or highest point) it uses as many
    channels as the well holds, as close to that wall as they fit. ``MAX_CHANNELS``
    uses the most channels the well can hold, moving away from the aim only as far
    as that needs. ``split_wells`` also takes a channel count (``int``) for exactly
    that many channels.
    """

    POSITION = "position"
    MAX_CHANNELS = "max_channels"


class PumpDirection(IntEnum):
    """Hamilton Media Fill Module pump motor direction -- the vendor HSL's
    ``DIRECTION_COUNTER_CLOCKWISE`` / ``DIRECTION_CLOCKWISE``. Every pump starts
    each run counter-clockwise."""

    COUNTER_CLOCKWISE = 0
    CLOCKWISE = 1


__all__ = [
    "AspirateMode",
    "Axis",
    "CMOrientation",
    "CapacitiveLLD",
    "ConnectionState",
    "CoordinateMode",
    "CoreGripForce",
    "CoreGripType",
    "DispenseMode",
    "EjectMode",
    "ExecutorEvent",
    "GripInverse",
    "InteriorLightState",
    "LastDilutionWaste",
    "LightColor",
    "MPH96Pattern",
    "MPH96PreAirAspirate",
    "MphPickupMode",
    "MphPickupSide",
    "PipArmSpeed",
    "PlaceRotation",
    "PostDispenseZ",
    "PreAliquotDisposal",
    "PressureLLD",
    "PumpDirection",
    "QCGType",
    "RunState",
    "ScanPositions",
    "SideTouch",
    "SplitChannelType",
    "SplitWellFit",
    "TeachingDirection",
    "TeachingMeasureStatus",
    "TiltPivotPoint",
    "TiltWellPosition",
    "TrackedLabwareType",
    "WellOrder",
]

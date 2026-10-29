"""Error-vocabulary enumerations for the Hamilton VENUS Python SDK.

Contains recovery-action classifiers and all per-operation error-type enums.
Parameter enums (AspirateMode, Axis, etc.) live in :mod:`hamilton_venus.models.enums`.
"""

from __future__ import annotations

from enum import StrEnum


class _ErrorTypeMixin:
    """Mixin that gives error-type enums identity-based hashing and equality.

    All error-type enums share the same string values (e.g. ``"execution"``,
    ``"hardware"``) across different classes.  Without this mixin the default
    ``str.__hash__`` / ``str.__eq__`` semantics would cause every member whose
    ``.value == "execution"`` to hash and compare equal regardless of which
    enum class it belongs to, collapsing the ``ALLOWED_ACTIONS`` dict from
    ~230 entries down to ~37. This mixin implements identity-based comparison
    using type(self) to ensure that enums from different classes are treated
    as distinct dictionary keys even when they share the same string value.
    """

    value: str

    def __hash__(self) -> int:
        return hash((type(self), self.value))

    def __eq__(self, other: object) -> bool:
        if type(self) is type(other):
            return self.value == getattr(other, "value", None)
        return NotImplemented


class ActionKind(StrEnum):
    """Recovery action classification: resolves error vs performs action."""

    RECOVERY = "recovery"
    ACTION = "action"


class RecoveryAction(StrEnum):
    """SDK-level recovery/action vocabulary with kind metadata."""

    kind: ActionKind

    def __new__(cls, value: str, kind: ActionKind = ActionKind.RECOVERY) -> RecoveryAction:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.kind = kind
        return obj

    CANCEL = ("cancel", ActionKind.RECOVERY)
    ABORT = ("abort", ActionKind.RECOVERY)
    BOTTOM = ("bottom", ActionKind.RECOVERY)
    EXCLUDE = ("exclude", ActionKind.RECOVERY)
    CONTINUE = ("continue", ActionKind.RECOVERY)
    REPEAT = ("repeat", ActionKind.RECOVERY)
    WASTE = ("waste", ActionKind.RECOVERY)
    NEXT = ("next", ActionKind.RECOVERY)
    AIR = ("air", ActionKind.RECOVERY)
    AVAILABLE = ("available", ActionKind.RECOVERY)
    BARCODE = ("barcode", ActionKind.RECOVERY)
    INITIALIZE = ("initialize", ActionKind.ACTION)


class TipPickupError(_ErrorTypeMixin, StrEnum):
    """1000µL channel tip pickup error types."""

    EXECUTION = "execution"
    HARDWARE = "hardware"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    TIP_PRESENT = "tip_present"


class TipEjectError(_ErrorTypeMixin, StrEnum):
    """1000µL channel tip eject error types."""

    EXECUTION = "execution"
    HARDWARE = "hardware"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"


class AspirateError(_ErrorTypeMixin, StrEnum):
    """1000µL channel aspiration error types."""

    ANTI_DROP = "anti_drop"
    CLOT = "clot"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    IMPROPER = "improper"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    UNEXPECTED_CLLD = "unexpected_clld"


class DispenseError(_ErrorTypeMixin, StrEnum):
    """1000µL channel dispense error types."""

    ANTI_DROP = "anti_drop"
    CLOT = "clot"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    IMPROPER = "improper"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    NOT_ASPIRATED = "not_aspirated"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    PRESSURE_LLD = "pressure_lld"
    UNEXPECTED_CLLD = "unexpected_clld"


class DispenseFlyError(_ErrorTypeMixin, StrEnum):
    """1000µL channel dispense fly error types."""

    ANTI_DROP = "anti_drop"
    HARDWARE = "hardware"
    IMPROPER_DISP = "improper_disp"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"
    TADM_LOWER = "tadm_lower"
    TADM_UPPER = "tadm_upper"


class Aspirate2ndPhaseError(_ErrorTypeMixin, StrEnum):
    """1000µL channel 2nd phase aspiration error types."""

    ANTI_DROP = "anti_drop"
    CLOT = "clot"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    IMPROPER = "improper"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    UNEXPECTED_CLLD = "unexpected_clld"


class MoveToPositionError(_ErrorTypeMixin, StrEnum):
    """Movement error types."""

    HARDWARE = "hardware"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"


class NeedleWashError(_ErrorTypeMixin, StrEnum):
    """Needle wash error types (STAR only)."""

    HARDWARE = "hardware"
    OTHER = "other"
    WASH_LIQUID = "wash_liquid"


class EasyAspirateError(_ErrorTypeMixin, StrEnum):
    """Easy aspiration error types."""

    ANTI_DROP = "anti_drop"
    BARCODE = "barcode"
    CLOT = "clot"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    IMPROPER = "improper"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    LOADING_TRAY = "loading_tray"
    NOT_DETECTED = "not_detected"
    NOT_EXECUTED = "not_executed"
    NO_CARRIER = "no_carrier"
    NO_CARRIER_BC = "no_carrier_bc"
    NO_TIP = "no_tip"
    OTHER = "other"
    TIP_PRESENT = "tip_present"
    UNEXPECTED_CLLD = "unexpected_clld"
    WASH_LIQUID = "wash_liquid"
    WRONG_CARRIER = "wrong_carrier"


class EasyDispenseError(_ErrorTypeMixin, StrEnum):
    """Easy dispense error types."""

    ANTI_DROP = "anti_drop"
    CLOT = "clot"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    IMPROPER = "improper"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    NOT_ASPIRATED = "not_aspirated"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    PRESSURE_LLD = "pressure_lld"
    UNEXPECTED_CLLD = "unexpected_clld"
    WASH_LIQUID = "wash_liquid"


class COREGripTransportError(_ErrorTypeMixin, StrEnum):
    """CO-RE gripper transport error types."""

    BARCODE = "barcode"
    BARCODE_MASK = "barcode_mask"
    BARCODE_UNIQUE = "barcode_unique"
    BARCODE_USED = "barcode_used"
    DELIMITER = "delimiter"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    LABWARE_NOT_FOUND = "labware_not_found"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    TIP_PRESENT = "tip_present"


class ZSwapGetPlateError(_ErrorTypeMixin, StrEnum):
    """Z-Swap get plate error types."""

    EXECUTION = "execution"
    HARDWARE = "hardware"
    LABWARE_NOT_FOUND = "labware_not_found"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    TIP_PRESENT = "tip_present"


class ZSwapPlacePlateError(_ErrorTypeMixin, StrEnum):
    """Z-Swap place plate error types."""

    HARDWARE = "hardware"
    LABWARE_NOT_FOUND = "labware_not_found"
    OTHER = "other"


class ZSwapReadBarcodeError(_ErrorTypeMixin, StrEnum):
    """Z-Swap read barcode error types."""

    BARCODE = "barcode"
    BARCODE_MASK = "barcode_mask"
    BARCODE_UNIQUE = "barcode_unique"
    BARCODE_USED = "barcode_used"
    DELIMITER = "delimiter"
    HARDWARE = "hardware"
    OTHER = "other"


class Head96AspirateError(_ErrorTypeMixin, StrEnum):
    """CO-RE 96 head aspiration error types."""

    HARDWARE = "hardware"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"
    TADM_LOWER = "tadm_lower"
    TADM_UPPER = "tadm_upper"


class Head96DispenseError(_ErrorTypeMixin, StrEnum):
    """CO-RE 96 head dispense error types."""

    HARDWARE = "hardware"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"
    PRESSURE_LLD = "pressure_lld"
    TADM_LOWER = "tadm_lower"
    TADM_UPPER = "tadm_upper"


class Head96TipPickUpError(_ErrorTypeMixin, StrEnum):
    """CO-RE 96 head tip pickup error types."""

    EXECUTION = "execution"
    HARDWARE = "hardware"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    TIP_PRESENT = "tip_present"


class Head96TipEjectError(_ErrorTypeMixin, StrEnum):
    """CO-RE 96 head tip eject error types."""

    EXECUTION = "execution"
    HARDWARE = "hardware"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"


class Head96MoveError(_ErrorTypeMixin, StrEnum):
    """CO-RE 96 head movement error types."""

    HARDWARE = "hardware"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"


class Head96WashError(_ErrorTypeMixin, StrEnum):
    """CO-RE 96 head wash error types."""

    HARDWARE = "hardware"
    OTHER = "other"
    WASH_LIQUID = "wash_liquid"


class Head96EmptyWasherError(_ErrorTypeMixin, StrEnum):
    """CO-RE 96 head empty washer error types."""

    HARDWARE = "hardware"
    OTHER = "other"


class EasyHead96AspirateError(_ErrorTypeMixin, StrEnum):
    """Easy CO-RE 96 head aspiration error types."""

    HARDWARE = "hardware"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"
    TADM_LOWER = "tadm_lower"
    TADM_UPPER = "tadm_upper"


class EasyHead96DispenseError(_ErrorTypeMixin, StrEnum):
    """Easy CO-RE 96 head dispense error types."""

    HARDWARE = "hardware"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"
    PRESSURE_LLD = "pressure_lld"
    TADM_LOWER = "tadm_lower"
    TADM_UPPER = "tadm_upper"


class XLZSwapGetPlateError(_ErrorTypeMixin, StrEnum):
    """XL Z-Swap get plate error types."""

    EXECUTION = "execution"
    HARDWARE = "hardware"
    LABWARE_NOT_FOUND = "labware_not_found"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    TIP_PRESENT = "tip_present"


class XLZSwapPlacePlateError(_ErrorTypeMixin, StrEnum):
    """XL Z-Swap place plate error types."""

    HARDWARE = "hardware"
    LABWARE_NOT_FOUND = "labware_not_found"
    OTHER = "other"


class XLZSwapReadBarcodeError(_ErrorTypeMixin, StrEnum):
    """XL Z-Swap read barcode error types."""

    BARCODE = "barcode"
    BARCODE_MASK = "barcode_mask"
    BARCODE_UNIQUE = "barcode_unique"
    BARCODE_USED = "barcode_used"
    DELIMITER = "delimiter"
    HARDWARE = "hardware"
    OTHER = "other"


class AutoloadError(_ErrorTypeMixin, StrEnum):
    """Autoload/IDL error types."""

    BARCODE = "barcode"
    BARCODE_MASK = "barcode_mask"
    BARCODE_UNIQUE = "barcode_unique"
    BARCODE_USED = "barcode_used"
    CALIBRATE = "calibrate"
    COLLISION_RISK = "collision_risk"
    DELIMITER = "delimiter"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    LOADING_TRAY = "loading_tray"
    NO_CARRIER = "no_carrier"
    NO_CARRIER_BC = "no_carrier_bc"
    NO_LABWARE = "no_labware"
    NOT_DETECTED = "not_detected"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"
    UNEXPECTED_LW = "unexpected_lw"
    WRONG_CARRIER = "wrong_carrier"
    WRONG_LABWARE = "wrong_labware"


class GripperError(_ErrorTypeMixin, StrEnum):
    """iSWAP/IPG gripper error types."""

    BARCODE = "barcode"
    BARCODE_MASK = "barcode_mask"
    BARCODE_UNIQUE = "barcode_unique"
    BARCODE_USED = "barcode_used"
    DELIMITER = "delimiter"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    LABWARE_LOST = "labware_lost"
    LABWARE_NOT_FOUND = "labware_not_found"
    LABWARE_PRESENT = "labware_present"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"


class InitializeError(_ErrorTypeMixin, StrEnum):
    """Module initialization error types."""

    COLLISION_RISK = "collision_risk"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"
    TEMPERATURE = "temperature"


class CoverError(_ErrorTypeMixin, StrEnum):
    """Front cover lock error types."""

    COVER_OPEN = "cover_open"
    ILLEGAL_INTERVENTION = "illegal_intervention"
    LOADING_TRAY = "loading_tray"
    OTHER = "other"


class MagPipError(_ErrorTypeMixin, StrEnum):
    """MagPip channel error types (VANTAGE only)."""

    ANTI_DROP = "anti_drop"
    CLOT = "clot"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    IMPROPER = "improper"
    IMPROPER_DISP = "improper_disp"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    NOT_ASPIRATED = "not_aspirated"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    TADM_LOWER = "tadm_lower"
    TADM_UPPER = "tadm_upper"
    TIP_PRESENT = "tip_present"
    UNEXPECTED_CLLD = "unexpected_clld"


class XLTipPickupError(_ErrorTypeMixin, StrEnum):
    """5mL (XL) channel tip pickup error types."""

    EXECUTION = "execution"
    HARDWARE = "hardware"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    TIP_PRESENT = "tip_present"


class XLTipEjectError(_ErrorTypeMixin, StrEnum):
    """5mL (XL) channel tip eject error types."""

    EXECUTION = "execution"
    HARDWARE = "hardware"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"


class XLAspirateError(_ErrorTypeMixin, StrEnum):
    """5mL (XL) channel aspiration error types."""

    ANTI_DROP = "anti_drop"
    CLOT = "clot"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    IMPROPER = "improper"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    UNEXPECTED_CLLD = "unexpected_clld"


class XLDispenseError(_ErrorTypeMixin, StrEnum):
    """5mL (XL) channel dispense error types."""

    ANTI_DROP = "anti_drop"
    CLOT = "clot"
    EXECUTION = "execution"
    HARDWARE = "hardware"
    IMPROPER = "improper"
    INSUFFICIENT = "insufficient"
    LIQUID_LEVEL = "liquid_level"
    NOT_ASPIRATED = "not_aspirated"
    NOT_EXECUTED = "not_executed"
    NO_TIP = "no_tip"
    OTHER = "other"
    PRESSURE_LLD = "pressure_lld"
    UNEXPECTED_CLLD = "unexpected_clld"


class XLDispenseFlyError(_ErrorTypeMixin, StrEnum):
    """5mL (XL) channel dispense fly error types."""

    ANTI_DROP = "anti_drop"
    HARDWARE = "hardware"
    IMPROPER_DISP = "improper_disp"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"
    TADM_LOWER = "tadm_lower"
    TADM_UPPER = "tadm_upper"


class XLMoveToPositionError(_ErrorTypeMixin, StrEnum):
    """5mL (XL) channel movement error types."""

    HARDWARE = "hardware"
    NOT_EXECUTED = "not_executed"
    OTHER = "other"


class OperationCategory(StrEnum):
    """High-level category of the instrument operation that raised an error.

    Each member corresponds to a distinct pipetting, transport, or system
    operation performed by a Hamilton STAR or Vantage instrument. The value
    is a lowercase snake-case string suitable for use as a dictionary key or
    log tag.

    These categories are **STAR/Vantage-specific**. A Nimbus classifier would
    either reuse a subset of these members or define its own enum; see the
    ``_error_classifier`` module docstring for extension guidance.

    .. important:: Field-name contract with ``ErrorProfile``

        Each member's string value is **identical** to the name of the
        corresponding field on :class:`~hamilton_venus.error_handling.ErrorProfile`.
        For example, ``OperationCategory.ASPIRATE.value == "aspirate"`` and
        ``ErrorProfile`` has a field named ``aspirate``.  The resolver
        uses ``getattr(profile, category.value)`` to look up the per-operation
        dict.  When adding a new category, the ``ErrorProfile`` field **must**
        use the same snake_case name, otherwise the resolver will raise
        ``AttributeError`` at runtime.
    """

    TIP_PICKUP = "tip_pickup"
    TIP_EJECT = "tip_eject"
    ASPIRATE = "aspirate"
    DISPENSE = "dispense"
    HEAD96_ASPIRATE = "head96_aspirate"
    HEAD96_DISPENSE = "head96_dispense"
    HEAD96_TIP_PICKUP = "head96_tip_pickup"
    AUTOLOAD = "autoload"
    GRIPPER = "gripper"
    INITIALIZE = "initialize"
    DISPENSE_FLY = "dispense_fly"
    ASPIRATE_2ND_PHASE = "aspirate_2nd_phase"
    NEEDLE_WASH = "needle_wash"
    EASY_ASPIRATE = "easy_aspirate"
    EASY_DISPENSE = "easy_dispense"
    CORE_GRIP_TRANSPORT = "core_grip_transport"
    ZSWAP_GET_PLATE = "zswap_get_plate"
    ZSWAP_READ_BARCODE = "zswap_read_barcode"
    ZSWAP_PLACE_PLATE = "zswap_place_plate"
    MOVE_TO_POSITION = "move_to_position"
    XL_TIP_PICKUP = "xl_tip_pickup"
    XL_TIP_EJECT = "xl_tip_eject"
    XL_ASPIRATE = "xl_aspirate"
    XL_DISPENSE = "xl_dispense"
    XL_DISPENSE_FLY = "xl_dispense_fly"
    XL_MOVE_TO_POSITION = "xl_move_to_position"
    LOCK_FRONT_COVER = "lock_front_cover"
    MAGPIP = "magpip"
    HEAD96_TIP_EJECT = "head96_tip_eject"
    HEAD96_MOVE = "head96_move"
    HEAD96_WASH = "head96_wash"
    HEAD96_EMPTY_WASHER = "head96_empty_washer"
    EASY_HEAD96_ASPIRATE = "easy_head96_aspirate"
    EASY_HEAD96_DISPENSE = "easy_head96_dispense"
    XL_ZSWAP_GET_PLATE = "xl_zswap_get_plate"
    XL_ZSWAP_PLACE_PLATE = "xl_zswap_place_plate"
    XL_ZSWAP_READ_BARCODE = "xl_zswap_read_barcode"


__all__ = [
    "ActionKind",
    "Aspirate2ndPhaseError",
    "AspirateError",
    "AutoloadError",
    "COREGripTransportError",
    "CoverError",
    "DispenseError",
    "DispenseFlyError",
    "EasyAspirateError",
    "EasyDispenseError",
    "GripperError",
    "Head96AspirateError",
    "Head96DispenseError",
    "Head96TipPickUpError",
    "InitializeError",
    "MagPipError",
    "MoveToPositionError",
    "NeedleWashError",
    "OperationCategory",
    "RecoveryAction",
    "TipEjectError",
    "TipPickupError",
    "XLAspirateError",
    "XLDispenseError",
    "XLDispenseFlyError",
    "XLMoveToPositionError",
    "XLTipEjectError",
    "XLTipPickupError",
    "XLZSwapGetPlateError",
    "XLZSwapPlacePlateError",
    "XLZSwapReadBarcodeError",
    "ZSwapGetPlateError",
    "ZSwapPlacePlateError",
    "ZSwapReadBarcodeError",
]

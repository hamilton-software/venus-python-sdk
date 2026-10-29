"""Allowed recovery actions for tip handling operations (pickup and eject).

This module defines the valid recovery actions for TipPickupError, TipEjectError,
and variants (Head96, XL) across all tip-handling operations.
"""

from hamilton_venus.models.error_types import (
    Head96TipEjectError,
    Head96TipPickUpError,
    RecoveryAction,
    TipEjectError,
    TipPickupError,
    XLTipEjectError,
    XLTipPickupError,
)

ACTIONS = {
    # 1000µL Channel - Tip Pickup
    TipPickupError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    TipPickupError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    TipPickupError.NOT_EXECUTED: {
        RecoveryAction.ABORT,
        RecoveryAction.EXCLUDE,
        RecoveryAction.REPEAT,
    },
    TipPickupError.NO_TIP: {
        RecoveryAction.ABORT,
        RecoveryAction.EXCLUDE,
        RecoveryAction.NEXT,
        RecoveryAction.REPEAT,
    },
    TipPickupError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    TipPickupError.TIP_PRESENT: {RecoveryAction.ABORT, RecoveryAction.EXCLUDE, RecoveryAction.WASTE},
    # 1000µL Channel - Tip Eject
    TipEjectError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE},
    TipEjectError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE},
    TipEjectError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE},
    TipEjectError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE},
    # 5mL (XL) Channel - Tip Pickup
    XLTipPickupError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    XLTipPickupError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    XLTipPickupError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.EXCLUDE, RecoveryAction.REPEAT},
    XLTipPickupError.NO_TIP: {
        RecoveryAction.ABORT,
        RecoveryAction.EXCLUDE,
        RecoveryAction.NEXT,
        RecoveryAction.REPEAT,
    },
    XLTipPickupError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    XLTipPickupError.TIP_PRESENT: {RecoveryAction.ABORT, RecoveryAction.EXCLUDE, RecoveryAction.WASTE},
    # 5mL (XL) Channel - Tip Eject
    XLTipEjectError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE, RecoveryAction.REPEAT},
    XLTipEjectError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE, RecoveryAction.REPEAT},
    XLTipEjectError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE, RecoveryAction.REPEAT},
    XLTipEjectError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    # CO-RE 96 Head - Tip Pickup
    Head96TipPickUpError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    Head96TipPickUpError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    Head96TipPickUpError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.EXCLUDE, RecoveryAction.REPEAT},
    Head96TipPickUpError.NO_TIP: {
        RecoveryAction.ABORT,
        RecoveryAction.EXCLUDE,
        RecoveryAction.NEXT,
        RecoveryAction.REPEAT,
    },
    Head96TipPickUpError.OTHER: {
        RecoveryAction.ABORT,
        RecoveryAction.CONTINUE,
        RecoveryAction.REPEAT,
    },
    Head96TipPickUpError.TIP_PRESENT: {RecoveryAction.ABORT, RecoveryAction.EXCLUDE},
    # CO-RE 96 Head - Tip Eject
    Head96TipEjectError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE, RecoveryAction.REPEAT},
    Head96TipEjectError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE, RecoveryAction.REPEAT},
    Head96TipEjectError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE, RecoveryAction.REPEAT},
    Head96TipEjectError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
}

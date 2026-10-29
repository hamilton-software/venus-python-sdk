"""Allowed recovery actions for system and utility operations.

This module defines the valid recovery actions for system operations including
initialization, autoload/IDL, movement, needle wash, and cover operations.
"""

from hamilton_venus.models.error_types import (
    AutoloadError,
    CoverError,
    Head96EmptyWasherError,
    Head96MoveError,
    Head96WashError,
    InitializeError,
    MoveToPositionError,
    NeedleWashError,
    RecoveryAction,
    XLMoveToPositionError,
)

ACTIONS = {
    # Initialize
    InitializeError.COLLISION_RISK: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    InitializeError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    InitializeError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE, RecoveryAction.REPEAT},
    InitializeError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    InitializeError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    InitializeError.TEMPERATURE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    # Autoload/IDL
    AutoloadError.BARCODE: {
        RecoveryAction.ABORT,
        RecoveryAction.BARCODE,
        RecoveryAction.CONTINUE,
        RecoveryAction.REPEAT,
    },
    AutoloadError.BARCODE_MASK: {RecoveryAction.ABORT, RecoveryAction.CONTINUE},
    AutoloadError.BARCODE_UNIQUE: {RecoveryAction.ABORT, RecoveryAction.CONTINUE},
    AutoloadError.BARCODE_USED: {RecoveryAction.ABORT, RecoveryAction.CONTINUE},
    AutoloadError.CALIBRATE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    AutoloadError.COLLISION_RISK: {
        RecoveryAction.ABORT,
        RecoveryAction.REPEAT,
    },
    AutoloadError.DELIMITER: {RecoveryAction.ABORT},
    AutoloadError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    AutoloadError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    AutoloadError.LOADING_TRAY: {RecoveryAction.ABORT},
    AutoloadError.NOT_DETECTED: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    AutoloadError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    AutoloadError.NO_CARRIER: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    AutoloadError.NO_CARRIER_BC: {
        RecoveryAction.ABORT,
        RecoveryAction.BARCODE,
        RecoveryAction.CONTINUE,
        RecoveryAction.REPEAT,
    },
    AutoloadError.NO_LABWARE: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    AutoloadError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    AutoloadError.UNEXPECTED_LW: {RecoveryAction.ABORT, RecoveryAction.CONTINUE},
    AutoloadError.WRONG_CARRIER: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    AutoloadError.WRONG_LABWARE: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    # Movement (1000µL)
    MoveToPositionError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    MoveToPositionError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    MoveToPositionError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    # Movement (5mL/XL)
    XLMoveToPositionError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    XLMoveToPositionError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    XLMoveToPositionError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    # Needle Wash (STAR only)
    NeedleWashError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE, RecoveryAction.REPEAT},
    NeedleWashError.OTHER: {RecoveryAction.ABORT},
    NeedleWashError.WASH_LIQUID: {RecoveryAction.ABORT, RecoveryAction.INITIALIZE, RecoveryAction.REPEAT},
    # Front Cover Lock
    CoverError.COVER_OPEN: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    CoverError.ILLEGAL_INTERVENTION: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    CoverError.LOADING_TRAY: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    CoverError.OTHER: {RecoveryAction.ABORT},
    # CO-RE 96 Head - Movement
    Head96MoveError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    Head96MoveError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    Head96MoveError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    # CO-RE 96 Head - Wash
    Head96WashError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    Head96WashError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    Head96WashError.WASH_LIQUID: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    # CO-RE 96 Head - Empty Washer
    Head96EmptyWasherError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    Head96EmptyWasherError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
}

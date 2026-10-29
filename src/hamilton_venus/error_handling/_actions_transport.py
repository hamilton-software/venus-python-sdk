"""Allowed recovery actions for transport and gripper operations.

This module defines the valid recovery actions for transport operations including
COREGripTransport, ZSwap operations, and iSWAP/IPG gripper operations.
"""

from hamilton_venus.models.error_types import (
    COREGripTransportError,
    GripperError,
    RecoveryAction,
    XLZSwapGetPlateError,
    XLZSwapPlacePlateError,
    XLZSwapReadBarcodeError,
    ZSwapGetPlateError,
    ZSwapPlacePlateError,
    ZSwapReadBarcodeError,
)

ACTIONS = {
    # CO-RE Grip Transport
    COREGripTransportError.BARCODE: {RecoveryAction.ABORT, RecoveryAction.BARCODE, RecoveryAction.CONTINUE},
    COREGripTransportError.BARCODE_MASK: {RecoveryAction.ABORT, RecoveryAction.EXCLUDE, RecoveryAction.CONTINUE},
    COREGripTransportError.BARCODE_UNIQUE: {
        RecoveryAction.ABORT,
        RecoveryAction.EXCLUDE,
        RecoveryAction.CONTINUE,
    },
    COREGripTransportError.BARCODE_USED: {
        RecoveryAction.ABORT,
        RecoveryAction.EXCLUDE,
        RecoveryAction.CONTINUE,
    },
    COREGripTransportError.DELIMITER: {RecoveryAction.ABORT, RecoveryAction.EXCLUDE},
    COREGripTransportError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    COREGripTransportError.HARDWARE: {RecoveryAction.ABORT},
    COREGripTransportError.LABWARE_NOT_FOUND: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    COREGripTransportError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    COREGripTransportError.NO_TIP: {RecoveryAction.ABORT},
    COREGripTransportError.TIP_PRESENT: {RecoveryAction.ABORT, RecoveryAction.WASTE},
    COREGripTransportError.OTHER: {RecoveryAction.ABORT},
    # Z-Swap Get Plate
    ZSwapGetPlateError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    ZSwapGetPlateError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    ZSwapGetPlateError.LABWARE_NOT_FOUND: {RecoveryAction.ABORT},
    ZSwapGetPlateError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    ZSwapGetPlateError.NO_TIP: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    ZSwapGetPlateError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    ZSwapGetPlateError.TIP_PRESENT: {RecoveryAction.ABORT, RecoveryAction.EXCLUDE, RecoveryAction.WASTE},
    # Z-Swap Read Barcode
    ZSwapReadBarcodeError.BARCODE: {RecoveryAction.ABORT, RecoveryAction.BARCODE, RecoveryAction.CONTINUE},
    ZSwapReadBarcodeError.BARCODE_MASK: {
        RecoveryAction.ABORT,
        RecoveryAction.EXCLUDE,
        RecoveryAction.CONTINUE,
    },
    ZSwapReadBarcodeError.BARCODE_UNIQUE: {
        RecoveryAction.ABORT,
        RecoveryAction.EXCLUDE,
        RecoveryAction.CONTINUE,
    },
    ZSwapReadBarcodeError.BARCODE_USED: {
        RecoveryAction.ABORT,
        RecoveryAction.EXCLUDE,
        RecoveryAction.CONTINUE,
    },
    ZSwapReadBarcodeError.DELIMITER: {RecoveryAction.ABORT, RecoveryAction.EXCLUDE},
    ZSwapReadBarcodeError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    ZSwapReadBarcodeError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    # Z-Swap Place Plate
    ZSwapPlacePlateError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    ZSwapPlacePlateError.LABWARE_NOT_FOUND: {RecoveryAction.ABORT},
    ZSwapPlacePlateError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    # XL Z-Swap Get Plate
    XLZSwapGetPlateError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    XLZSwapGetPlateError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    XLZSwapGetPlateError.LABWARE_NOT_FOUND: {RecoveryAction.ABORT},
    XLZSwapGetPlateError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    XLZSwapGetPlateError.NO_TIP: {RecoveryAction.ABORT, RecoveryAction.EXCLUDE},
    XLZSwapGetPlateError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    XLZSwapGetPlateError.TIP_PRESENT: {RecoveryAction.ABORT, RecoveryAction.EXCLUDE},
    # XL Z-Swap Place Plate
    XLZSwapPlacePlateError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    XLZSwapPlacePlateError.LABWARE_NOT_FOUND: {RecoveryAction.ABORT},
    XLZSwapPlacePlateError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    # XL Z-Swap Read Barcode
    XLZSwapReadBarcodeError.BARCODE: {RecoveryAction.ABORT, RecoveryAction.BARCODE, RecoveryAction.CONTINUE},
    XLZSwapReadBarcodeError.BARCODE_MASK: {RecoveryAction.ABORT, RecoveryAction.CONTINUE},
    XLZSwapReadBarcodeError.BARCODE_UNIQUE: {RecoveryAction.ABORT, RecoveryAction.CONTINUE},
    XLZSwapReadBarcodeError.BARCODE_USED: {RecoveryAction.ABORT, RecoveryAction.CONTINUE},
    XLZSwapReadBarcodeError.DELIMITER: {RecoveryAction.ABORT},
    XLZSwapReadBarcodeError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    XLZSwapReadBarcodeError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
    # iSWAP/IPG Gripper
    GripperError.BARCODE: {RecoveryAction.ABORT, RecoveryAction.BARCODE, RecoveryAction.CONTINUE},
    GripperError.BARCODE_MASK: {RecoveryAction.ABORT, RecoveryAction.CONTINUE},
    GripperError.BARCODE_UNIQUE: {RecoveryAction.ABORT, RecoveryAction.CONTINUE},
    GripperError.BARCODE_USED: {RecoveryAction.ABORT, RecoveryAction.CONTINUE},
    GripperError.DELIMITER: {RecoveryAction.ABORT},
    GripperError.EXECUTION: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    GripperError.HARDWARE: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    GripperError.LABWARE_LOST: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    GripperError.LABWARE_NOT_FOUND: {RecoveryAction.ABORT},
    GripperError.LABWARE_PRESENT: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    GripperError.NOT_EXECUTED: {RecoveryAction.ABORT, RecoveryAction.REPEAT},
    GripperError.OTHER: {RecoveryAction.ABORT, RecoveryAction.CONTINUE, RecoveryAction.REPEAT},
}

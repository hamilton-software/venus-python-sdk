"""Allowed recovery actions mapping for each error type.

This module provides the complete set of valid recovery actions for every
error condition across all instrument operations.

The ALLOWED_ACTIONS mapping is organized into logical categories:
- Tip handling (pickup/eject) for 1000µL, 5mL, and 96-head channels
- Aspiration for 1000µL, 5mL, 96-head, and autoload channels
- Dispensing for 1000µL, 5mL, 96-head, MagPip, and autoload channels
- Transport and gripper (Z-Swap, CORE Grip, iSWAP/IPG)
- System operations (initialize, autoload, movement, wash, cover)

Each category is defined in a dedicated module to improve maintainability and
reduce code duplication. This separation makes it easier to review, modify, and
extend error handling rules specific to each operation type.
"""

from typing import Any

from hamilton_venus.error_handling._actions_aspirate import ACTIONS as ASPIRATE_ACTIONS
from hamilton_venus.error_handling._actions_dispense import ACTIONS as DISPENSE_ACTIONS
from hamilton_venus.error_handling._actions_system import ACTIONS as SYSTEM_ACTIONS
from hamilton_venus.error_handling._actions_tip_handling import (
    ACTIONS as TIP_HANDLING_ACTIONS,
)
from hamilton_venus.error_handling._actions_transport import (
    ACTIONS as TRANSPORT_ACTIONS,
)
from hamilton_venus.models.error_types import RecoveryAction

# Consolidated ALLOWED_ACTIONS mapping combining all category-specific actions.
ALLOWED_ACTIONS: dict[Any, set[RecoveryAction]] = {
    **TIP_HANDLING_ACTIONS,
    **ASPIRATE_ACTIONS,
    **DISPENSE_ACTIONS,
    **TRANSPORT_ACTIONS,
    **SYSTEM_ACTIONS,
}

__all__ = ["ALLOWED_ACTIONS"]

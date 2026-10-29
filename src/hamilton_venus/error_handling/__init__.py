"""Error handling profiles and actions for Hamilton instruments.

This package provides a comprehensive error handling framework for Hamilton Venus
operations, including:

- ErrorEntry: Single error-handling rule definition
- ErrorProfile: Complete profile container with operation-specific entries
- STANDARD_PROFILE: Pre-configured error handling profile for standard lab workflows
- ALLOWED_ACTIONS: Mapping of valid recovery actions for each error type

Documentation: See docs/error_handling.md for comprehensive user documentation

Example usage:
    >>> from hamilton_venus.error_handling import ErrorProfile, STANDARD_PROFILE
    >>> # Use the built-in standard profile
    >>> profile = STANDARD_PROFILE
    >>>
    >>> # Create a custom profile
    >>> custom = STANDARD_PROFILE.with_overrides(
    ...     name="Custom",
    ...     operations={
    ...         "aspirate": {
    ...             AspirateError.CLOT: ErrorEntry(
    ...                 actions=(RecoveryAction.REPEAT, RecoveryAction.EXCLUDE)
    ...             )
    ...         }
    ...     }
    ... )

References:
    - Main documentation: docs/error_handling.md
    - Profile JSON files: src/hamilton_venus/error_handling/profiles/
    - Design documentation: docs/design/error-handling/
"""

from hamilton_venus.error_handling.access_actions import (
    ACCESS_ACTION_IDS,
    ACCESS_ACTION_LABELS,
    access_action_recovery,
    access_actions,
)
from hamilton_venus.error_handling.actions import ALLOWED_ACTIONS
from hamilton_venus.error_handling.presets import STANDARD_PROFILE
from hamilton_venus.error_handling.profile import ErrorEntry, ErrorProfile

__all__ = [
    "ACCESS_ACTION_IDS",
    "ACCESS_ACTION_LABELS",
    "ALLOWED_ACTIONS",
    "STANDARD_PROFILE",
    "ErrorEntry",
    "ErrorProfile",
    "access_action_recovery",
    "access_actions",
]

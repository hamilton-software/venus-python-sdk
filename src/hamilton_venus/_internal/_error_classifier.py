"""Error classifier for Hamilton STAR / Vantage instrument error codes.

This module maps the numeric MAIN error codes emitted by the Hamilton STAR and
Vantage firmware into structured (OperationCategory, error-type) pairs that the
rest of the SDK can act on.

Instrument scope
----------------
The classification table _MAIN_CODE_TO_ERROR_TYPE is **specific to STAR/Vantage**
firmware. ``OperationCategory`` lives in ``hamilton_venus.models.enums`` and is
shared across the SDK. Different Hamilton instruments
use different error-code schemes:

* **STAR / Vantage** - two-digit decimal MAIN codes ("04", "06", …), optionally
  followed by a slash-separated sub-code ("06/02"). Only the MAIN code is used
  for classification.
* **Nimbus** - Nimbus firmware encodes errors differently and does not use the
  same MAIN-code numbering. To support Nimbus you would:

  1. Add a new classification table (e.g. _NIMBUS_CODE_TO_ERROR_TYPE) that maps
     Nimbus error identifiers to (OperationCategory, <NimbusError>) tuples,
     using new or shared OperationCategory members as appropriate.
  2. Subclass (or replace) ErrorClassifier with a NimbusErrorClassifier that
     overrides classify() to look up the Nimbus table. The action_to_server_id
     helper is instrument-agnostic and can be reused as-is.
  3. Inject the correct classifier into ErrorResolver at construction time so
     the resolver remains instrument-neutral.


"""
from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

from hamilton_venus.models.error_types import (
    AspirateError,
    AutoloadError,
    DispenseError,
    DispenseFlyError,
    GripperError,
    InitializeError,
    MagPipError,
    OperationCategory,
    RecoveryAction,
    TipPickupError,
)

if TYPE_CHECKING:
    from hamilton_venus.models.instrument_errors import (
        ErrorData,
        RecoveryActionDescriptor,
    )

_logger = logging.getLogger(__name__)


def _generate_category_frozenset(*categories: OperationCategory) -> frozenset[str]:
    """Generate a frozenset of category string values from OperationCategory enum members.

    This function centralizes the mapping of logical operation groups to their
    OperationCategory members, making it a single source of truth for category
    membership that can be easily extended when new operations are added.

    Parameters
    ----------
    *categories : OperationCategory
        Variable number of OperationCategory enum members to include in the frozenset.

    Returns
    -------
    frozenset[str]
        A frozen set containing the string values of the provided categories.
    """
    return frozenset(cat.value for cat in categories)


# STAR / Vantage MAIN-code lookup table.
#
# Maps the two-digit decimal MAIN error code (the part before the first "/")
# to a (OperationCategory, <error-type enum member>) pair.
#
# NOTE: MAIN code "00" (no error) is handled by an explicit early return in
# classify() and is intentionally absent from this table.
#
#
# Source: Hamilton STAR/Vantage firmware error-code documentation.
# When adding new instrument support, create a parallel mapping dict and
# inject it via a subclass of ErrorClassifier (see module docstring).
#
# VANTAGE-only sub-codes
# -----------------------------------------------------
# The Vantage firmware emits a number of sub-codes that do not appear in
# the STAR walkaway dataset.  Because classify() uses only the MAIN code
# for its primary lookup, every sub-code listed below is **already handled
# correctly** by the corresponding entry in this table without any changes:
#
#   1000 µL / 5 mL channels
#     01/01, 01/03, 01/04, 01/12, 01/17          → "01" → INITIALIZE / OTHER
#     02/10, 02/11, 02/25-02/29, 02/38, 02/58,
#       02/59, 02/64, 02/69, 02/79               → "02" → INITIALIZE / HARDWARE
#     03/36, 03/39                               → "03" → INITIALIZE / EXECUTION
#     10/15  (Vantage; STAR uses 10/01)          → "10" → INITIALIZE / NOT_EXECUTED
#
#   Autoload / IDL
#     01/34, 01/70-01/80, 01/93-01/97            → "01" → INITIALIZE / OTHER
#     02/25-02/29, 02/56-02/58, 02/63, 02/64,
#       02/85-02/92                              → "02" → INITIALIZE / HARDWARE
#     03/36, 03/39, 03/xxxx (4-digit)            → "03" → INITIALIZE / EXECUTION
#     10/0211 (extended execution code)          → "10" → INITIALIZE / NOT_EXECUTED
#
#   iSWAP / IPG
#     01/17, 01/19                               → "01" → INITIALIZE / OTHER
#     02/22, 02/23, 02/54-02/58, 02/65-02/68    → "02" → INITIALIZE / HARDWARE
#
# The only sub-code overrides that deviate from the MAIN-code default are
# implemented in classify() via explicit if-blocks above the table lookup:
#   02/54  → NOT_ASPIRATED  (dispense context)
#   13/83, 13/84 → LOADING_TRAY
#   17/83  → TADM_UPPER     (dispense-fly context)
#   04/82  → TADM_LOWER / IMPROPER
#   02/0151 → OTHER         (MagPip context)
#
# Extended error codes (100+)
# -----------------------------------------------
# The following error codes are high-level composite errors generated from
# multiple sub-code combinations:
#   100 → Wrong Carrier Error → AUTOLOAD / OTHER
#   101 → No Carrier Barcode Error → AUTOLOAD / BARCODE
#   102 → Liquid Level Error (from 06/70, 06/73, 06/87) → ASPIRATE / LIQUID_LEVEL
#   103 → Not Detected Error → INITIALIZE / NOT_EXECUTED
#   104 → Not Aspirated Error (from 02/54) → DISPENSE / NOT_ASPIRATED
_MAIN_CODE_TO_ERROR_TYPE: dict[str, tuple[OperationCategory, Enum]] = {
    "01": (OperationCategory.INITIALIZE, InitializeError.OTHER),
    "02": (OperationCategory.INITIALIZE, InitializeError.HARDWARE),
    "03": (OperationCategory.INITIALIZE, InitializeError.EXECUTION),
    "04": (OperationCategory.ASPIRATE, AspirateError.CLOT),
    "05": (OperationCategory.AUTOLOAD, AutoloadError.BARCODE),
    "06": (OperationCategory.ASPIRATE, AspirateError.LIQUID_LEVEL),
    "07": (OperationCategory.TIP_PICKUP, TipPickupError.TIP_PRESENT),
    "08": (OperationCategory.TIP_PICKUP, TipPickupError.NO_TIP),
    "10": (OperationCategory.INITIALIZE, InitializeError.NOT_EXECUTED),
    "13": (OperationCategory.AUTOLOAD, AutoloadError.OTHER),
    "14": (OperationCategory.INITIALIZE, InitializeError.HARDWARE),
    "17": (OperationCategory.ASPIRATE, AspirateError.IMPROPER),
    "25": (OperationCategory.INITIALIZE, InitializeError.HARDWARE),
    "28": (OperationCategory.ASPIRATE, AspirateError.UNEXPECTED_CLLD),
    "31": (OperationCategory.ASPIRATE, AspirateError.ANTI_DROP),
    "100": (OperationCategory.AUTOLOAD, AutoloadError.OTHER),
    "101": (OperationCategory.AUTOLOAD, AutoloadError.BARCODE),
    "102": (OperationCategory.ASPIRATE, AspirateError.LIQUID_LEVEL),
    "103": (OperationCategory.INITIALIZE, InitializeError.NOT_EXECUTED),
    "104": (OperationCategory.DISPENSE, DispenseError.NOT_ASPIRATED),
}

# Category membership frozensets generated from OperationCategory enum.
# These define logical groupings of operation types for context-dependent error mapping.
_ASPIRATE_CATEGORIES: frozenset[str] = _generate_category_frozenset(
    OperationCategory.ASPIRATE,
    OperationCategory.HEAD96_ASPIRATE,
    OperationCategory.XL_ASPIRATE,
    OperationCategory.EASY_ASPIRATE,
    OperationCategory.ASPIRATE_2ND_PHASE,
)

_DISPENSE_CATEGORIES: frozenset[str] = _generate_category_frozenset(
    OperationCategory.DISPENSE,
    OperationCategory.HEAD96_DISPENSE,
    OperationCategory.XL_DISPENSE,
    OperationCategory.EASY_DISPENSE,
    OperationCategory.DISPENSE_FLY,
    OperationCategory.XL_DISPENSE_FLY,
)

_NON_FLY_DISPENSE_CATEGORIES: frozenset[str] = _generate_category_frozenset(
    OperationCategory.DISPENSE,
    OperationCategory.HEAD96_DISPENSE,
    OperationCategory.XL_DISPENSE,
    OperationCategory.EASY_DISPENSE,
)

_DISPENSE_FLY_CATEGORIES: frozenset[str] = _generate_category_frozenset(
    OperationCategory.DISPENSE_FLY,
    OperationCategory.XL_DISPENSE_FLY,
)

_GRIPPER_CATEGORIES: frozenset[str] = _generate_category_frozenset(
    OperationCategory.GRIPPER,
    OperationCategory.CORE_GRIP_TRANSPORT,
    OperationCategory.ZSWAP_GET_PLATE,
    OperationCategory.ZSWAP_READ_BARCODE,
    OperationCategory.ZSWAP_PLACE_PLATE,
)


class ErrorClassifier:
    """Classifies Hamilton STAR / Vantage error codes and resolves recovery action IDs.

    This class is **STAR/Vantage-specific**. It interprets the two-digit
    decimal MAIN error codes produced by STAR/Vantage firmware and maps them
    to an (OperationCategory, <error-type>) pair that higher-level recovery
    logic can act on.

    To support a different instrument (e.g. Nimbus) without modifying this
    class, create a subclass that overrides classify() and supplies its own
    lookup table. The action_to_server_id helper performs a name-based lookup
    against the server's recoveryActions list and is instrument-agnostic;
    subclasses can inherit it unchanged. See the module docstring for a detailed
    extension walkthrough.

    Attributes
    ----------
    _classification_miss_count : int
        Counts how many error codes were not found in the lookup table and
        fell back to (INITIALIZE, OTHER). Exposed via the stats property for
        monitoring / diagnostics.
    """

    def __init__(self) -> None:
        self._classification_miss_count = 0

    def classify(
        self,
        error_data: ErrorData,
        operation_context: str | None = None,
    ) -> tuple[OperationCategory, Enum] | tuple[None, None]:
        """Classify a STAR / Vantage error code into a category and error type.

        Extracts the MAIN code (the portion before the first "/" in error_data.code)
        and performs a lookup in _MAIN_CODE_TO_ERROR_TYPE. Any device prefix (e.g.,
        "P1:") is stripped before extraction. Context-dependent MAIN codes (20, 21,
        23, 26) are reclassified using the operation_context string which has the
        format "{category}/{action_name}".

        Parameters
        ----------
        error_data : ErrorData
            The error payload received from the VENUS WebAPI. Only
            error_data.code is examined. The code may include a device prefix
            (e.g., "P1:102/70") which is automatically stripped.
        operation_context : str | None
            The last dispatched operation context, e.g. "aspirate/Aspirate".
            Used to disambiguate context-dependent MAIN codes.

        Returns
        -------
        tuple[OperationCategory, Enum]
            The matched (category, error_type) pair, e.g.
            (OperationCategory.ASPIRATE, AspirateError.CLOT).
        tuple[None, None]
            Returned when MAIN code is "00" (no error), indicating that
            no recovery is required.

        Notes
        -----
        * If error_data.code is empty or None, the method falls back to
          (INITIALIZE, OTHER) and increments _classification_miss_count.
        * Unmapped MAIN codes also fall back to (INITIALIZE, OTHER) and
          increment the miss counter.
        """
        return self.classify_code(error_data.code, operation_context)

    def classify_code(
        self,
        code: str | None,
        operation_context: str | None = None,
    ) -> tuple[OperationCategory, Enum] | tuple[None, None]:
        """Classify a raw error code string into a category and error type.

        Identical classification logic as ``classify()`` but accepts a plain
        code string directly. Used for per-channel ``DetailedError.code``
        classification without wrapping in a full ``ErrorData`` object.

        Parameters
        ----------
        code : str | None
            Raw error code string, e.g. ``"04"``, ``"P1:06/70"``.
        operation_context : str | None
            The last dispatched operation context (same semantics as in
            ``classify()``).
        """
        if not code:
            self._classification_miss_count += 1
            _logger.debug(
                "Error code is missing or None; falling back to OTHER. "
                "Classification miss count: %d",
                self._classification_miss_count,
            )
            return (OperationCategory.INITIALIZE, InitializeError.OTHER)

        # Strip device prefix (e.g., "P1:" from "P1:102/70") if present
        code_str = code
        if ":" in code_str:
            code_str = code_str.split(":", 1)[1]

        parts = code_str.split("/", 1)
        main_code = parts[0]
        sub_code = parts[1] if len(parts) == 2 else None

        if main_code == "00":
            _logger.debug("Detected NO_ERROR (MAIN code '00'); returning None, None for fast-path")
            return (None, None)

        op_category = operation_context.split("/")[0] if operation_context else None

        if main_code == "20":
            if op_category in _ASPIRATE_CATEGORIES:
                return (OperationCategory.ASPIRATE, AspirateError.INSUFFICIENT)
            if op_category in _DISPENSE_CATEGORIES:
                return (OperationCategory.DISPENSE, DispenseError.INSUFFICIENT)
            return (OperationCategory.INITIALIZE, InitializeError.OTHER)

        if main_code == "26":
            if op_category in _ASPIRATE_CATEGORIES:
                return (OperationCategory.ASPIRATE, AspirateError.CLOT)
            if op_category in _DISPENSE_CATEGORIES:
                return (OperationCategory.DISPENSE, DispenseError.PRESSURE_LLD)
            return (OperationCategory.INITIALIZE, InitializeError.OTHER)

        if main_code in ("21", "23"):
            if op_category in _GRIPPER_CATEGORIES:
                return (OperationCategory.GRIPPER, GripperError.LABWARE_NOT_FOUND)
            return (OperationCategory.INITIALIZE, InitializeError.OTHER)

        if sub_code is not None:
            if main_code == "02" and sub_code == "54" and op_category in _NON_FLY_DISPENSE_CATEGORIES:
                return (OperationCategory.DISPENSE, DispenseError.NOT_ASPIRATED)

            if main_code == "13" and sub_code in ("83", "84"):
                return (OperationCategory.AUTOLOAD, AutoloadError.LOADING_TRAY)

            if main_code == "17" and sub_code == "83" and op_category in _DISPENSE_FLY_CATEGORIES:
                return (OperationCategory.DISPENSE, DispenseFlyError.TADM_UPPER)

            if main_code == "04" and sub_code == "82":
                if op_category in _DISPENSE_FLY_CATEGORIES:
                    return (OperationCategory.DISPENSE, DispenseFlyError.TADM_LOWER)
                return (OperationCategory.ASPIRATE, AspirateError.IMPROPER)

            if len(sub_code) == 4 and op_category == OperationCategory.MAGPIP.value and main_code == "02":
                if sub_code == "0151":
                    return (OperationCategory.MAGPIP, MagPipError.OTHER)
                return (OperationCategory.MAGPIP, MagPipError.HARDWARE)

        if main_code in _MAIN_CODE_TO_ERROR_TYPE:
            category, error_type = _MAIN_CODE_TO_ERROR_TYPE[main_code]
            _logger.debug(
                "Classified MAIN code '%s' to (%s, %s)",
                main_code,
                category.value,
                error_type.value,
            )
            return (category, error_type)

        self._classification_miss_count += 1
        _logger.debug(
            "Unmapped MAIN code '%s' (full code: %s); falling back to OTHER. "
            "Classification miss count: %d",
            main_code,
            code,
            self._classification_miss_count,
        )
        return (OperationCategory.INITIALIZE, InitializeError.OTHER)

    def action_to_server_id(
        self, action: RecoveryAction, recovery_actions: list[RecoveryActionDescriptor] | None
    ) -> int | None:
        """Resolve a RecoveryAction to the server's action ID.

        The VENUS WebAPI assigns opaque integer IDs to each recovery action
        available for a given error event. This method matches the
        human-readable RecoveryAction enum value against the server's list
        of RecoveryActionDescriptor objects using a case-insensitive name
        comparison and returns the matching action ID.

        This method is instrument-agnostic: it relies solely on the server's
        recoveryActions list and does not use any STAR/Vantage-specific logic,
        so subclasses for other instruments can inherit it unchanged.

        Parameters
        ----------
        action : RecoveryAction
            The desired recovery action (e.g. RecoveryAction.ASPIRATE_RETRY).
        recovery_actions : list[RecoveryActionDescriptor] | None
            The list of available actions returned by the server for the
            current error event. None or an empty list results in a warning
            and a None return value.

        Returns
        -------
        int | None
            The server-assigned action ID if a matching action is found,
            or None if the list is empty / the action is not present.
        """
        if not recovery_actions:
            _logger.warning("No recovery_actions available to match action '%s'", action.value)
            return None

        action_lower = action.value.lower()

        for desc in recovery_actions:
            if desc.name.lower() == action_lower:
                _logger.debug(
                    "Matched action '%s' to server action ID '%s' (server name: '%s')",
                    action.value,
                    desc.id,
                    desc.name,
                )
                return desc.id

        _logger.warning(
            "Action '%s' not found in recovery_actions. Available server actions: %s",
            action.value,
            [d.name for d in recovery_actions],
        )
        return None

    @property
    def stats(self) -> dict[str, int]:
        """Diagnostic counters for this classifier instance.

        Returns
        -------
        dict[str, int]
            A dictionary with the key "classification_miss_count" whose value
            is the number of error codes that could not be found in the lookup
            table and fell back to (INITIALIZE, OTHER).
        """
        return {"classification_miss_count": self._classification_miss_count}

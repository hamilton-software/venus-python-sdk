"""Error profile data structures using registry pattern.

This module defines immutable error profile containers that map operation
categories and error types to recovery actions.

**Example Usage**

    from hamilton_venus.error_handling import (
        ErrorProfile, ErrorEntry, STANDARD_PROFILE
    )
    from hamilton_venus.models.error_types import (
        RecoveryAction, TipPickupError, AspirateError
    )

    # Create a custom profile
    custom_profile = ErrorProfile(
        name="Custom_Lab_Run",
        default=ErrorEntry(actions=(RecoveryAction.ABORT,)),
        operations={
            "tip_pickup": {
                TipPickupError.NO_TIP: ErrorEntry(
                    actions=(RecoveryAction.REPEAT, RecoveryAction.EXCLUDE),
                    max_retries=3,
                ),
            },
            "aspirate": {
                AspirateError.CLOT: ErrorEntry(
                    actions=(RecoveryAction.REPEAT, RecoveryAction.EXCLUDE),
                    max_retries=2,
                ),
            },
        },
        operation_defaults={
            "tip_pickup": ErrorEntry(actions=(RecoveryAction.ABORT,)),
        },
    )

    # Or extend an existing profile
    variant = STANDARD_PROFILE.with_overrides(
        name="Strict_Mode",
        operations={
            "tip_pickup": {
                TipPickupError.NO_TIP: ErrorEntry(
                    actions=(RecoveryAction.ABORT,),
                    max_retries=0,
                ),
            },
        },
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from hamilton_venus.models.error_types import RecoveryAction
from hamilton_venus.models.instrument_errors import InputValue


class _UnsetType:
    """Sentinel value to distinguish 'not provided' from None in with_overrides()."""

    def __repr__(self) -> str:
        return "<_UNSET>"


_UNSET = _UnsetType()


@dataclass(frozen=True)
class ErrorEntry:
    """A single error-handling rule within a profile.

    The resolver executes actions in sequence: it attempts the first action,
    and if that action is REPEAT, it can be submitted up to ``max_retries``
    times before advancing to the next action in the chain. Non-REPEAT actions
    are submitted once and always advance to the next action. Once all actions
    are exhausted, the error escalates: if ``allow_operator`` is False the
    SDK submits ABORT; if True it invokes the operator callback when one is
    registered, or otherwise defers to the legacy VENUS operator dialog by
    submitting ``selected_action_id=-1``.

    Parameters
    ----------
    actions:
        Ordered tuple of recovery actions to attempt. The resolver iterates
        through these in order, potentially repeating the REPEAT action
        multiple times per entry.
    max_retries:
        Maximum times the REPEAT action will be submitted before advancing to
        the next action in the chain. Other action types are not affected by
        this parameter. Defaults to 1 (one REPEAT attempt per action slot).
    allow_operator:
        If True, allow operator escalation when all actions are exhausted.
        When a callback is registered via ``on_operator_error_escalation``, the SDK
        invokes it to obtain a recovery decision. When no callback is
        registered, the SDK defers to the legacy VENUS operator dialog by
        submitting ``selected_action_id=-1``, letting an operator resolve the
        error on the PC running VENUS. If False, the SDK submits ABORT.
    inputs:
        Mapping of RecoveryAction → tuple of input values. Used to pass
        context to recovery actions that require parameters.
    """

    actions: tuple[RecoveryAction, ...]
    max_retries: int = 1
    allow_operator: bool = True
    inputs: MappingProxyType[RecoveryAction, tuple[InputValue, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """Normalize user-friendly types to immutable forms."""
        actions_tuple = tuple(self.actions) if not isinstance(self.actions, tuple) else self.actions
        object.__setattr__(self, "actions", actions_tuple)

        if not isinstance(self.inputs, MappingProxyType):
            inputs_dict = dict(self.inputs) if self.inputs else {}
            inputs_proxy = MappingProxyType(inputs_dict)
            object.__setattr__(self, "inputs", inputs_proxy)


@dataclass(frozen=True)
class ErrorProfile:
    """Error profile container with registry-based operation rules.

    This profile uses a registry pattern to eliminate repetitive field pairs.
    Instead of separate fields for each operation type (e.g., tip_pickup,
    tip_pickup_default, aspirate, aspirate_default), all operations are stored
    in two registry dictionaries.

    Parameters
    ----------
    name:
        Human-readable profile name.
    default:
        Default error entry applied to all errors not explicitly handled.
    operations:
        Registry mapping operation names to error-type mappings.
        Structure: {operation_name: {error_type: ErrorEntry, ...}}
    operation_defaults:
        Registry mapping operation names to operation-specific defaults.
        Structure: {operation_name: ErrorEntry | None}
    error_defaults:
        Registry mapping error type names to cross-operation defaults.
        Structure: {error_type_name: ErrorEntry}
    """

    name: str
    default: ErrorEntry
    operations: MappingProxyType[str, MappingProxyType[Any, ErrorEntry]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    operation_defaults: MappingProxyType[str, ErrorEntry | None] = field(
        default_factory=lambda: MappingProxyType({})
    )
    error_defaults: MappingProxyType[str, ErrorEntry] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """Normalize operation dicts to MappingProxyType and validate against ALLOWED_ACTIONS."""
        from hamilton_venus.error_handling.actions import ALLOWED_ACTIONS

        # Normalize operations registry to nested MappingProxyType
        if not isinstance(self.operations, MappingProxyType):
            normalized_ops = {}
            for op_name, error_map in (self.operations or {}).items():
                if isinstance(error_map, MappingProxyType):
                    normalized_ops[op_name] = error_map
                else:
                    normalized_ops[op_name] = MappingProxyType(dict(error_map) if error_map else {})
            object.__setattr__(self, "operations", MappingProxyType(normalized_ops))

        # Normalize operation_defaults to MappingProxyType
        if not isinstance(self.operation_defaults, MappingProxyType):
            object.__setattr__(
                self, "operation_defaults", MappingProxyType(self.operation_defaults or {})
            )

        # Normalize error_defaults to MappingProxyType
        if not isinstance(self.error_defaults, MappingProxyType):
            object.__setattr__(
                self, "error_defaults", MappingProxyType(self.error_defaults or {})
            )

        # Validate all error types and their actions are in ALLOWED_ACTIONS
        for op_name, error_map in self.operations.items():
            for error_type, entry in error_map.items():
                if error_type not in ALLOWED_ACTIONS:
                    raise ValueError(
                        f"Error type {error_type} in operation '{op_name}' is not "
                        f"defined in ALLOWED_ACTIONS."
                    )

                self._validate_entry_actions_for_error_type(error_type, entry)

        # Validate error_defaults keys map to known error names.
        for error_type_name in self.error_defaults:
            matching_error_types = [
                error_type
                for error_type in ALLOWED_ACTIONS
                if getattr(error_type, "name", None) == error_type_name
            ]
            if not matching_error_types:
                raise ValueError(
                    f"error_defaults contains unknown error type name: {error_type_name}"
                )

    def _validate_entry_actions_for_error_type(self, error_type: Any, entry: ErrorEntry) -> None:
        from hamilton_venus.error_handling.actions import ALLOWED_ACTIONS

        allowed = ALLOWED_ACTIONS[error_type]
        for action in entry.actions:
            if action == RecoveryAction.CANCEL:
                continue
            if action not in allowed:
                error_type_name = (
                    f"{type(error_type).__name__}.{error_type.name}"
                )
                raise ValueError(
                    f"Action {action} is not allowed for error type "
                    f"{error_type_name}. Allowed actions: {allowed}"
                )

    def get_operation_rules(
        self, operation_name: str
    ) -> MappingProxyType[Any, ErrorEntry]:
        """Get error-type-to-entry mapping for a specific operation.

        Parameters
        ----------
        operation_name:
            Name of the operation (e.g., 'tip_pickup', 'aspirate').

        Returns
        -------
        MappingProxyType[Any, ErrorEntry]
            Mapping of error types to recovery entries for this operation,
            or empty MappingProxyType if operation not defined.
        """
        return self.operations.get(operation_name, MappingProxyType({}))

    def get_operation_default(self, operation_name: str) -> ErrorEntry | None:
        """Get operation-specific default error entry.

        Parameters
        ----------
        operation_name:
            Name of the operation (e.g., 'tip_pickup', 'aspirate').

        Returns
        -------
        ErrorEntry | None
            Operation-specific default, or None if not defined.
        """
        return self.operation_defaults.get(operation_name)

    def with_overrides(self, **kwargs: Any) -> ErrorProfile:
        """Return a new ErrorProfile merging caller overrides onto self.

        Plain-dict kwargs are merged (caller wins); _UNSET-sentinel
        kwargs preserve the base value; None clears the field.

        Special handling for registry-based fields:
        - `operations`: Dict is merged into the registry
        - `operation_defaults`: Dict is merged into the registry
        - `error_defaults`: Dict is merged into the registry
        """
        merged: dict[str, Any] = {}
        merged["name"] = kwargs.get("name") or self.name
        merged["default"] = kwargs.get("default") or self.default

        # Merge operations registry
        if "operations" in kwargs and kwargs["operations"] is not _UNSET:
            base_ops = dict(self.operations)
            override_ops = kwargs["operations"] or {}
            # Deep merge: for each operation, merge its error mappings
            for op_name, error_map in override_ops.items():
                if op_name in base_ops:
                    base_ops[op_name] = MappingProxyType(
                        {**dict(base_ops[op_name]), **dict(error_map)}
                    )
                else:
                    base_ops[op_name] = MappingProxyType(dict(error_map))
            merged["operations"] = base_ops
        else:
            merged["operations"] = self.operations

        # Merge operation_defaults registry
        if "operation_defaults" in kwargs and kwargs["operation_defaults"] is not _UNSET:
            merged["operation_defaults"] = {**dict(self.operation_defaults), **kwargs["operation_defaults"]}
        else:
            merged["operation_defaults"] = self.operation_defaults

        # Merge error_defaults registry
        if "error_defaults" in kwargs and kwargs["error_defaults"] is not _UNSET:
            merged["error_defaults"] = {**dict(self.error_defaults), **kwargs["error_defaults"]}
        else:
            merged["error_defaults"] = self.error_defaults

        return ErrorProfile(**merged)

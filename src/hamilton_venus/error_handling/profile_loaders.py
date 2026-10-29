"""JSON serialization and deserialization for ErrorProfile instances.

This module provides utilities to convert ErrorProfile objects to/from JSON
format, enabling profiles to be stored in discoverable configuration files.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from hamilton_venus.error_handling.profile import ErrorEntry, ErrorProfile
from hamilton_venus.models.error_types import OperationCategory, RecoveryAction


def _serialize_recovery_action(action: RecoveryAction) -> str:
    """Serialize a RecoveryAction enum to its string name."""
    return action.name


def _deserialize_recovery_action(action_str: str) -> RecoveryAction:
    """Deserialize a string to RecoveryAction enum."""
    return RecoveryAction[action_str]


def _error_type_to_string(error_type: Any) -> str:
    """Convert error type (enum or other) to string for JSON serialization."""
    if hasattr(error_type, "name"):
        # It's an enum
        return str(error_type.name)
    return str(error_type)


def _serialize_error_entry(entry: ErrorEntry) -> dict[str, Any]:
    """Convert ErrorEntry to JSON-serializable dictionary."""
    return {
        "actions": [_serialize_recovery_action(action) for action in entry.actions],
        "max_retries": entry.max_retries,
        "allow_operator": entry.allow_operator,
        "inputs": {},  # Future enhancement for inputs serialization
    }


def _deserialize_error_entry(data: dict[str, Any]) -> ErrorEntry:
    """Convert JSON dictionary to ErrorEntry."""
    return ErrorEntry(
        actions=tuple(
            _deserialize_recovery_action(action_str) for action_str in data["actions"]
        ),
        max_retries=data.get("max_retries", 1),
        allow_operator=data.get("allow_operator", True),
        inputs=MappingProxyType(data.get("inputs", {})),
    )


def serialize_profile(profile: ErrorProfile) -> dict[str, Any]:
    """Convert ErrorProfile to JSON-serializable dictionary.

    Parameters
    ----------
    profile : ErrorProfile
        The error profile to serialize.

    Returns
    -------
    dict[str, Any]
        A dictionary ready for JSON serialization.
    """
    # Serialize operations registry
    operations_dict = {}
    for op_name, error_map in profile.operations.items():
        operations_dict[op_name] = {
            _error_type_to_string(error_type): _serialize_error_entry(entry)
            for error_type, entry in error_map.items()
        }

    # Serialize operation_defaults registry
    operation_defaults_dict = {
        op_name: _serialize_error_entry(entry) if entry else None
        for op_name, entry in profile.operation_defaults.items()
    }

    error_defaults_dict = {
        error_type_name: _serialize_error_entry(entry)
        for error_type_name, entry in profile.error_defaults.items()
    }

    return {
        "name": profile.name,
        "default": _serialize_error_entry(profile.default),
        "operations": operations_dict,
        "operation_defaults": operation_defaults_dict,
        "error_defaults": error_defaults_dict,
    }


def deserialize_profile(data: dict[str, Any]) -> ErrorProfile:
    """Convert JSON dictionary to ErrorProfile.

    Note: Error type deserialization is deferred to allow for
    dynamic error type imports based on the operation.

    Parameters
    ----------
    data : dict[str, Any]
        Dictionary loaded from JSON.

    Returns
    -------
    ErrorProfile
        The reconstructed error profile.
    """
    # Generate error_type_map dynamically from OperationCategory enum
    error_type_map: dict[str, Any] = {}

    for operation in OperationCategory:
        op_name = operation.value

        # Convert snake_case operation name to CamelCase error class name
        # e.g., "tip_pickup" → "TipPickupError"
        parts = op_name.split("_")
        class_name = "".join(word.capitalize() for word in parts) + "Error"

        # Try to import the error type class
        try:
            error_types_module = importlib.import_module("hamilton_venus.models.error_types")
            error_type_class = getattr(error_types_module, class_name)
            error_type_map[op_name] = error_type_class
        except (ImportError, AttributeError):
            # Skip operations without corresponding error type classes
            pass

    # Deserialize default
    default = _deserialize_error_entry(data["default"])

    # Deserialize operations registry
    operations = {}
    for op_name, error_map in data.get("operations", {}).items():
        error_type_class = error_type_map.get(op_name)
        if error_type_class:
            error_entries = {}
            for error_type_str, entry_data in error_map.items():
                try:
                    error_type: Any = error_type_class[error_type_str]
                    error_entries[error_type] = _deserialize_error_entry(entry_data)
                except KeyError as e:
                    raise ValueError(
                        f"Unknown {op_name} error type: {error_type_str}"
                    ) from e
            operations[op_name] = MappingProxyType(error_entries)

    # Deserialize operation_defaults registry
    operation_defaults = {}
    for op_name, entry_data in data.get("operation_defaults", {}).items():
        operation_defaults[op_name] = (
            _deserialize_error_entry(entry_data) if entry_data else None
        )

    error_defaults = {}
    for error_type_name, entry_data in data.get("error_defaults", {}).items():
        error_defaults[error_type_name] = _deserialize_error_entry(entry_data)

    return ErrorProfile(
        name=data["name"],
        default=default,
        operations=MappingProxyType(operations),
        operation_defaults=MappingProxyType(operation_defaults),
        error_defaults=MappingProxyType(error_defaults),
    )


def profile_to_json(profile: ErrorProfile, indent: int = 2) -> str:
    """Convert ErrorProfile to JSON string.

    Parameters
    ----------
    profile : ErrorProfile
        The error profile to convert.
    indent : int, optional
        JSON indentation level. Defaults to 2.

    Returns
    -------
    str
        JSON string representation of the profile.
    """
    data = serialize_profile(profile)
    return json.dumps(data, indent=indent)


def profile_from_json(json_str: str) -> ErrorProfile:
    """Load ErrorProfile from JSON string.

    Parameters
    ----------
    json_str : str
        JSON string containing profile data.

    Returns
    -------
    ErrorProfile
        The loaded error profile.

    Raises
    ------
    json.JSONDecodeError
        If the JSON is invalid.
    ValueError
        If the profile data is invalid.
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in profile: {e}") from e
    return deserialize_profile(data)


def profile_to_json_file(profile: ErrorProfile, file_path: str | Path) -> None:
    """Save ErrorProfile to JSON file.

    Parameters
    ----------
    profile : ErrorProfile
        The error profile to save.
    file_path : str | Path
        Path where the JSON file will be written.
    """
    file_path = Path(file_path)
    json_str = profile_to_json(profile)
    file_path.write_text(json_str, encoding="utf-8")


def profile_from_json_file(file_path: str | Path) -> ErrorProfile:
    """Load ErrorProfile from JSON file.

    Parameters
    ----------
    file_path : str | Path
        Path to the JSON file.

    Returns
    -------
    ErrorProfile
        The loaded error profile.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    json.JSONDecodeError
        If the JSON is invalid.
    ValueError
        If the profile data is invalid.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Profile file not found: {file_path}")
    json_str = file_path.read_text(encoding="utf-8")
    return profile_from_json(json_str)

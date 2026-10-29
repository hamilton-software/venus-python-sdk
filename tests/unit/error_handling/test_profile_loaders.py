"""Test suite for JSON profile loading functionality."""

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from hamilton_venus.error_handling import STANDARD_PROFILE
from hamilton_venus.error_handling.profile import ErrorEntry
from hamilton_venus.error_handling.profile_loaders import (
    profile_from_json,
    profile_from_json_file,
    profile_to_json,
    profile_to_json_file,
)
from hamilton_venus.models.error_types import RecoveryAction, TipPickupError


class TestProfileJsonSerialization:
    """Test JSON serialization and deserialization of profiles."""

    def test_standard_profile_to_json(self):
        """Verify STANDARD_PROFILE can be converted to JSON string."""
        json_str = profile_to_json(STANDARD_PROFILE)

        data = json.loads(json_str)
        assert isinstance(data, dict)

        assert "name" in data
        assert "default" in data
        assert "operations" in data
        assert "operation_defaults" in data
        assert "error_defaults" in data

        assert data["name"] == "Standard_Lab_Profile"
        assert isinstance(data["default"]["actions"], list)
        assert all(isinstance(a, str) for a in data["default"]["actions"])

    def test_standard_profile_from_json_file(self):
        """Verify STANDARD_PROFILE can be loaded from JSON file."""
        profile_path = Path("src/hamilton_venus/error_handling/profiles/standard.json")
        assert profile_path.exists(), f"Profile file not found: {profile_path}"

        loaded_profile = profile_from_json_file(str(profile_path))

        assert loaded_profile.name == "Standard_Lab_Profile"
        assert loaded_profile.default == STANDARD_PROFILE.default
        assert loaded_profile.operations.keys() == STANDARD_PROFILE.operations.keys()

    def test_profile_operations_loaded_correctly(self):
        """Verify all operations are loaded correctly from JSON."""
        profile_path = Path("src/hamilton_venus/error_handling/profiles/standard.json")
        loaded_profile = profile_from_json_file(str(profile_path))

        expected_ops = {"tip_pickup", "aspirate", "dispense"}
        assert set(loaded_profile.operations.keys()) == expected_ops

    def test_profile_operation_rules_accessible(self):
        """Verify operation rules are accessible via getter."""
        profile_path = Path("src/hamilton_venus/error_handling/profiles/standard.json")
        loaded_profile = profile_from_json_file(str(profile_path))

        tip_pickup_rules = loaded_profile.get_operation_rules("tip_pickup")
        assert len(tip_pickup_rules) > 0

        tip_present_rule = tip_pickup_rules.get(TipPickupError.TIP_PRESENT)
        assert tip_present_rule is not None
        assert RecoveryAction.EXCLUDE in tip_present_rule.actions

    def test_roundtrip_serialization(self):
        """Verify profile can be serialized and deserialized without loss."""
        json_str = profile_to_json(STANDARD_PROFILE)
        restored_profile = profile_from_json(json_str)

        assert restored_profile.name == STANDARD_PROFILE.name
        assert restored_profile.default.actions == STANDARD_PROFILE.default.actions
        assert restored_profile.default.max_retries == STANDARD_PROFILE.default.max_retries

        assert set(restored_profile.operations.keys()) == set(STANDARD_PROFILE.operations.keys())

        original_entry = STANDARD_PROFILE.get_operation_rules("tip_pickup").get(TipPickupError.NO_TIP)
        restored_entry = restored_profile.get_operation_rules("tip_pickup").get(TipPickupError.NO_TIP)

        assert restored_entry is not None
        assert restored_entry.actions == original_entry.actions
        assert restored_entry.max_retries == original_entry.max_retries

    def test_roundtrip_error_defaults(self):
        profile = STANDARD_PROFILE.with_overrides(
            error_defaults={
                "NOT_EXECUTED": ErrorEntry(
                    actions=(RecoveryAction.REPEAT,),
                    max_retries=1,
                    allow_operator=True,
                )
            }
        )

        json_str = profile_to_json(profile)
        restored = profile_from_json(json_str)

        assert "NOT_EXECUTED" in restored.error_defaults
        assert restored.error_defaults["NOT_EXECUTED"].actions == (RecoveryAction.REPEAT,)

    def test_file_roundtrip(self, tmp_path):
        """Verify profile can be saved to and loaded from file."""
        custom_profile = STANDARD_PROFILE.with_overrides(
            name="Test_Profile",
            operations={
                "tip_pickup": {
                    TipPickupError.NO_TIP: ErrorEntry(
                        actions=(RecoveryAction.REPEAT, RecoveryAction.ABORT),
                        max_retries=5,
                    ),
                },
            },
        )

        test_file = tmp_path / "test_profile.json"
        profile_to_json_file(custom_profile, str(test_file))
        assert test_file.exists()

        loaded_profile = profile_from_json_file(str(test_file))

        assert loaded_profile.name == "Test_Profile"
        no_tip_rule = loaded_profile.get_operation_rules("tip_pickup").get(TipPickupError.NO_TIP)
        assert no_tip_rule is not None
        assert no_tip_rule.max_retries == 5

    def test_json_structure_valid(self):
        """Verify exported JSON has correct structure."""
        json_str = profile_to_json(STANDARD_PROFILE)
        data = json.loads(json_str)

        assert "name" in data
        assert "default" in data
        assert "operations" in data
        assert "operation_defaults" in data
        assert "error_defaults" in data

        default = data["default"]
        assert "actions" in default
        assert "max_retries" in default
        assert "allow_operator" in default
        assert "inputs" in default

        operations = data["operations"]
        assert isinstance(operations, dict)
        for _op_name, error_map in operations.items():
            assert isinstance(error_map, dict)
            for _error_type, entry in error_map.items():
                assert "actions" in entry
                assert "max_retries" in entry
                assert "allow_operator" in entry

    def test_error_on_missing_file(self):
        """Verify appropriate error when file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            profile_from_json_file("nonexistent_profile.json")

    def test_error_on_invalid_json(self):
        """Verify appropriate error for invalid JSON."""
        invalid_json = "{ invalid json content"
        with pytest.raises((json.JSONDecodeError, ValueError)):
            profile_from_json(invalid_json)

    def test_immutability_preserved(self):
        """Verify deserialized profile maintains immutability."""
        profile_path = Path("src/hamilton_venus/error_handling/profiles/standard.json")
        loaded_profile = profile_from_json_file(str(profile_path))

        with pytest.raises(AttributeError):
            loaded_profile.name = "Changed"  # type: ignore

        operations = loaded_profile.operations
        assert isinstance(operations, MappingProxyType)

        with pytest.raises(TypeError):
            operations["new_op"] = {}  # type: ignore


class TestProfileLoading:
    """Test profile loading integration."""

    def test_standard_profile_loads_at_import(self):
        """Verify STANDARD_PROFILE is loaded correctly at import time."""
        assert STANDARD_PROFILE.name == "Standard_Lab_Profile"
        assert STANDARD_PROFILE.default is not None
        assert isinstance(STANDARD_PROFILE.default.actions, tuple)

    def test_profile_operations_present(self):
        """Verify all expected operations are present."""
        expected_operations = {"tip_pickup", "aspirate", "dispense"}
        actual_operations = set(STANDARD_PROFILE.operations.keys())
        assert actual_operations == expected_operations

    def test_presets_module_exports(self):
        """Verify presets module exports work correctly."""
        from hamilton_venus.error_handling import presets

        profile = presets.STANDARD_PROFILE
        assert profile.name == "Standard_Lab_Profile"
        assert len(profile.operations) > 0

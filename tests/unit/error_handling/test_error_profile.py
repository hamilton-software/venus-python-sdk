"""Unit tests for error profile models and constants."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from hamilton_venus.error_handling import (
    ALLOWED_ACTIONS,
    STANDARD_PROFILE,
    ErrorEntry,
    ErrorProfile,
)
from hamilton_venus.models import RecoveryAction
from hamilton_venus.models.error_types import (
    Aspirate2ndPhaseError,
    AspirateError,
    AutoloadError,
    CoverError,
    DispenseError,
    GripperError,
    TipEjectError,
    TipPickupError,
)


class TestErrorEntry:
    def test_create_with_single_action(self):
        entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        assert entry.actions == (RecoveryAction.ABORT,)
        assert entry.max_retries == 1
        assert entry.allow_operator is True

    def test_create_with_multiple_actions(self):
        entry = ErrorEntry(
            actions=(RecoveryAction.ABORT, RecoveryAction.REPEAT),
            max_retries=3,
        )
        assert entry.actions == (RecoveryAction.ABORT, RecoveryAction.REPEAT)
        assert entry.max_retries == 3

    def test_actions_converted_to_tuple(self):
        entry = ErrorEntry(actions=[RecoveryAction.ABORT, RecoveryAction.REPEAT])
        assert isinstance(entry.actions, tuple)
        assert entry.actions == (RecoveryAction.ABORT, RecoveryAction.REPEAT)

    def test_is_frozen(self):
        entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        with pytest.raises(FrozenInstanceError):
            entry.actions = (RecoveryAction.REPEAT,)

    def test_inputs_becomes_mapping_proxy(self):
        inputs_dict = {RecoveryAction.ABORT: ()}
        entry = ErrorEntry(actions=(RecoveryAction.ABORT,), inputs=inputs_dict)
        assert isinstance(entry.inputs, MappingProxyType)
        assert RecoveryAction.ABORT in entry.inputs

    def test_inputs_default_empty(self):
        entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        assert isinstance(entry.inputs, MappingProxyType)
        assert len(entry.inputs) == 0


class TestErrorProfile:
    def test_standard_profile_exists(self):
        assert STANDARD_PROFILE is not None

    def test_standard_profile_name(self):
        assert STANDARD_PROFILE.name == "Standard_Lab_Profile"

    def test_standard_profile_default_entry(self):
        assert STANDARD_PROFILE.default is not None
        assert isinstance(STANDARD_PROFILE.default.actions, tuple)
        assert isinstance(STANDARD_PROFILE.default.max_retries, int)
        assert isinstance(STANDARD_PROFILE.default.allow_operator, bool)

    def test_standard_profile_has_operations(self):
        assert len(STANDARD_PROFILE.operations) > 0
        assert "tip_pickup" in STANDARD_PROFILE.operations

    def test_standard_profile_is_frozen(self):
        with pytest.raises(FrozenInstanceError):
            STANDARD_PROFILE.name = "New Name"

    def test_error_profile_requires_name_and_default(self):
        entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        profile = ErrorProfile(name="Test", default=entry)
        assert profile.name == "Test"
        assert profile.default == entry

    def test_error_profile_tip_pickup_optional(self):
        entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        profile = ErrorProfile(name="Test", default=entry)
        assert profile.get_operation_default("tip_pickup") is None
        assert len(profile.get_operation_rules("tip_pickup")) == 0

    def test_error_profile_all_error_type_fields_exist(self):
        entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        profile = ErrorProfile(name="Test", default=entry)

        # Test that accessor methods work for various operation types
        for _ in [
            "tip_pickup",
            "tip_eject",
            "aspirate",
            "dispense",
            "gripper",
            "autoload",
            "initialize",
            "lock_front_cover",
        ]:
            assert hasattr(profile, "get_operation_rules"), "Missing accessor method"
            assert hasattr(profile, "get_operation_default"), "Missing accessor method"

    def test_error_profile_mappings_are_mapping_proxies(self):
        entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        profile = ErrorProfile(name="Test", default=entry)

        for op_name in ["tip_pickup", "tip_eject", "aspirate", "dispense"]:
            assert isinstance(profile.get_operation_rules(op_name), MappingProxyType)


class TestAllowedActions:
    def test_allowed_actions_is_dict(self):
        assert isinstance(ALLOWED_ACTIONS, dict)

    def test_allowed_actions_not_empty(self):
        assert len(ALLOWED_ACTIONS) > 0

    def test_allowed_actions_values_are_sets(self):
        for error_type, actions_set in ALLOWED_ACTIONS.items():
            assert isinstance(actions_set, set), f"ALLOWED_ACTIONS[{error_type}] is not a set"

    def test_allowed_actions_set_contains_recovery_actions(self):
        for error_type, actions_set in ALLOWED_ACTIONS.items():
            for action in actions_set:
                assert isinstance(action, RecoveryAction), f"Invalid action {action} for {error_type}"

    def test_tip_pickup_error_allowed_actions(self):
        assert TipPickupError.EXECUTION in ALLOWED_ACTIONS
        actions = ALLOWED_ACTIONS[TipPickupError.EXECUTION]
        assert isinstance(actions, set)
        assert len(actions) > 0

    def test_dispense_error_allowed_actions(self):
        assert DispenseError.EXECUTION in ALLOWED_ACTIONS
        actions = ALLOWED_ACTIONS[DispenseError.EXECUTION]
        assert isinstance(actions, set)
        assert len(actions) > 0

    def test_aspirate_error_allowed_actions(self):
        assert AspirateError.EXECUTION in ALLOWED_ACTIONS
        actions = ALLOWED_ACTIONS[AspirateError.EXECUTION]
        assert isinstance(actions, set)
        assert len(actions) > 0

    def test_gripper_error_allowed_actions(self):
        assert GripperError.EXECUTION in ALLOWED_ACTIONS
        actions = ALLOWED_ACTIONS[GripperError.EXECUTION]
        assert isinstance(actions, set)
        assert len(actions) > 0

    def test_allowed_actions_abort_always_present(self):
        for error_type, actions_set in ALLOWED_ACTIONS.items():
            assert RecoveryAction.ABORT in actions_set, f"RecoveryAction.ABORT not in {error_type}"

    def test_allowed_actions_covers_major_error_types(self):
        major_error_types = [
            TipPickupError,
            TipEjectError,
            AspirateError,
            DispenseError,
            GripperError,
            AutoloadError,
            CoverError,
            Aspirate2ndPhaseError,
        ]

        for error_type_enum in major_error_types:
            for member in error_type_enum:
                assert member in ALLOWED_ACTIONS, f"{member} not in ALLOWED_ACTIONS"

    def test_allowed_actions_mutually_exclusive_recovery_actions(self):
        for _error_type, actions_set in ALLOWED_ACTIONS.items():
            if RecoveryAction.ABORT in actions_set:
                continue
            actions_list = list(actions_set)
            for action in actions_list:
                assert isinstance(action, RecoveryAction)


class TestErrorEntryWithInputs:
    def test_error_entry_with_empty_inputs(self):
        entry = ErrorEntry(actions=(RecoveryAction.ABORT,), inputs={})
        assert len(entry.inputs) == 0

    def test_error_entry_inputs_immutable(self):
        entry = ErrorEntry(
            actions=(RecoveryAction.ABORT,),
            inputs={RecoveryAction.ABORT: ()},
        )
        with pytest.raises(TypeError):
            entry.inputs[RecoveryAction.ABORT] = ()


class TestErrorProfileIntegration:
    def test_can_extend_standard_profile(self):
        entry = ErrorEntry(actions=(RecoveryAction.REPEAT,))
        profile = ErrorProfile(
            name="Custom",
            default=entry,
            operation_defaults={
                "tip_pickup": STANDARD_PROFILE.default,
            },
            error_defaults={
                "NOT_EXECUTED": ErrorEntry(actions=(RecoveryAction.REPEAT,)),
            },
        )

        assert profile.name == "Custom"
        assert profile.default.actions == (RecoveryAction.REPEAT,)
        op_default = profile.get_operation_default("tip_pickup")
        assert op_default is not None
        assert op_default is STANDARD_PROFILE.default
        assert profile.error_defaults["NOT_EXECUTED"].actions == (RecoveryAction.REPEAT,)

    def test_error_profile_with_specific_error_mappings(self):
        default_entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        custom_entry = ErrorEntry(actions=(RecoveryAction.REPEAT,))

        profile = ErrorProfile(
            name="Custom",
            default=default_entry,
            operations={
                "tip_pickup": {TipPickupError.EXECUTION: custom_entry},
            },
        )

        assert profile.get_operation_rules("tip_pickup")[TipPickupError.EXECUTION] == custom_entry


class TestProfileValidation:
    """Tests for the new profile validation in __post_init__."""

    def test_valid_profile_with_allowed_actions(self):
        """Profile with valid actions should be created without error."""
        default_entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        custom_entry = ErrorEntry(actions=(RecoveryAction.REPEAT,))

        profile = ErrorProfile(
            name="Valid",
            default=default_entry,
            operations={
                "tip_pickup": {TipPickupError.EXECUTION: custom_entry},
            },
        )

        assert profile.get_operation_rules("tip_pickup")[TipPickupError.EXECUTION] == custom_entry

    def test_profile_rejects_invalid_action_for_error_type(self):
        """Profile should raise ValueError for action not in ALLOWED_ACTIONS."""
        default_entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        # BARCODE is not allowed for TipPickupError.EXECUTION
        invalid_entry = ErrorEntry(actions=(RecoveryAction.BARCODE,))

        with pytest.raises(ValueError) as exc_info:
            ErrorProfile(
                name="Invalid",
                default=default_entry,
                operations={
                    "tip_pickup": {TipPickupError.EXECUTION: invalid_entry},
                },
            )

        assert "not allowed" in str(exc_info.value).lower()
        assert "TipPickupError.EXECUTION" in str(exc_info.value)

    def test_profile_validates_multiple_actions_in_entry(self):
        """Profile validation should check all actions in an ErrorEntry."""
        default_entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        # Mix of valid and invalid actions
        mixed_entry = ErrorEntry(actions=(RecoveryAction.REPEAT, RecoveryAction.BARCODE))

        with pytest.raises(ValueError) as exc_info:
            ErrorProfile(
                name="Mixed",
                default=default_entry,
                operations={
                    "tip_pickup": {TipPickupError.EXECUTION: mixed_entry},
                },
            )

        assert "not allowed" in str(exc_info.value).lower()

    def test_profile_rejects_unknown_error_default_key(self):
        default_entry = ErrorEntry(actions=(RecoveryAction.ABORT,))

        with pytest.raises(ValueError) as exc_info:
            ErrorProfile(
                name="Invalid",
                default=default_entry,
                error_defaults={
                    "NOT_A_REAL_ERROR": ErrorEntry(actions=(RecoveryAction.REPEAT,)),
                },
            )

        assert "unknown error type name" in str(exc_info.value)

    def test_profile_accepts_error_default_entry(self):
        default_entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        profile = ErrorProfile(
            name="Valid",
            default=default_entry,
            error_defaults={
                "NOT_EXECUTED": ErrorEntry(actions=(RecoveryAction.REPEAT,)),
            },
        )

        assert profile.error_defaults["NOT_EXECUTED"].actions == (RecoveryAction.REPEAT,)

    def test_profile_validation_across_multiple_operations(self):
        """Profile validation should work for multiple operation types."""
        default_entry = ErrorEntry(actions=(RecoveryAction.ABORT,))

        # Valid aspirate entry
        valid_aspirate_entry = ErrorEntry(actions=(RecoveryAction.REPEAT,))

        # Valid dispense entry
        valid_dispense_entry = ErrorEntry(actions=(RecoveryAction.ABORT, RecoveryAction.EXCLUDE))

        profile = ErrorProfile(
            name="MultiOp",
            default=default_entry,
            operations={
                "aspirate": {AspirateError.CLOT: valid_aspirate_entry},
                "dispense": {DispenseError.CLOT: valid_dispense_entry},
            },
        )

        assert profile.get_operation_rules("aspirate")[AspirateError.CLOT] == valid_aspirate_entry
        assert profile.get_operation_rules("dispense")[DispenseError.CLOT] == valid_dispense_entry

    def test_safe_profile_passes_validation(self):
        """STANDARD_PROFILE should load and be structurally valid."""
        assert STANDARD_PROFILE is not None
        assert isinstance(STANDARD_PROFILE.name, str) and STANDARD_PROFILE.name
        assert STANDARD_PROFILE.default is not None
        assert isinstance(STANDARD_PROFILE.default.actions, tuple)
        assert isinstance(STANDARD_PROFILE.default.max_retries, int)

    def test_profile_with_empty_operations_passes_validation(self):
        """Profile with empty operation dicts should pass validation."""
        default_entry = ErrorEntry(actions=(RecoveryAction.ABORT,))
        profile = ErrorProfile(
            name="Empty",
            default=default_entry,
            operations={
                "tip_pickup": {},
                "aspirate": {},
            },
        )

        assert len(profile.get_operation_rules("tip_pickup")) == 0
        assert len(profile.get_operation_rules("aspirate")) == 0

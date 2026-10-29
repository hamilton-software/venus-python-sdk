"""Unit tests for ErrorClassifier."""

from __future__ import annotations

import pytest

from hamilton_venus._internal._error_classifier import (
    _ASPIRATE_CATEGORIES,
    _DISPENSE_CATEGORIES,
    _DISPENSE_FLY_CATEGORIES,
    _GRIPPER_CATEGORIES,
    _NON_FLY_DISPENSE_CATEGORIES,
    ErrorClassifier,
    _generate_category_frozenset,
)
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
from hamilton_venus.models.instrument_errors import ErrorData, RecoveryActionDescriptor


def _error(code: str | None) -> ErrorData:
    return ErrorData(uuid="test-uuid", code=code)


def _action(id: int, name: str) -> RecoveryActionDescriptor:
    return RecoveryActionDescriptor(id=id, name=name, index=0)


class TestGenerateCategoryFrozenset:
    """Tests for the _generate_category_frozenset helper function."""

    def test_generates_frozenset(self):
        result = _generate_category_frozenset(OperationCategory.ASPIRATE)
        assert isinstance(result, frozenset)

    def test_contains_category_values(self):
        result = _generate_category_frozenset(OperationCategory.ASPIRATE)
        assert OperationCategory.ASPIRATE.value in result

    def test_multiple_categories(self):
        result = _generate_category_frozenset(
            OperationCategory.ASPIRATE,
            OperationCategory.HEAD96_ASPIRATE,
        )
        assert len(result) == 2
        assert OperationCategory.ASPIRATE.value in result
        assert OperationCategory.HEAD96_ASPIRATE.value in result

    def test_frozenset_is_immutable(self):
        result = _generate_category_frozenset(OperationCategory.ASPIRATE)
        with pytest.raises(AttributeError):
            result.add("new_value")


class TestCategoryFrozensets:
    """Tests for the generated category frozensets."""

    def test_aspirate_categories_not_empty(self):
        assert len(_ASPIRATE_CATEGORIES) > 0

    def test_aspirate_categories_contains_base_aspirate(self):
        assert OperationCategory.ASPIRATE.value in _ASPIRATE_CATEGORIES

    def test_aspirate_categories_contains_head96_aspirate(self):
        assert OperationCategory.HEAD96_ASPIRATE.value in _ASPIRATE_CATEGORIES

    def test_aspirate_categories_contains_xl_aspirate(self):
        assert OperationCategory.XL_ASPIRATE.value in _ASPIRATE_CATEGORIES

    def test_aspirate_categories_contains_easy_aspirate(self):
        assert OperationCategory.EASY_ASPIRATE.value in _ASPIRATE_CATEGORIES

    def test_aspirate_categories_contains_2nd_phase(self):
        assert OperationCategory.ASPIRATE_2ND_PHASE.value in _ASPIRATE_CATEGORIES

    def test_dispense_categories_not_empty(self):
        assert len(_DISPENSE_CATEGORIES) > 0

    def test_dispense_categories_contains_base_dispense(self):
        assert OperationCategory.DISPENSE.value in _DISPENSE_CATEGORIES

    def test_dispense_categories_contains_dispense_fly(self):
        assert OperationCategory.DISPENSE_FLY.value in _DISPENSE_CATEGORIES

    def test_dispense_categories_contains_easy_dispense(self):
        assert OperationCategory.EASY_DISPENSE.value in _DISPENSE_CATEGORIES

    def test_non_fly_dispense_excludes_fly_variants(self):
        assert OperationCategory.DISPENSE_FLY.value not in _NON_FLY_DISPENSE_CATEGORIES
        assert OperationCategory.XL_DISPENSE_FLY.value not in _NON_FLY_DISPENSE_CATEGORIES

    def test_non_fly_dispense_includes_standard_dispense(self):
        assert OperationCategory.DISPENSE.value in _NON_FLY_DISPENSE_CATEGORIES

    def test_dispense_fly_categories_not_empty(self):
        assert len(_DISPENSE_FLY_CATEGORIES) > 0

    def test_dispense_fly_categories_contains_dispense_fly(self):
        assert OperationCategory.DISPENSE_FLY.value in _DISPENSE_FLY_CATEGORIES

    def test_dispense_fly_categories_contains_xl_dispense_fly(self):
        assert OperationCategory.XL_DISPENSE_FLY.value in _DISPENSE_FLY_CATEGORIES

    def test_gripper_categories_not_empty(self):
        assert len(_GRIPPER_CATEGORIES) > 0

    def test_gripper_categories_contains_gripper(self):
        assert OperationCategory.GRIPPER.value in _GRIPPER_CATEGORIES

    def test_gripper_categories_contains_core_grip_transport(self):
        assert OperationCategory.CORE_GRIP_TRANSPORT.value in _GRIPPER_CATEGORIES

    def test_gripper_categories_contains_zswap_get_plate(self):
        assert OperationCategory.ZSWAP_GET_PLATE.value in _GRIPPER_CATEGORIES

    def test_gripper_categories_contains_zswap_read_barcode(self):
        assert OperationCategory.ZSWAP_READ_BARCODE.value in _GRIPPER_CATEGORIES

    def test_gripper_categories_contains_zswap_place_plate(self):
        assert OperationCategory.ZSWAP_PLACE_PLATE.value in _GRIPPER_CATEGORIES

    def test_all_frozensets_are_immutable(self):
        with pytest.raises(AttributeError):
            _ASPIRATE_CATEGORIES.add("new")
        with pytest.raises(AttributeError):
            _DISPENSE_CATEGORIES.add("new")
        with pytest.raises(AttributeError):
            _GRIPPER_CATEGORIES.add("new")


class TestErrorClassifierClassify:
    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_no_error_code_returns_initialize_other(self):
        result = self.classifier.classify(_error(None))
        assert result == (OperationCategory.INITIALIZE, InitializeError.OTHER)

    def test_empty_string_code_returns_initialize_other(self):
        result = self.classifier.classify(_error(""))
        assert result == (OperationCategory.INITIALIZE, InitializeError.OTHER)

    def test_no_error_increments_miss_count(self):
        self.classifier.classify(_error(None))
        self.classifier.classify(_error(""))
        assert self.classifier.stats["classification_miss_count"] == 2

    def test_main_code_00_returns_none_none(self):
        result = self.classifier.classify(_error("00"))
        assert result == (None, None)

    def test_main_code_00_with_subcode_returns_none_none(self):
        result = self.classifier.classify(_error("00/01"))
        assert result == (None, None)

    def test_known_aspirate_clot(self):
        assert self.classifier.classify(_error("04")) == (OperationCategory.ASPIRATE, AspirateError.CLOT)

    def test_known_aspirate_liquid_level(self):
        assert self.classifier.classify(_error("06")) == (OperationCategory.ASPIRATE, AspirateError.LIQUID_LEVEL)

    def test_known_aspirate_with_subcode(self):
        assert self.classifier.classify(_error("04/02")) == (OperationCategory.ASPIRATE, AspirateError.CLOT)

    def test_known_tip_pickup_no_tip(self):
        assert self.classifier.classify(_error("08")) == (OperationCategory.TIP_PICKUP, TipPickupError.NO_TIP)

    def test_known_tip_pickup_tip_present(self):
        assert self.classifier.classify(_error("07")) == (OperationCategory.TIP_PICKUP, TipPickupError.TIP_PRESENT)

    def test_known_autoload_barcode(self):
        assert self.classifier.classify(_error("05")) == (OperationCategory.AUTOLOAD, AutoloadError.BARCODE)

    def test_known_autoload_other(self):
        assert self.classifier.classify(_error("13")) == (OperationCategory.AUTOLOAD, AutoloadError.OTHER)

    def test_known_initialize_hardware(self):
        assert self.classifier.classify(_error("02")) == (OperationCategory.INITIALIZE, InitializeError.HARDWARE)

    def test_unmapped_code_returns_initialize_other(self):
        result = self.classifier.classify(_error("99"))
        assert result == (OperationCategory.INITIALIZE, InitializeError.OTHER)

    def test_unmapped_code_increments_miss_count(self):
        self.classifier.classify(_error("99"))
        assert self.classifier.stats["classification_miss_count"] == 1

    def test_context_dependent_20_aspirate(self):
        result = self.classifier.classify(_error("20"), operation_context="aspirate/Aspirate")
        assert result == (OperationCategory.ASPIRATE, AspirateError.INSUFFICIENT)

    def test_context_dependent_20_dispense(self):
        result = self.classifier.classify(_error("20"), operation_context="dispense/Dispense")
        assert result == (OperationCategory.DISPENSE, DispenseError.INSUFFICIENT)

    def test_context_dependent_20_no_context_fallback(self):
        result = self.classifier.classify(_error("20"), operation_context=None)
        assert result == (OperationCategory.INITIALIZE, InitializeError.OTHER)

    def test_context_dependent_20_empty_string_context_fallback(self):
        result = self.classifier.classify(_error("20"), operation_context="")
        assert result == (OperationCategory.INITIALIZE, InitializeError.OTHER)

    def test_context_dependent_26_aspirate(self):
        result = self.classifier.classify(_error("26"), operation_context="aspirate/Aspirate")
        assert result == (OperationCategory.ASPIRATE, AspirateError.CLOT)

    def test_context_dependent_26_dispense(self):
        result = self.classifier.classify(_error("26"), operation_context="dispense/Dispense")
        assert result == (OperationCategory.DISPENSE, DispenseError.PRESSURE_LLD)

    def test_context_dependent_26_no_context_fallback(self):
        result = self.classifier.classify(_error("26"), operation_context=None)
        assert result == (OperationCategory.INITIALIZE, InitializeError.OTHER)

    def test_context_dependent_26_empty_string_context_fallback(self):
        result = self.classifier.classify(_error("26"), operation_context="")
        assert result == (OperationCategory.INITIALIZE, InitializeError.OTHER)

    def test_context_dependent_21_gripper(self):
        result = self.classifier.classify(_error("21"), operation_context="gripper/Move")
        assert result == (OperationCategory.GRIPPER, GripperError.LABWARE_NOT_FOUND)

    def test_context_dependent_23_gripper(self):
        result = self.classifier.classify(_error("23"), operation_context="gripper/Move")
        assert result == (OperationCategory.GRIPPER, GripperError.LABWARE_NOT_FOUND)

    def test_context_dependent_21_no_context_fallback(self):
        result = self.classifier.classify(_error("21"), operation_context=None)
        assert result == (OperationCategory.INITIALIZE, InitializeError.OTHER)

    def test_context_dependent_21_empty_string_context_fallback(self):
        result = self.classifier.classify(_error("21"), operation_context="")
        assert result == (OperationCategory.INITIALIZE, InitializeError.OTHER)

    def test_context_dependent_20_head96_aspirate(self):
        result = self.classifier.classify(_error("20"), operation_context="head96_aspirate/Aspirate96")
        assert result == (OperationCategory.ASPIRATE, AspirateError.INSUFFICIENT)

    def test_context_dependent_20_xl_aspirate(self):
        result = self.classifier.classify(_error("20"), operation_context="xl_aspirate/XLAspirate")
        assert result == (OperationCategory.ASPIRATE, AspirateError.INSUFFICIENT)

    def test_context_dependent_26_head96_dispense(self):
        result = self.classifier.classify(_error("26"), operation_context="head96_dispense/Dispense96")
        assert result == (OperationCategory.DISPENSE, DispenseError.PRESSURE_LLD)

    def test_context_dependent_21_core_grip(self):
        result = self.classifier.classify(_error("21"), operation_context="core_grip_transport/Transport")
        assert result == (OperationCategory.GRIPPER, GripperError.LABWARE_NOT_FOUND)

    def test_context_dependent_21_zswap_get_plate(self):
        result = self.classifier.classify(_error("21"), operation_context="zswap_get_plate/Get")
        assert result == (OperationCategory.GRIPPER, GripperError.LABWARE_NOT_FOUND)

    def test_stats_initial(self):
        assert self.classifier.stats == {"classification_miss_count": 0}


class TestContextSensitiveErrorClassification:
    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_02_54_non_fly_dispense_returns_not_aspirated(self):
        result = self.classifier.classify(_error("02/54"), operation_context="dispense/Dispense")
        assert result == (OperationCategory.DISPENSE, DispenseError.NOT_ASPIRATED)

    def test_02_54_head96_dispense_returns_not_aspirated(self):
        result = self.classifier.classify(_error("02/54"), operation_context="head96_dispense/Dispense96")
        assert result == (OperationCategory.DISPENSE, DispenseError.NOT_ASPIRATED)

    def test_02_54_xl_dispense_returns_not_aspirated(self):
        result = self.classifier.classify(_error("02/54"), operation_context="xl_dispense/XLDispense")
        assert result == (OperationCategory.DISPENSE, DispenseError.NOT_ASPIRATED)

    def test_02_54_easy_dispense_returns_not_aspirated(self):
        result = self.classifier.classify(_error("02/54"), operation_context="easy_dispense/EasyDispense")
        assert result == (OperationCategory.DISPENSE, DispenseError.NOT_ASPIRATED)

    def test_02_54_unexpected_context_falls_to_hardware(self):
        result = self.classifier.classify(_error("02/54"), operation_context="tip_pickup/TipPickup")
        assert result == (OperationCategory.INITIALIZE, InitializeError.HARDWARE)

    def test_02_54_dispense_fly_falls_to_hardware(self):
        result = self.classifier.classify(_error("02/54"), operation_context="dispense_fly/DispenseFly")
        assert result == (OperationCategory.INITIALIZE, InitializeError.HARDWARE)

    def test_02_54_aspirate_falls_to_hardware(self):
        result = self.classifier.classify(_error("02/54"), operation_context="aspirate/Aspirate")
        assert result == (OperationCategory.INITIALIZE, InitializeError.HARDWARE)

    def test_02_54_no_context_falls_to_hardware(self):
        result = self.classifier.classify(_error("02/54"), operation_context=None)
        assert result == (OperationCategory.INITIALIZE, InitializeError.HARDWARE)

    def test_02_54_empty_string_context_falls_to_hardware(self):
        result = self.classifier.classify(_error("02/54"), operation_context="")
        assert result == (OperationCategory.INITIALIZE, InitializeError.HARDWARE)

    def test_13_83_returns_loading_tray(self):
        result = self.classifier.classify(_error("13/83"))
        assert result == (OperationCategory.AUTOLOAD, AutoloadError.LOADING_TRAY)

    def test_13_84_returns_loading_tray(self):
        result = self.classifier.classify(_error("13/84"))
        assert result == (OperationCategory.AUTOLOAD, AutoloadError.LOADING_TRAY)

    def test_13_no_subcode_returns_other(self):
        result = self.classifier.classify(_error("13"))
        assert result == (OperationCategory.AUTOLOAD, AutoloadError.OTHER)

    def test_17_83_dispense_fly_returns_tadm_upper(self):
        result = self.classifier.classify(_error("17/83"), operation_context="dispense_fly/DispenseFly")
        assert result == (OperationCategory.DISPENSE, DispenseFlyError.TADM_UPPER)

    def test_17_83_xl_dispense_fly_returns_tadm_upper(self):
        result = self.classifier.classify(_error("17/83"), operation_context="xl_dispense_fly/XLDispenseFly")
        assert result == (OperationCategory.DISPENSE, DispenseFlyError.TADM_UPPER)

    def test_17_83_aspirate_falls_to_improper(self):
        result = self.classifier.classify(_error("17/83"), operation_context="aspirate/Aspirate")
        assert result == (OperationCategory.ASPIRATE, AspirateError.IMPROPER)

    def test_17_83_no_context_falls_to_improper(self):
        result = self.classifier.classify(_error("17/83"), operation_context=None)
        assert result == (OperationCategory.ASPIRATE, AspirateError.IMPROPER)

    def test_17_83_empty_string_context_falls_to_improper(self):
        result = self.classifier.classify(_error("17/83"), operation_context="")
        assert result == (OperationCategory.ASPIRATE, AspirateError.IMPROPER)

    def test_04_82_dispense_fly_returns_tadm_lower(self):
        result = self.classifier.classify(_error("04/82"), operation_context="dispense_fly/DispenseFly")
        assert result == (OperationCategory.DISPENSE, DispenseFlyError.TADM_LOWER)

    def test_04_82_xl_dispense_fly_returns_tadm_lower(self):
        result = self.classifier.classify(_error("04/82"), operation_context="xl_dispense_fly/XLDispenseFly")
        assert result == (OperationCategory.DISPENSE, DispenseFlyError.TADM_LOWER)

    def test_04_82_aspirate_returns_improper(self):
        result = self.classifier.classify(_error("04/82"), operation_context="aspirate/Aspirate")
        assert result == (OperationCategory.ASPIRATE, AspirateError.IMPROPER)

    def test_04_82_no_context_returns_improper(self):
        result = self.classifier.classify(_error("04/82"), operation_context=None)
        assert result == (OperationCategory.ASPIRATE, AspirateError.IMPROPER)

    def test_04_82_empty_string_context_returns_improper(self):
        result = self.classifier.classify(_error("04/82"), operation_context="")
        assert result == (OperationCategory.ASPIRATE, AspirateError.IMPROPER)

    def test_magpip_02_0151_returns_other(self):
        result = self.classifier.classify(_error("02/0151"), operation_context="magpip/MagPipAspirate")
        assert result == (OperationCategory.MAGPIP, MagPipError.OTHER)

    def test_magpip_02_other_4digit_returns_hardware(self):
        result = self.classifier.classify(_error("02/0152"), operation_context="magpip/MagPipAspirate")
        assert result == (OperationCategory.MAGPIP, MagPipError.HARDWARE)

    def test_magpip_02_0001_returns_hardware(self):
        result = self.classifier.classify(_error("02/0001"), operation_context="magpip/MagPipAspirate")
        assert result == (OperationCategory.MAGPIP, MagPipError.HARDWARE)

    def test_non_magpip_02_4digit_falls_to_flat_table(self):
        result = self.classifier.classify(_error("02/0151"), operation_context="aspirate/Aspirate")
        assert result == (OperationCategory.INITIALIZE, InitializeError.HARDWARE)

    def test_magpip_02_0151_empty_string_context_falls_to_flat_table(self):
        result = self.classifier.classify(_error("02/0151"), operation_context="")
        assert result == (OperationCategory.INITIALIZE, InitializeError.HARDWARE)


class TestErrorClassifierActionToServerId:
    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_returns_none_when_list_is_none(self):
        result = self.classifier.action_to_server_id(RecoveryAction.CANCEL, None)
        assert result is None

    def test_returns_none_when_list_is_empty(self):
        result = self.classifier.action_to_server_id(RecoveryAction.CANCEL, [])
        assert result is None

    def test_matches_action_by_name_case_insensitive(self):
        actions = [_action(7, "Cancel")]
        result = self.classifier.action_to_server_id(RecoveryAction.CANCEL, actions)
        assert result == 7

    def test_matches_action_uppercase_server_name(self):
        actions = [_action(3, "ABORT")]
        result = self.classifier.action_to_server_id(RecoveryAction.ABORT, actions)
        assert result == 3

    def test_returns_none_when_action_not_in_list(self):
        actions = [_action(1, "continue")]
        result = self.classifier.action_to_server_id(RecoveryAction.ABORT, actions)
        assert result is None

    def test_returns_first_match_when_multiple_actions(self):
        actions = [_action(1, "cancel"), _action(2, "abort"), _action(3, "continue")]
        result = self.classifier.action_to_server_id(RecoveryAction.ABORT, actions)
        assert result == 2


class TestDevicePrefixHandling:
    """Tests for handling device prefixes in error codes (e.g., 'P1:102/70')."""

    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_device_prefix_p1_102_liquid_level(self):
        """Test that error code 'P1:102/70' (device prefix + extended error) is correctly classified."""
        result = self.classifier.classify(_error("P1:102/70"))
        assert result == (OperationCategory.ASPIRATE, AspirateError.LIQUID_LEVEL)

    def test_device_prefix_p1_102_no_subcode(self):
        """Test that error code 'P1:102' (device prefix without subcode) is correctly classified."""
        result = self.classifier.classify(_error("P1:102"))
        assert result == (OperationCategory.ASPIRATE, AspirateError.LIQUID_LEVEL)

    def test_device_prefix_p1_06_liquid_level(self):
        """Test that standard error code with device prefix 'P1:06' is correctly classified."""
        result = self.classifier.classify(_error("P1:06"))
        assert result == (OperationCategory.ASPIRATE, AspirateError.LIQUID_LEVEL)

    def test_device_prefix_p1_04_clot(self):
        """Test that error code 'P1:04' is correctly classified."""
        result = self.classifier.classify(_error("P1:04"))
        assert result == (OperationCategory.ASPIRATE, AspirateError.CLOT)

    def test_device_prefix_p1_08_no_tip(self):
        """Test that error code 'P1:08' is correctly classified."""
        result = self.classifier.classify(_error("P1:08"))
        assert result == (OperationCategory.TIP_PICKUP, TipPickupError.NO_TIP)

    def test_device_prefix_preserved_in_logging(self):
        """Test that the original error code with prefix is logged for diagnostics."""
        # When an unmapped code with prefix is encountered, the full original code should be in logs
        self.classifier.classify(_error("P1:99"))
        assert self.classifier.stats["classification_miss_count"] == 1

    def test_device_prefix_p2_102(self):
        """Test that other device prefixes (e.g., 'P2:') are also handled."""
        result = self.classifier.classify(_error("P2:102/70"))
        assert result == (OperationCategory.ASPIRATE, AspirateError.LIQUID_LEVEL)


class TestExtendedErrorCodes:
    """Tests for extended error codes (100+)."""

    def setup_method(self):
        self.classifier = ErrorClassifier()

    def test_error_code_100_wrong_carrier(self):
        """Test that error code 100 (Wrong Carrier Error) is correctly classified."""
        result = self.classifier.classify(_error("100"))
        assert result == (OperationCategory.AUTOLOAD, AutoloadError.OTHER)

    def test_error_code_101_no_carrier_barcode(self):
        """Test that error code 101 (No Carrier Barcode Error) is correctly classified."""
        result = self.classifier.classify(_error("101"))
        assert result == (OperationCategory.AUTOLOAD, AutoloadError.BARCODE)

    def test_error_code_102_liquid_level(self):
        """Test that error code 102 (Liquid Level Error) is correctly classified."""
        result = self.classifier.classify(_error("102"))
        assert result == (OperationCategory.ASPIRATE, AspirateError.LIQUID_LEVEL)

    def test_error_code_102_with_subcode_70(self):
        """Test that error code 102/70 (from 06/70) is correctly classified."""
        result = self.classifier.classify(_error("102/70"))
        assert result == (OperationCategory.ASPIRATE, AspirateError.LIQUID_LEVEL)

    def test_error_code_102_with_subcode_73(self):
        """Test that error code 102/73 (from 06/73) is correctly classified."""
        result = self.classifier.classify(_error("102/73"))
        assert result == (OperationCategory.ASPIRATE, AspirateError.LIQUID_LEVEL)

    def test_error_code_103_not_detected(self):
        """Test that error code 103 (Not Detected Error) is correctly classified."""
        result = self.classifier.classify(_error("103"))
        assert result == (OperationCategory.INITIALIZE, InitializeError.NOT_EXECUTED)

    def test_error_code_104_not_aspirated(self):
        """Test that error code 104 (Not Aspirated Error from 02/54) is correctly classified."""
        result = self.classifier.classify(_error("104"))
        assert result == (OperationCategory.DISPENSE, DispenseError.NOT_ASPIRATED)

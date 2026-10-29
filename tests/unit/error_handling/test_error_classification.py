"""Unit tests for error classification and action-to-server-ID mapping."""

from __future__ import annotations

from hamilton_venus._internal._error_classifier import (
    ErrorClassifier,
    OperationCategory,
)
from hamilton_venus.models.error_types import (
    AspirateError,
    AutoloadError,
    InitializeError,
    RecoveryAction,
    TipPickupError,
)
from hamilton_venus.models.instrument_errors import (
    ErrorData,
    RecoveryActionDescriptor,
)


class TestErrorClassification:
    def test_no_error_fast_path(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code="00/00", message="No error")

        category, error_type = classifier.classify(error)

        assert category is None
        assert error_type is None
        assert classifier.stats["classification_miss_count"] == 0

    def test_clot_error_main_04(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code="04/01", message="Clot detected")

        category, error_type = classifier.classify(error)

        assert category == OperationCategory.ASPIRATE
        assert error_type == AspirateError.CLOT
        assert classifier.stats["classification_miss_count"] == 0

    def test_hardware_error_main_02(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code="02/05", message="Hardware error")

        category, error_type = classifier.classify(error)

        assert category == OperationCategory.INITIALIZE
        assert error_type == InitializeError.HARDWARE
        assert classifier.stats["classification_miss_count"] == 0

    def test_no_tip_error_main_08(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code="08/02", message="No tip")

        category, error_type = classifier.classify(error)

        assert category == OperationCategory.TIP_PICKUP
        assert error_type == TipPickupError.NO_TIP
        assert classifier.stats["classification_miss_count"] == 0

    def test_unmapped_main_code_fallback_to_other(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code="99/01", message="Unknown error")

        category, error_type = classifier.classify(error)

        assert category == OperationCategory.INITIALIZE
        assert error_type == InitializeError.OTHER
        assert classifier.stats["classification_miss_count"] == 1

    def test_context_dependent_main_20_fallback_to_other(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code="20/01", message="TADM Upper Limit")

        category, error_type = classifier.classify(error)

        assert category == OperationCategory.INITIALIZE
        assert error_type == InitializeError.OTHER
        assert classifier.stats["classification_miss_count"] == 0

    def test_context_dependent_main_26_fallback_to_other(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code="26/01", message="TADM Lower Limit")

        category, error_type = classifier.classify(error)

        assert category == OperationCategory.INITIALIZE
        assert error_type == InitializeError.OTHER
        assert classifier.stats["classification_miss_count"] == 0

    def test_context_dependent_main_21_fallback_to_other(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code="21/01", message="Unexpected Object")

        category, error_type = classifier.classify(error)

        assert category == OperationCategory.INITIALIZE
        assert error_type == InitializeError.OTHER
        assert classifier.stats["classification_miss_count"] == 0

    def test_context_dependent_main_23_fallback_to_other(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code="23/01", message="Object Lost")

        category, error_type = classifier.classify(error)

        assert category == OperationCategory.INITIALIZE
        assert error_type == InitializeError.OTHER
        assert classifier.stats["classification_miss_count"] == 0

    def test_missing_code_fallback_to_other(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code=None, message="No code")

        category, error_type = classifier.classify(error)

        assert category == OperationCategory.INITIALIZE
        assert error_type == InitializeError.OTHER
        assert classifier.stats["classification_miss_count"] == 1

    def test_empty_code_fallback_to_other(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code="", message="Empty code")

        category, error_type = classifier.classify(error)

        assert category == OperationCategory.INITIALIZE
        assert error_type == InitializeError.OTHER
        assert classifier.stats["classification_miss_count"] == 1

    def test_code_without_slash(self):
        classifier = ErrorClassifier()
        error = ErrorData(uuid="test-uuid", code="04", message="Code without slash")

        category, error_type = classifier.classify(error)

        assert category == OperationCategory.ASPIRATE
        assert error_type == AspirateError.CLOT
        assert classifier.stats["classification_miss_count"] == 0

    def test_miss_counter_accumulates(self):
        classifier = ErrorClassifier()
        error1 = ErrorData(uuid="uuid1", code="99/01", message="Unknown")
        error2 = ErrorData(uuid="uuid2", code="98/01", message="Unknown")
        error3 = ErrorData(uuid="uuid3", code=None, message="No code")

        classifier.classify(error1)
        assert classifier.stats["classification_miss_count"] == 1

        classifier.classify(error2)
        assert classifier.stats["classification_miss_count"] == 2

        classifier.classify(error3)
        assert classifier.stats["classification_miss_count"] == 3

    def test_various_main_codes(self):
        classifier = ErrorClassifier()
        test_cases = [
            ("01/01", OperationCategory.INITIALIZE, InitializeError.OTHER),
            ("03/01", OperationCategory.INITIALIZE, InitializeError.EXECUTION),
            ("05/01", OperationCategory.AUTOLOAD, AutoloadError.BARCODE),
            ("06/01", OperationCategory.ASPIRATE, AspirateError.LIQUID_LEVEL),
            ("07/01", OperationCategory.TIP_PICKUP, TipPickupError.TIP_PRESENT),
            ("10/01", OperationCategory.INITIALIZE, InitializeError.NOT_EXECUTED),
            ("13/01", OperationCategory.AUTOLOAD, AutoloadError.OTHER),
            ("14/01", OperationCategory.INITIALIZE, InitializeError.HARDWARE),
            ("17/01", OperationCategory.ASPIRATE, AspirateError.IMPROPER),
            ("25/01", OperationCategory.INITIALIZE, InitializeError.HARDWARE),
            ("28/01", OperationCategory.ASPIRATE, AspirateError.UNEXPECTED_CLLD),
            ("31/01", OperationCategory.ASPIRATE, AspirateError.ANTI_DROP),
        ]

        for code, expected_category, expected_error_type in test_cases:
            error = ErrorData(uuid="test", code=code, message="Test")
            category, error_type = classifier.classify(error)
            assert category == expected_category, f"Failed for code {code}"
            assert error_type == expected_error_type, f"Failed for code {code}"


class TestActionToServerIdMapping:
    def test_exact_case_match(self):
        classifier = ErrorClassifier()
        descriptors = [
            RecoveryActionDescriptor(id=1, name="abort", index=0),
            RecoveryActionDescriptor(id=2, name="repeat", index=1),
        ]

        action_id = classifier.action_to_server_id(RecoveryAction.ABORT, descriptors)

        assert action_id == 1

    def test_case_insensitive_match_uppercase_server(self):
        classifier = ErrorClassifier()
        descriptors = [
            RecoveryActionDescriptor(id=1, name="ABORT", index=0),
            RecoveryActionDescriptor(id=2, name="REPEAT", index=1),
        ]

        action_id = classifier.action_to_server_id(RecoveryAction.ABORT, descriptors)

        assert action_id == 1

    def test_case_insensitive_match_mixed_case_server(self):
        classifier = ErrorClassifier()
        descriptors = [
            RecoveryActionDescriptor(id=1, name="Abort", index=0),
            RecoveryActionDescriptor(id=2, name="Repeat", index=1),
        ]

        action_id = classifier.action_to_server_id(RecoveryAction.ABORT, descriptors)

        assert action_id == 1

    def test_multiple_actions_correct_match(self):
        classifier = ErrorClassifier()
        descriptors = [
            RecoveryActionDescriptor(id=1, name="abort", index=0),
            RecoveryActionDescriptor(id=2, name="repeat", index=1),
            RecoveryActionDescriptor(id=3, name="continue", index=2),
            RecoveryActionDescriptor(id=4, name="exclude", index=3),
        ]

        result_repeat = classifier.action_to_server_id(RecoveryAction.REPEAT, descriptors)
        result_exclude = classifier.action_to_server_id(RecoveryAction.EXCLUDE, descriptors)

        assert result_repeat == 2
        assert result_exclude == 4

    def test_action_not_in_recovery_actions(self):
        classifier = ErrorClassifier()
        descriptors = [
            RecoveryActionDescriptor(id=1, name="abort", index=0),
            RecoveryActionDescriptor(id=2, name="repeat", index=1),
        ]

        action_id = classifier.action_to_server_id(RecoveryAction.BARCODE, descriptors)

        assert action_id is None

    def test_empty_recovery_actions_list(self):
        classifier = ErrorClassifier()

        action_id = classifier.action_to_server_id(RecoveryAction.ABORT, [])

        assert action_id is None

    def test_none_recovery_actions(self):
        classifier = ErrorClassifier()

        action_id = classifier.action_to_server_id(RecoveryAction.ABORT, None)

        assert action_id is None

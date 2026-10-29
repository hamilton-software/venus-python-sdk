"""Unit tests for error-type enums and recovery action enums."""

from __future__ import annotations

import pytest

from hamilton_venus.models import ActionKind, RecoveryAction
from hamilton_venus.models.error_types import (
    Aspirate2ndPhaseError,
    AspirateError,
    AutoloadError,
    COREGripTransportError,
    CoverError,
    DispenseError,
    DispenseFlyError,
    EasyAspirateError,
    EasyDispenseError,
    GripperError,
    Head96AspirateError,
    Head96DispenseError,
    Head96TipPickUpError,
    InitializeError,
    MagPipError,
    MoveToPositionError,
    NeedleWashError,
    TipEjectError,
    TipPickupError,
    XLAspirateError,
    XLDispenseError,
    XLDispenseFlyError,
    XLTipEjectError,
    XLTipPickupError,
    ZSwapGetPlateError,
    ZSwapPlacePlateError,
    ZSwapReadBarcodeError,
)


class TestActionKindEnum:
    def test_action_kind_has_expected_members(self):
        assert hasattr(ActionKind, "RECOVERY")
        assert hasattr(ActionKind, "ACTION")

    def test_action_kind_values_are_strings(self):
        assert isinstance(ActionKind.RECOVERY.value, str)
        assert isinstance(ActionKind.ACTION.value, str)

    def test_action_kind_member_names_match(self):
        assert ActionKind.RECOVERY.name == "RECOVERY"
        assert ActionKind.ACTION.name == "ACTION"


class TestRecoveryActionEnum:
    def test_recovery_action_has_members(self):
        expected_members = [
            "CANCEL",
            "ABORT",
            "BOTTOM",
            "EXCLUDE",
            "CONTINUE",
            "REPEAT",
            "WASTE",
            "NEXT",
            "AIR",
            "AVAILABLE",
            "BARCODE",
            "INITIALIZE",
        ]
        for member in expected_members:
            assert hasattr(RecoveryAction, member), f"RecoveryAction missing {member}"

    def test_recovery_action_values_are_strings(self):
        for member in RecoveryAction:
            assert isinstance(member.value, str), f"{member.name} value is not a string"


class TestErrorTypeEnumsStructure:
    def test_all_error_enums_are_present(self):
        error_enum_classes = [
            AspirateError,
            Aspirate2ndPhaseError,
            AutoloadError,
            COREGripTransportError,
            CoverError,
            DispenseError,
            DispenseFlyError,
            EasyAspirateError,
            EasyDispenseError,
            GripperError,
            Head96AspirateError,
            Head96DispenseError,
            Head96TipPickUpError,
            InitializeError,
            MagPipError,
            MoveToPositionError,
            NeedleWashError,
            TipEjectError,
            TipPickupError,
            XLAspirateError,
            XLDispenseError,
            XLDispenseFlyError,
            XLTipEjectError,
            XLTipPickupError,
            ZSwapGetPlateError,
            ZSwapPlacePlateError,
            ZSwapReadBarcodeError,
        ]

        for enum_class in error_enum_classes:
            assert len(enum_class) > 0, f"{enum_class.__name__} has no members"

    def test_all_error_enum_values_are_strings(self):
        error_enum_classes = [
            AspirateError,
            Aspirate2ndPhaseError,
            AutoloadError,
            COREGripTransportError,
            CoverError,
            DispenseError,
            DispenseFlyError,
            EasyAspirateError,
            EasyDispenseError,
            GripperError,
            Head96AspirateError,
            Head96DispenseError,
            Head96TipPickUpError,
            InitializeError,
            MagPipError,
            MoveToPositionError,
            NeedleWashError,
            TipEjectError,
            TipPickupError,
            XLAspirateError,
            XLDispenseError,
            XLDispenseFlyError,
            XLTipEjectError,
            XLTipPickupError,
            ZSwapGetPlateError,
            ZSwapPlacePlateError,
            ZSwapReadBarcodeError,
        ]

        for enum_class in error_enum_classes:
            for member in enum_class:
                assert isinstance(member.value, str), f"{enum_class.__name__}.{member.name} value is not a string"

    def test_error_enum_members_have_names(self):
        error_enum_classes = [
            AspirateError,
            Aspirate2ndPhaseError,
            AutoloadError,
            COREGripTransportError,
            CoverError,
            DispenseError,
            DispenseFlyError,
            EasyAspirateError,
            EasyDispenseError,
            GripperError,
            Head96AspirateError,
            Head96DispenseError,
            Head96TipPickUpError,
            InitializeError,
            MagPipError,
            MoveToPositionError,
            NeedleWashError,
            TipEjectError,
            TipPickupError,
            XLAspirateError,
            XLDispenseError,
            XLDispenseFlyError,
            XLTipEjectError,
            XLTipPickupError,
            ZSwapGetPlateError,
            ZSwapPlacePlateError,
            ZSwapReadBarcodeError,
        ]

        for enum_class in error_enum_classes:
            for member in enum_class:
                assert hasattr(member, "name"), f"{enum_class.__name__} member missing name"
                assert isinstance(member.name, str)
                assert len(member.name) > 0


class TestSpecificErrorEnums:
    def test_tip_pickup_error_members(self):
        members = list(TipPickupError.__members__.keys())
        assert len(members) > 0
        assert all(isinstance(m.upper(), str) for m in members)

    def test_tip_eject_error_members(self):
        members = list(TipEjectError.__members__.keys())
        assert len(members) > 0
        assert all(isinstance(m.upper(), str) for m in members)

    def test_aspirate_error_members(self):
        members = list(AspirateError.__members__.keys())
        assert len(members) > 0

    def test_dispense_error_members(self):
        members = list(DispenseError.__members__.keys())
        assert len(members) > 0

    def test_dispense_fly_error_members(self):
        members = list(DispenseFlyError.__members__.keys())
        assert len(members) > 0

    def test_cover_error_members(self):
        members = list(CoverError.__members__.keys())
        assert len(members) > 0

    def test_gripper_error_members(self):
        members = list(GripperError.__members__.keys())
        assert len(members) > 0

    def test_autoload_error_members(self):
        members = list(AutoloadError.__members__.keys())
        assert len(members) > 0


class TestErrorEnumAccessibility:
    def test_all_error_enums_are_importable(self):
        try:
            from hamilton_venus.models.error_types import (
                Aspirate2ndPhaseError,
                AspirateError,
                AutoloadError,
                COREGripTransportError,
                CoverError,
                DispenseError,
                DispenseFlyError,
                EasyAspirateError,
                EasyDispenseError,
                GripperError,
                Head96AspirateError,
                Head96DispenseError,
                Head96TipPickUpError,
                InitializeError,
                MagPipError,
                MoveToPositionError,
                NeedleWashError,
                TipEjectError,
                TipPickupError,
                XLAspirateError,
                XLDispenseError,
                XLDispenseFlyError,
                XLTipEjectError,
                XLTipPickupError,
                ZSwapGetPlateError,
                ZSwapPlacePlateError,
                ZSwapReadBarcodeError,
            )

            assert all(
                [
                    Aspirate2ndPhaseError,
                    AspirateError,
                    AutoloadError,
                    COREGripTransportError,
                    CoverError,
                    DispenseError,
                    DispenseFlyError,
                    EasyAspirateError,
                    EasyDispenseError,
                    GripperError,
                    Head96AspirateError,
                    Head96DispenseError,
                    Head96TipPickUpError,
                    InitializeError,
                    MagPipError,
                    MoveToPositionError,
                    NeedleWashError,
                    TipEjectError,
                    TipPickupError,
                    XLAspirateError,
                    XLDispenseError,
                    XLDispenseFlyError,
                    XLTipEjectError,
                    XLTipPickupError,
                    ZSwapGetPlateError,
                    ZSwapPlacePlateError,
                    ZSwapReadBarcodeError,
                ]
            )
        except ImportError as e:
            pytest.fail(f"Failed to import error enums: {e}")

    def test_recovery_action_is_importable(self):
        try:
            from hamilton_venus.models import RecoveryAction

            assert RecoveryAction is not None
        except ImportError as e:
            pytest.fail(f"Failed to import RecoveryAction: {e}")

    def test_action_kind_is_importable(self):
        try:
            from hamilton_venus.models import ActionKind

            assert ActionKind is not None
        except ImportError as e:
            pytest.fail(f"Failed to import ActionKind: {e}")

    def test_all_error_exports_from_top_level(self):
        try:
            from hamilton_venus import (
                ActionKind,
                Aspirate2ndPhaseError,
                AspirateError,
                AutoloadError,
                COREGripTransportError,
                CoverError,
                DispenseError,
                DispenseFlyError,
                EasyAspirateError,
                EasyDispenseError,
                GripperError,
                Head96AspirateError,
                Head96DispenseError,
                Head96TipPickUpError,
                InitializeError,
                MagPipError,
                MoveToPositionError,
                NeedleWashError,
                RecoveryAction,
                TipEjectError,
                TipPickupError,
                XLAspirateError,
                XLDispenseError,
                XLDispenseFlyError,
                XLTipEjectError,
                XLTipPickupError,
            )

            assert all(
                [
                    ActionKind,
                    Aspirate2ndPhaseError,
                    AspirateError,
                    AutoloadError,
                    COREGripTransportError,
                    CoverError,
                    DispenseError,
                    DispenseFlyError,
                    EasyAspirateError,
                    EasyDispenseError,
                    GripperError,
                    Head96AspirateError,
                    Head96DispenseError,
                    Head96TipPickUpError,
                    InitializeError,
                    MagPipError,
                    MoveToPositionError,
                    NeedleWashError,
                    RecoveryAction,
                    TipEjectError,
                    TipPickupError,
                    XLAspirateError,
                    XLDispenseError,
                    XLDispenseFlyError,
                    XLTipEjectError,
                    XLTipPickupError,
                ]
            )
        except ImportError as e:
            pytest.fail(f"Failed to import from top-level hamilton_venus: {e}")


class TestAllErrorEnumsAreStringEnums:
    def test_all_error_enum_members_are_strings(self):
        error_enums = [
            AspirateError,
            Aspirate2ndPhaseError,
            AutoloadError,
            COREGripTransportError,
            CoverError,
            DispenseError,
            DispenseFlyError,
            EasyAspirateError,
            EasyDispenseError,
            GripperError,
            Head96AspirateError,
            Head96DispenseError,
            Head96TipPickUpError,
            InitializeError,
            MagPipError,
            MoveToPositionError,
            NeedleWashError,
            TipEjectError,
            TipPickupError,
            XLAspirateError,
            XLDispenseError,
            XLDispenseFlyError,
            XLTipEjectError,
            XLTipPickupError,
            ZSwapGetPlateError,
            ZSwapPlacePlateError,
            ZSwapReadBarcodeError,
        ]

        for enum_class in error_enums:
            for member in enum_class:
                assert isinstance(member.value, str), f"{enum_class.__name__}.{member.name} value is not a string"


class TestErrorTypeMixinHashEquality:
    def test_same_value_different_class_share_same_string_value(self):
        assert TipPickupError.EXECUTION.value == TipEjectError.EXECUTION.value
        assert TipPickupError.EXECUTION is not TipEjectError.EXECUTION

    def test_same_value_different_class_have_different_hashes(self):
        assert hash(TipPickupError.EXECUTION) != hash(TipEjectError.EXECUTION)

    def test_same_class_same_member_is_equal(self):
        assert TipPickupError.EXECUTION == TipPickupError.EXECUTION

    def test_same_class_different_member_not_equal(self):
        assert TipPickupError.EXECUTION != TipPickupError.NO_TIP

    def test_cross_class_not_used_as_same_dict_key(self):
        d = {TipPickupError.EXECUTION: "pickup", TipEjectError.EXECUTION: "eject"}
        assert len(d) == 2
        assert d[TipPickupError.EXECUTION] == "pickup"
        assert d[TipEjectError.EXECUTION] == "eject"

"""Channel-count limits read from the instrument configuration on connect."""

from __future__ import annotations

import asyncio
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus._internal._base_instrument_client import _InstrumentSyncClientBase
from hamilton_venus.config import SdkConfig
from hamilton_venus.exceptions import VenusCommandUnsupportedError
from hamilton_venus.models import CommandResponse
from hamilton_venus.models.position import LabwareLayoutSpec
from hamilton_venus.star_client import StarClient

# Captured at import, before the conftest autouse fixture stubs it out.
_REAL_LOAD_INSTRUMENT_CONFIG = _InstrumentSyncClientBase._load_instrument_config


def _configuration_response(**return_parameters) -> CommandResponse:
    return CommandResponse(return_status="Success", return_code=0, return_parameters=return_parameters)


@pytest.fixture
def config():
    return SdkConfig(base_url="http://test:42400")


@pytest.fixture
def mock_async_star_class():
    spec = LabwareLayoutSpec.from_definition({"rack_layout": {"rows": 8, "columns": 12}})
    with (
        patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient") as cls,
        patch.object(StarClient, "get_labware_spec", return_value=spec),
    ):
        star = MagicMock()
        star.start = AsyncMock()
        star.stop = AsyncMock()
        star.venus = MagicMock()
        star.venus.send_command = AsyncMock(return_value=_configuration_response())
        cls.return_value = star
        yield cls


def _load_config(client: StarClient) -> None:
    asyncio.run(_REAL_LOAD_INSTRUMENT_CONFIG(client))


class TestLoadChannelLimits:
    def test_reads_per_module_totals_from_configuration(self, config, mock_async_star_class):
        venus = mock_async_star_class.return_value.venus
        venus.send_command.return_value = _configuration_response(
            LeftArm={"channels1mL": {"total": 12}, "channels5mL": {"total": 4}},
            RightArm={"channels1mL": {"total": 8}},
        )
        with StarClient(config) as client:
            _load_config(client)

        # The larger arm total wins; modules the instrument lacks are omitted.
        assert client._channel_limits == {"channels.1mL": 12, "channels.5mL": 4}
        venus.send_command.assert_awaited_with(category="Instrument", action_name="configuration.getConfiguration")

    def test_channel_types_skip_modules_whose_arms_disagree(self, config, mock_async_star_class):
        venus = mock_async_star_class.return_value.venus
        venus.send_command.return_value = _configuration_response(
            LeftArm={
                "channels1mL": {"total": 8, "type": "Fluid Motion"},
                "channels5mL": {"total": 4, "type": "Legacy"},
            },
            RightArm={"channels1mL": {"total": 8, "type": "Legacy"}},
        )
        with StarClient(config) as client:
            _load_config(client)
        # 1mL arms disagree so it is skipped; the 5mL module is only on one arm.
        assert client._channel_types == {"channels.5mL": "Legacy"}

        venus.send_command.return_value = _configuration_response(
            LeftArm={"channels1mL": {"total": 8, "type": "Fluid Motion"}},
            RightArm={},
        )
        with StarClient(config) as client:
            _load_config(client)
        assert client._channel_types == {"channels.1mL": "Fluid Motion"}

    def test_query_failure_keeps_previous_limits(self, config, mock_async_star_class):
        venus = mock_async_star_class.return_value.venus
        venus.send_command.side_effect = RuntimeError("boom")
        with StarClient(config) as client:
            client._channel_limits = {"channels.1mL": 8}
            _load_config(client)

        assert client._channel_limits == {"channels.1mL": 8}


class TestChannelLimitValidation:
    def test_uses_instrument_reported_limit(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._channel_limits = {"channels.1mL": 8}
            with pytest.raises(ValueError, match="1mL support a maximum of 8"):
                client.tip_pickup(channels=list(range(1, 10)), positions="TipRack@col:1")

    def test_allows_more_than_eight_when_instrument_has_them(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._channel_limits = {"channels.1mL": 12}
            client.tip_pickup(channels=list(range(1, 13)), tip_pool="TransferTips")

    def test_rejects_channel_numbers_above_reported_total(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._channel_limits = {"channels.1mL": 8}
            with pytest.raises(ValueError, match="between 1 and 8, but got: \\[9, 10\\]"):
                client.tip_pickup(channels=[9, 10], tip_pool="TransferTips")

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(lambda c: c.tip_pickup(channels=[], tip_pool="TransferTips"), id="tip_pickup"),
            pytest.param(lambda c: c.tip_eject(channels=[]), id="tip_eject"),
            pytest.param(
                lambda c: c.aspirate("Tubes@all", channels=[], volumes=75.0, liquid_class="Water"),
                id="aspirate",
            ),
            pytest.param(lambda c: c.dispense("Plate@col:1", channels=[], volumes=75.0), id="dispense"),
        ],
    )
    def test_rejects_empty_channel_list(self, config, mock_async_star_class, call):
        # An empty list used to slip through: channel_count became 0, the selector
        # expanded to zero positions, and VENUS answered "positions has no positions defined".
        with StarClient(config) as client, pytest.raises(ValueError, match="channels must not be empty"):
            call(client)

    def test_none_channels_still_means_default(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client.tip_pickup(channels=None, tip_pool="TransferTips")

    def test_rejects_channel_number_below_one(self, config, mock_async_star_class):
        with StarClient(config) as client, pytest.raises(ValueError, match="between 1 and 16, but got: \\[0\\]"):
            client.tip_pickup(channels=[0, 1], tip_pool="TransferTips")

    def test_falls_back_to_sdk_ceiling_without_configuration(self, config, mock_async_star_class):
        with StarClient(config) as client:
            assert client._channel_limits == {}
            with pytest.raises(ValueError, match="1mL support a maximum of 16"):
                client.tip_pickup(channels=list(range(1, 18)), positions="TipRack@col:1")


class TestOptionalHardwareGuard:
    @staticmethod
    def _configure(client: StarClient, **return_parameters) -> None:
        venus = client._instrument.venus
        venus.send_command.return_value = _configuration_response(**return_parameters)
        _load_config(client)

    def test_flags_reflect_configuration(self, config, mock_async_star_class):
        with StarClient(config) as client:
            self._configure(
                client,
                Autoload=True,
                LeftArm={"MPH96": {"total": 96}, "gripper": {"type": "iSWAP"}},
                RightArm={},
            )
        assert client._feature_support == {"mph96": True, "autoload": True, "gripper": True}

    def test_missing_hardware_is_flagged_unavailable(self, config, mock_async_star_class):
        with StarClient(config) as client:
            self._configure(client, Autoload=False, LeftArm={"MPH96": None, "gripper": {}}, RightArm={})
        assert client._feature_support == {"mph96": False, "autoload": False, "gripper": False}

    @pytest.mark.parametrize(
        ("action_name", "label"),
        [
            ("mph96.aspirate", "MPH96"),
            ("autoload.moveTo", "autoload"),
            ("transport.iswap.moveLabware", "iSWAP/IPG"),
        ],
    )
    def test_rejects_commands_for_unavailable_hardware(self, config, mock_async_star_class, action_name, label):
        with StarClient(config) as client:
            client._feature_support = {"mph96": False, "autoload": False, "gripper": False}
            with pytest.raises(VenusCommandUnsupportedError, match=label):
                client._check_command_supported("Instrument", action_name)

    def test_allows_commands_for_available_hardware(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._feature_support = {"mph96": True, "autoload": True, "gripper": True}
            for action_name in ("mph96.aspirate", "autoload.moveTo", "transport.iswap.park"):
                client._check_command_supported("Instrument", action_name)

    def test_nothing_rejected_before_configuration_is_read(self, config, mock_async_star_class):
        with StarClient(config) as client:
            assert client._feature_support == {}
            client._check_command_supported("Instrument", "mph96.aspirate")

    def test_other_commands_unaffected(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._feature_support = {"mph96": False, "autoload": False, "gripper": False}
            action_names = ("channels.1mL.tipPickup", "transport.1mL.moveLabware", "configuration.getConfiguration")
            for action_name in action_names:
                client._check_command_supported("Instrument", action_name)

    def test_guard_is_installed_on_venus_client(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._instrument.venus.set_command_guard.assert_called_once_with(client._check_command_supported)


class TestFrontChannelValidation:
    _TRANSPORT_ARGS: ClassVar = {"labware_name": "P", "carrier": "C", "site": "1", "grip_height_above_bottom": 5.0}

    def test_rejects_front_channel_above_reported_total(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._channel_limits = {"channels.1mL": 8}
            with pytest.raises(ValueError, match="1mL front_channel must be between 2 and 8, got 9"):
                client.core_transport(**self._TRANSPORT_ARGS, front_channel=9)

    def test_accepts_front_channel_up_to_reported_total(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._channel_limits = {"channels.1mL": 12}
            client.core_transport(**self._TRANSPORT_ARGS, front_channel=12)

    def test_uses_module_specific_limit(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._channel_limits = {"channels.1mL": 16, "channels.5mL": 4}
            client.core_transport(**self._TRANSPORT_ARGS, front_channel=8)
            with pytest.raises(ValueError, match="5mL front_channel must be between 2 and 4, got 8"):
                client.core_5ml_transport(**self._TRANSPORT_ARGS, front_channel=8)

    def test_core_gripper_needs_two_channels(self, config, mock_async_star_class):
        with StarClient(config) as client:
            with pytest.raises(ValueError, match=r"between 2 and 16, got 1 \(the CO-RE gripper spans 2 channels\)"):
                client.core_transport(**self._TRANSPORT_ARGS, front_channel=1)
            client.core_transport(**self._TRANSPORT_ARGS, front_channel=2)

    def test_fluid_motion_channels_use_four_channel_qcg(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._channel_types = {"channels.1mL": "Fluid Motion", "channels.5mL": "Legacy"}
            with pytest.raises(ValueError, match=r"between 4 and 16, got 3 \(the QCG spans 4 channels\)"):
                client.core_transport(**self._TRANSPORT_ARGS, front_channel=3)
            client.core_transport(**self._TRANSPORT_ARGS, front_channel=4)
            # The 5mL module is not Fluid Motion, so it keeps the 2-channel gripper.
            client.core_5ml_transport(**self._TRANSPORT_ARGS, front_channel=2)

    def test_vantage_uses_four_channel_qcg_without_configuration(self, config, mock_async_star_class):
        from hamilton_venus.vantage_client import VantageClient

        with VantageClient(config) as client, pytest.raises(ValueError, match="between 4 and 16, got 2"):
            client.core_transport(**self._TRANSPORT_ARGS, front_channel=2)

    def test_omitted_front_channel_is_not_validated(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._channel_limits = {"channels.1mL": 2}
            client.core_transport(**self._TRANSPORT_ARGS)

    @pytest.mark.parametrize(
        "method",
        ["core_transport_to_waste", "core_hold_lid", "core_5ml_transport_to_waste", "core_5ml_hold_lid"],
    )
    def test_other_front_channel_commands_validate(self, config, mock_async_star_class, method):
        with StarClient(config) as client:
            client._channel_limits = {"channels.1mL": 8, "channels.5mL": 8}
            with pytest.raises(ValueError, match="front_channel must be between 2 and 8, got 9"):
                getattr(client, method)(front_channel=9, **self._extra_args(method))

    @staticmethod
    def _extra_args(method: str) -> dict:
        if method.endswith("hold_lid"):
            return {"labware_name": "P", "grip_height_from_top": 5.0}
        return {"labware_name": "P", "grip_height_above_bottom": 5.0}


class TestGripperToolGuard:
    @pytest.mark.parametrize(
        ("action_name", "channel_type", "match"),
        [
            ("labware.addQCG", "Legacy", "adds a QCG, which needs Fluid Motion channels.*reports Legacy"),
            (
                "labware.add1mLCoreGrip",
                "Fluid Motion",
                "adds a CO-RE gripper, which needs Legacy channels.*reports Fluid",
            ),
        ],
    )
    def test_star_rejects_gripper_that_does_not_match_channel_type(
        self, config, mock_async_star_class, action_name, channel_type, match
    ):
        with StarClient(config) as client:
            client._channel_types = {"channels.1mL": channel_type}
            with pytest.raises(VenusCommandUnsupportedError, match=match):
                client._check_command_supported("Deck Layout", action_name)

    @pytest.mark.parametrize(
        ("action_name", "channel_type"),
        [("labware.addQCG", "Fluid Motion"), ("labware.add1mLCoreGrip", "Legacy")],
    )
    def test_star_allows_matching_gripper(self, config, mock_async_star_class, action_name, channel_type):
        with StarClient(config) as client:
            client._channel_types = {"channels.1mL": channel_type}
            client._check_command_supported("Deck Layout", action_name)

    @pytest.mark.parametrize("action_name", ["labware.addQCG", "labware.add1mLCoreGrip"])
    def test_nothing_rejected_when_channel_type_unknown(self, config, mock_async_star_class, action_name):
        with StarClient(config) as client:
            assert client._channel_types == {}
            client._check_command_supported("Deck Layout", action_name)

    def test_5ml_core_grip_is_not_gated(self, config, mock_async_star_class):
        with StarClient(config) as client:
            client._channel_types = {"channels.1mL": "Fluid Motion"}
            client._check_command_supported("Deck Layout", "labware.add5mLCoreGrip")

    def test_vantage_is_not_gated(self, config, mock_async_star_class):
        from hamilton_venus.vantage_client import VantageClient

        with VantageClient(config) as client:
            client._channel_types = {"channels.1mL": "Legacy"}
            client._check_command_supported("Deck Layout", "labware.addQCG")

    @pytest.mark.parametrize("action_name", ["transport.1mL.presentAndScan", "transport.iswap.presentAndScan"])
    def test_present_and_scan_rejected_on_vantage(self, config, mock_async_star_class, action_name):
        from hamilton_venus.vantage_client import VantageClient

        with (
            VantageClient(config) as client,
            pytest.raises(VenusCommandUnsupportedError, match="not supported on a Vantage"),
        ):
            client._check_command_supported("Instrument", action_name)

        with StarClient(config) as client:
            client._check_command_supported("Instrument", action_name)

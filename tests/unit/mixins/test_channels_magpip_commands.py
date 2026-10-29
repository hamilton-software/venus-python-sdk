"""Unit tests for ChannelsMagPipCommandsMixin (Vantage MagPip channels)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import (
    AspirateSettings,
    CommandResponse,
    DispenseSettings,
    TadmMode,
    TadmRecording,
    TadmSettings,
)
from hamilton_venus.models.enums import CapacitiveLLD, EjectMode
from hamilton_venus.vantage_client import VantageClient


@pytest.fixture
def config():
    return SdkConfig(base_url="http://test:42400")


@pytest.fixture
def mock_async_instrument_class():
    from hamilton_venus.models.position import LabwareLayoutSpec

    _default_spec = LabwareLayoutSpec.from_definition({"rack_layout": {"rows": 8, "columns": 12}})
    with (
        patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient") as cls,
        patch.object(VantageClient, "get_labware_spec", return_value=_default_spec),
    ):
        instrument = MagicMock()
        instrument.start = AsyncMock()
        instrument.stop = AsyncMock()

        venus = MagicMock()
        venus.send_command = AsyncMock(
            return_value=CommandResponse(return_status="Success", return_code=0, return_parameters={}),
        )
        instrument.venus = venus
        cls.return_value = instrument
        yield cls


class TestMagPipTipCommands:
    def test_tip_pickup_magpip_with_pool(self, config, mock_async_instrument_class):
        instrument = mock_async_instrument_class.return_value
        with VantageClient(config) as client:
            result = client.tip_pickup_magpip(channels=[1, 2, 3], tip_pool="TransferTips")

        assert result.success is True
        instrument.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.MagPip.tipPickup",
            parameters={"channels": [1, 2, 3], "tipPool": "TransferTips", "optimizedPickup": True},
        )

    def test_tip_eject_magpip_defaults_to_waste(self, config, mock_async_instrument_class):
        instrument = mock_async_instrument_class.return_value
        with VantageClient(config) as client:
            result = client.tip_eject_magpip(channels=[1], eject_mode=EjectMode.WASTE)

        assert result.success is True
        call = instrument.venus.send_command.await_args
        assert call.kwargs["action_name"] == "channels.MagPip.tipEject"
        assert call.kwargs["parameters"]["ejectMode"] == "waste"

    def test_tip_check_magpip_action_name(self, config, mock_async_instrument_class):
        instrument = mock_async_instrument_class.return_value
        instrument.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"activeChannels": [{"channel": 1, "tipType": 0, "tipName": "1000ul Tip"}]},
            )
        )
        with VantageClient(config) as client:
            result = client.tip_check_magpip()

        assert result.success is True
        instrument.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.MagPip.tipCheck",
        )


class TestMagPipAspirate:
    def test_aspirate_magpip_basic_no_tip_tracking_factor(self, config, mock_async_instrument_class):
        instrument = mock_async_instrument_class.return_value
        instrument.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"channels": [{"channel": 1, "aspiratedVolume": 100}]},
            )
        )
        with VantageClient(config) as client:
            result = client.aspirate_magpip(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=100.0,
                liquid_class="Water_DispenseJet_Empty",
                settings=AspirateSettings(tip_tracking_factor=2.0),
            )

        assert result.success is True
        params = instrument.venus.send_command.await_args.kwargs["parameters"]
        assert instrument.venus.send_command.await_args.kwargs["action_name"] == "channels.MagPip.aspirate"
        assert "tipTrackingFactor" not in params
        assert "TADM" not in params

    def test_aspirate_magpip_with_tadm_and_mad_and_adc(self, config, mock_async_instrument_class):
        instrument = mock_async_instrument_class.return_value
        instrument.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success", return_code=0, return_parameters={"channels": []}
            )
        )
        with VantageClient(config) as client:
            client.aspirate_magpip(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=100.0,
                liquid_class="Water_DispenseJet_Empty",
                mad_enabled=True,
                mad_threshold=200,
                adc=True,
                tadm=TadmSettings(enabled=TadmMode.MONITORING, recording=TadmRecording.ERROR_CURVES_ONLY),
            )

        params = instrument.venus.send_command.await_args.kwargs["parameters"]
        assert params["madEnabled"] is True
        assert params["madThreshold"] == 200
        assert params["ADC"] is True
        assert params["TADM"] == {"enabled": 2, "recording": 1}

    def test_aspirate_magpip_channel_validation_names_magpip(self, config, mock_async_instrument_class):
        with VantageClient(config) as client, pytest.raises(ValueError, match="MagPip support a maximum of 16"):
            client.aspirate_magpip(
                positions="Plate_1@col:1",
                channels=list(range(1, 18)),
                volumes=100.0,
                liquid_class="Water_DispenseJet_Empty",
            )


class TestMagPipDispense:
    def test_dispense_magpip_with_tadm(self, config, mock_async_instrument_class):
        instrument = mock_async_instrument_class.return_value
        instrument.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success", return_code=0, return_parameters={"channels": []}
            )
        )
        with VantageClient(config) as client:
            client.dispense_magpip(
                positions="Plate_1@col:1",
                channels=[1, 2],
                volumes=100.0,
                settings=DispenseSettings(capacitive_lld=CapacitiveLLD.MAX),
                tadm=TadmSettings(),
            )

        params = instrument.venus.send_command.await_args.kwargs["parameters"]
        assert instrument.venus.send_command.await_args.kwargs["action_name"] == "channels.MagPip.dispense"
        assert "tipTrackingFactor" not in params
        assert params["TADM"] == {"enabled": 0, "recording": 2}
        assert params["capacitiveLLD"] == CapacitiveLLD.MAX


class TestMagPipDispenseOnTheFly:
    def test_dispense_on_the_fly_magpip_minimal(self, config, mock_async_instrument_class):
        instrument = mock_async_instrument_class.return_value
        with VantageClient(config) as client:
            result = client.dispense_on_the_fly_magpip(
                channels=[1, 2],
                labware_name="plate 1",
                volumes=100.0,
                labware_surface_distance=3.0,
            )

        assert result.success is True
        instrument.venus.send_command.assert_awaited_once_with(
            category="Instrument",
            action_name="channels.MagPip.dispenseOnTheFly",
            parameters={
                "channels": [1, 2],
                "labwareName": "plate 1",
                "volumes": 100.0,
                "labwareSurfaceDistance": 3.0,
                "startXOffset": 0.0,
                "xSpeed": 0.0,
                "xAccelerationDistance": 8.0,
                "dispenseDirection": 0,
                "excludedPositions": [],
            },
        )

    def test_dispense_on_the_fly_magpip_with_adc_and_tadm(self, config, mock_async_instrument_class):
        instrument = mock_async_instrument_class.return_value
        with VantageClient(config) as client:
            client.dispense_on_the_fly_magpip(
                channels=[1],
                labware_name="plate 1",
                volumes=80.0,
                labware_surface_distance=3.0,
                adc=True,
                tadm=TadmSettings(enabled=TadmMode.RECORDING),
            )

        params = instrument.venus.send_command.await_args.kwargs["parameters"]
        assert params["ADC"] is True
        assert params["TADM"] == {"enabled": 1, "recording": 2}


class TestMagPipAxisStatus:
    def test_action_names(self, config, mock_async_instrument_class):
        instrument = mock_async_instrument_class.return_value
        instrument.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success", return_code=0, return_parameters={"channelStatus": []}
            )
        )
        names = []
        with VantageClient(config) as client:
            client.move_axis_magpip([1], z=100.0)
            names.append(instrument.venus.send_command.await_args.kwargs["action_name"])
            client.get_status_magpip()
            names.append(instrument.venus.send_command.await_args.kwargs["action_name"])

        assert names == ["channels.MagPip.moveAxis", "channels.MagPip.getStatus"]

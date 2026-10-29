"""Unit tests for LiquidClassCommandsMixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.models import (
    CommandResponse,
    GetLiquidClassResponse,
    LiquidClassDefinition,
    LiquidClassesResponse,
    LiquidDevicesResponse,
    LiquidNamesResponse,
    TipTypesResponse,
)
from hamilton_venus.star_client import StarClient


@pytest.fixture
def config():
    return SdkConfig(base_url="http://test:42400")


@pytest.fixture
def mock_async_star_class():
    with patch("hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient") as cls:
        star = MagicMock()
        star.start = AsyncMock()
        star.stop = AsyncMock()

        venus_mock = MagicMock()
        venus_mock.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={},
            ),
        )
        star.venus = venus_mock

        cls.return_value = star
        yield cls


class TestLiquidClassCommands:
    def test_pull_liquid_classes_single(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.pull_liquid_classes(names=["Water"])

        assert result.success is True
        star.venus.send_command.assert_awaited_once()
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["category"] == "System"
        assert call_args.kwargs["action_name"] == "liquidClass.pullLiquidClasses"
        assert call_args.kwargs["parameters"]["names"] == ["Water"]

    def test_pull_liquid_classes_multiple(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.pull_liquid_classes(names=["Water", "Serum", "Viscous"])

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["parameters"]["names"] == ["Water", "Serum", "Viscous"]

    def test_push_liquid_classes_single(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.push_liquid_classes(names=["Water"])

        assert result.success is True
        star.venus.send_command.assert_awaited_once()
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["category"] == "System"
        assert call_args.kwargs["action_name"] == "liquidClass.pushLiquidClasses"
        assert call_args.kwargs["parameters"]["names"] == ["Water"]

    def test_push_liquid_classes_multiple(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.push_liquid_classes(names=["Water", "Serum", "Viscous"])

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["parameters"]["names"] == ["Water", "Serum", "Viscous"]

    def test_get_liquid_devices(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command.return_value = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={
                "devices": [
                    {"deviceName": "Channel_1mL", "deviceId": 0},
                    {"deviceName": "MPH96", "deviceId": 1},
                ]
            },
        )

        with StarClient(config) as client:
            result = client.get_liquid_devices()

        assert isinstance(result, LiquidDevicesResponse)
        assert result.return_parameters.devices[0].device_name == "Channel_1mL"
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="liquidClass.getLiquidDevices",
        )

    def test_get_liquid_devices_response_model(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"devices": [{"deviceName": "Device1", "deviceId": 2}]},
            )
        )

        with StarClient(config) as client:
            result = client.get_liquid_devices()

        assert result.success is True
        assert result.return_parameters.devices[0].device_id == 2

    def test_get_liquid_names(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command.return_value = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"liquidNames": ["Water", "Serum", "Viscous"]},
        )

        with StarClient(config) as client:
            result = client.get_liquid_names()

        assert isinstance(result, LiquidNamesResponse)
        assert result.return_parameters.liquid_names == ["Water", "Serum", "Viscous"]
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="liquidClass.getLiquidNames",
        )

    def test_get_liquid_names_response_model(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"liquidNames": ["Liquid1", "Liquid2"]},
            ),
        )

        with StarClient(config) as client:
            result = client.get_liquid_names()

        assert result.success is True
        assert result.return_parameters.liquid_names == ["Liquid1", "Liquid2"]

    def test_get_liquid_classes_defaults(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command.return_value = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={
                "count": 2,
                "liquidClassNames": ["Water_DispenseJet_Empty", "Water_DispenseSurface_Empty"],
            },
        )

        with StarClient(config) as client:
            result = client.get_liquid_classes()

        assert isinstance(result, LiquidClassesResponse)
        assert result.return_parameters.count == 2
        assert result.return_parameters.liquid_class_names == ["Water_DispenseJet_Empty", "Water_DispenseSurface_Empty"]
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="liquidClass.getLiquidClasses",
            parameters={
                "tipType": -1,
                "device": -1,
                "dispenseMode": -1,
                "isOriginal": -1,
                "hasTadmEnabled": -1,
            },
        )

    def test_get_liquid_classes_with_filters(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        with StarClient(config) as client:
            result = client.get_liquid_classes(
                tip_type=0,
                device=1,
                dispense_mode=3,
                is_original=1,
                has_tadm_enabled=0,
            )

        assert result.success is True
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="liquidClass.getLiquidClasses",
            parameters={
                "tipType": 0,
                "device": 1,
                "dispenseMode": 3,
                "isOriginal": 1,
                "hasTadmEnabled": 0,
            },
        )

    def test_get_tip_types(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command.return_value = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={
                "tipTypes": {
                    "0": {"tipTypeName": "1000uL"},
                    "1": {"tipTypeName": "200uL"},
                }
            },
        )

        with StarClient(config) as client:
            result = client.get_tip_types()

        assert isinstance(result, TipTypesResponse)
        assert result.return_parameters.tip_types["0"]["tipTypeName"] == "1000uL"
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="liquidClass.getTipTypes",
        )

    def test_get_tip_types_response_model(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command = AsyncMock(
            return_value=CommandResponse(
                return_status="Success",
                return_code=0,
                return_parameters={"tipTypes": {"2": {"tipTypeName": "Type2"}}},
            )
        )

        with StarClient(config) as client:
            result = client.get_tip_types()

        assert result.success is True
        assert result.return_parameters.tip_types["2"]["tipTypeName"] == "Type2"

    def test_get_liquid_class(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command.return_value = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={
                "definition": {
                    "id": "StandardVolume_Water_DispenseJet_Empty",
                    "isUserDefined": True,
                    "version": "1.1",
                    "tadmEnabled": False,
                    "validated": False,
                    "notes": "",
                    "appliesTo": {
                        "instrument": "STAR",
                        "liquid": "Water",
                        "volumeRange": {"min": 0, "max": 1000},
                        "tipType": "300ul Standard Volume Tip",
                        "dispenseMode": "Jet Empty Tip",
                        "pipettingDevice": "Channel",
                    },
                    "pipettingProperties": {
                        "aspirate": {
                            "flowRate": 100,
                            "mixFlowRate": 100,
                            "airTransportVolume": 5,
                            "blowOutVolume": 30,
                            "swapSpeed": 2,
                            "settlingTime": 1,
                            "overAspirateVolume": 0,
                            "clotRetractHeight": 0,
                        },
                        "dispense": {
                            "flowRate": 180,
                            "mixFlowRate": 1,
                            "airTransportVolume": 5,
                            "blowOutVolume": 30,
                            "swapSpeed": 1,
                            "settlingTime": 0,
                            "stopFlowRate": 100,
                            "stopBackVolume": 0,
                        },
                        "detection": {"lld": {"pressureSensitivity": 4, "lldMaxHeightDifference": 0}},
                        "correction": [
                            {"targetedVolume": 0, "correctedVolume": 0},
                            {"targetedVolume": 100, "correctedVolume": 100},
                        ],
                        "tadmBands": [],
                    },
                    "_internal": {
                        "designHistory": "AQAAAAA=",
                        "tipTypeId": 0,
                        "dispenseMode": 3,
                        "liquidDeviceIds": [1],
                    },
                }
            },
        )

        with StarClient(config) as client:
            result = client.get_liquid_class(name="StandardVolume_Water_DispenseJet_Empty")

        assert isinstance(result, GetLiquidClassResponse)
        assert result.success is True
        defn = result.return_parameters.definition
        assert defn.id == "StandardVolume_Water_DispenseJet_Empty"
        assert defn.applies_to.liquid == "Water"
        assert defn.internal.tip_type_id == 0
        assert defn.internal.dispense_mode == 3
        assert defn.pipetting_properties.aspirate.flow_rate == 100
        assert defn.pipetting_properties.dispense.flow_rate == 180
        assert defn.internal.liquid_device_ids == [1]
        assert len(defn.pipetting_properties.correction) == 2
        star.venus.send_command.assert_awaited_once_with(
            category="System",
            action_name="liquidClass.getLiquidClass",
            parameters={"name": "StandardVolume_Water_DispenseJet_Empty"},
        )

    def test_update_liquid_class(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value
        star.venus.send_command.return_value = CommandResponse(
            return_status="Success",
            return_code=0,
            return_parameters={"message": '"StandardVolume_Water_DispenseJet_Empty" was updated'},
        )

        definition = LiquidClassDefinition(
            className="StandardVolume_Water_DispenseJet_Empty",
            liquidName="Water",
            version="1.1",
            tipTypeId=0,
            tipTypeName="300ul Standard Volume Tip",
            dispenseMode=3,
            dispenseModeName="Jet Empty Tip",
            isUserDefined=True,
            notes="",
            tadmEnabled=False,
            validationState=0,
            pressureLldSensitivity=4,
            lldMaxHeightDifference=0,
            liquidDeviceIds=[1],
            aFlowRate=120,
            aMixFlowRate=100,
            aAirTransportVol=5,
            aBlowoutVol=30,
            aSwapSpeed=2,
            aSettlingTime=1,
            aOverAspirateVol=0,
            aClotRetractHeight=0,
            dFlowRate=180,
            dMixFlowRate=1,
            dAirTransportVol=5,
            dBlowoutVol=30,
            dSwapSpeed=1,
            dSettlingTime=0,
            dStopFlowRate=100,
            dStopBackVol=0,
            correctionCurve=[],
            tadmBands=[],
            designHistoryBase64="AQAAAAA=",
            checkSum=-1515716501,
        )

        with StarClient(config) as client:
            result = client.update_liquid_class(definition=definition)

        assert result.success is True
        call_args = star.venus.send_command.call_args
        assert call_args.kwargs["category"] == "System"
        assert call_args.kwargs["action_name"] == "liquidClass.updateLiquidClass"
        sent_defn = call_args.kwargs["parameters"]["definition"]
        assert sent_defn["className"] == "StandardVolume_Water_DispenseJet_Empty"
        assert sent_defn["aFlowRate"] == 120

    def test_update_liquid_class_sends_full_definition(self, config, mock_async_star_class):
        star = mock_async_star_class.return_value

        definition = LiquidClassDefinition(
            className="HighVolume_DMSO_DispenseJet_Empty",
            liquidName="DMSO",
            version="1.0",
            tipTypeId=1,
            tipTypeName="1000ul High Volume Tip",
            dispenseMode=0,
            dispenseModeName="Jet Empty Tip",
            isUserDefined=False,
            notes="test notes",
            tadmEnabled=True,
            validationState=1,
            pressureLldSensitivity=2,
            lldMaxHeightDifference=1.5,
            liquidDeviceIds=[0, 1],
            aFlowRate=50,
            aMixFlowRate=50,
            aAirTransportVol=10,
            aBlowoutVol=20,
            aSwapSpeed=1,
            aSettlingTime=2,
            aOverAspirateVol=5,
            aClotRetractHeight=0,
            dFlowRate=100,
            dMixFlowRate=2,
            dAirTransportVol=10,
            dBlowoutVol=20,
            dSwapSpeed=2,
            dSettlingTime=1,
            dStopFlowRate=50,
            dStopBackVol=5,
            correctionCurve=[],
            tadmBands=[],
            designHistoryBase64="AQAAAAA=",
            checkSum=0,
        )

        with StarClient(config) as client:
            result = client.update_liquid_class(definition=definition)

        assert result.success is True
        sent_defn = star.venus.send_command.call_args.kwargs["parameters"]["definition"]
        assert sent_defn["liquidName"] == "DMSO"
        assert sent_defn["tipTypeId"] == 1
        assert sent_defn["tadmEnabled"] is True
        assert sent_defn["liquidDeviceIds"] == [0, 1]

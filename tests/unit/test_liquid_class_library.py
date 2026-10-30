"""Choosing liquid classes from what they apply to (hamilton_venus.liquid_class_library),
find_liquid_classes, and the device check before pipetting commands."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient
from hamilton_venus.exceptions import LiquidClassMismatchError
from hamilton_venus.liquid_class_library import (
    LiquidClassLibrary,
    device_for_action,
    fitted_devices,
    normalize_device,
    normalize_dispense_mode,
    parse_tip_types,
    rank_candidates,
)
from hamilton_venus.mixins.liquid_class_commands import LiquidClassCommandsMixin
from hamilton_venus.models import ConfigurationResponse, TipTypesResponse
from hamilton_venus.models.enums import DispenseMode

# Trimmed from a real get_tip_types reply.
TIP_TYPES = {
    "0": {"Max Liquid Volume": 300, "Max Tip Volume": 400, "Tip Length": 59.9, "Stop Disk Immersion Depth": 8,
          "Filter": False, "Conductivity": True,
          "Liquid Device List": ["1mL Channels", "96 head", "96 wash station", "1mL X1 Channels"],
          "Tip View Name": "300ul Standard Volume Tip (Ham org. name)", "Tip Class": "tip"},
    "4": {"Max Liquid Volume": 1000, "Max Tip Volume": 1250, "Tip Length": 95.1, "Filter": False,
          "Liquid Device List": ["1mL Channels", "96 head", "96 wash station", "1mL X1 Channels"],
          "Tip View Name": "1000ul High Volume Tip (Ham org. name)", "Tip Class": "tip"},
    "25": {"Max Liquid Volume": 5000, "Max Tip Volume": 5420, "Tip Length": 118, "Filter": False,
           "Liquid Device List": ["5mL channels", "5mL X5 Channels"], "Tip View Name": "5ml Tip (Ham org. name)",
           "Tip Class": "tip"},
}


def _write(root: Path, instrument: str, rel: str, name: str, **applies: Any) -> None:
    path = root / instrument / rel / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "id": name, "validated": True,
        "appliesTo": {"instrument": "ML_STAR", "liquid": applies.get("liquid", "Water"),
                      "volumeRange": {"min": 0, "max": applies.get("vmax", 300)},
                      "tipType": applies.get("tip", "tip_300ul"), "dispenseMode": applies.get("mode", "jet_empty"),
                      "pipettingDevice": applies.get("device", "channels_1000ul")},
        "_internal": {"tipTypeId": applies.get("tip_id", 0)},
    }
    path.write_text(json.dumps(body), encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "Liquid Class"
    tip300 = "System/Channels_1000ul/Tip_300ul"
    _write(root, "VANTAGE", f"{tip300}/Water/Jet_Empty", "StandardVolume_Water_DispenseJet_Empty")
    _write(root, "VANTAGE", f"{tip300}/Ethanol/Jet_Empty", "StandardVolume_EtOH_DispenseJet_Empty",
           liquid="Ethanol")
    _write(root, "VANTAGE", f"{tip300}/Water/Surface_Empty", "StandardVolume_Water_DispenseSurface_Empty",
           mode="surface_empty")
    _write(root, "VANTAGE", "User/Channels_1000ul/Tip_300ul/Water/Jet_Empty", "MyWater")
    _write(root, "VANTAGE", "System/Channels_1000ul/Tip_1000ul/Water/Jet_Empty", "HighVolume_Water_DispenseJet_Empty",
           tip="tip_1000ul", tip_id=4, vmax=1000)
    _write(root, "VANTAGE", "System/Channels_Magpip/Tip_300ul/Water/Jet_Empty", "MagPip_Water_JetEmpty",
           device="channels_magpip")
    _write(root, "VANTAGE", "System/Head_96/Tip_300ul/Water/Jet_Empty", "Core96_Water_JetEmpty", device="head_96")
    _write(root, "STAR", "System/Channels_1000ul/Tip_300ul/Water/Jet_Empty", "StarOnly_Water_JetEmpty")
    return root


def _config(**arm: Any) -> ConfigurationResponse:
    return ConfigurationResponse.model_validate({"returnStatus": "Success", "returnParameters": {"LeftArm": arm}})


class TestVocabulary:
    def test_tip_types_parse_with_their_devices(self):
        tips = parse_tip_types(TIP_TYPES)
        assert tips[0].max_liquid_volume == 300 and tips[0].tip_length == 59.9
        # The collar (8 mm up to the stop disk) sits on the channel: 51.9 mm reaches below it.
        assert tips[0].length_below_channel == 51.9
        assert tips[0].model_dump()["length_below_channel"] == 51.9
        assert tips[4].length_below_channel == 95.1  # no stop disk depth given: whole length
        assert tips[0].usable_on("channels_1000ul") and tips[0].usable_on("head_96")
        assert not tips[0].usable_on("channels_magpip")
        assert tips[25].devices() == ["channels_5ml"]
        assert tips[0].name == "300ul Standard Volume Tip"  # "(Ham org. name)" is dropped

    def test_fitted_devices_come_from_the_configuration(self):
        devices = fitted_devices(_config(channels1mL={"total": 8}, MPH96={"total": 96}))
        assert devices == {"channels_1000ul", "head_96"}
        assert "channels_magpip" not in devices

    def test_names_and_actions(self):
        assert normalize_device("1mL") == "channels_1000ul"
        assert normalize_device("MagPip") == "channels_magpip"
        assert normalize_device("MPH96") == "head_96"
        assert normalize_dispense_mode(DispenseMode.JET_EMPTY_TIP) == "jet_empty"
        assert normalize_dispense_mode("Surface Part") == "surface_part"
        assert device_for_action("channels.1mL.aspirate") == "channels_1000ul"
        assert device_for_action("channels.MagPip.dispense") == "channels_magpip"
        assert device_for_action("mph96.aspirate") == "head_96"
        assert device_for_action("status.getStatus") is None
        with pytest.raises(ValueError):
            normalize_device("8-channel thing")


class TestRanking:
    def test_only_this_device_tip_and_mode(self, root):
        lib = LiquidClassLibrary(root, "VANTAGE")
        found, _ = rank_candidates(lib, liquid="Water", device="channels_1000ul", tip_type_id=0,
                                   dispense_mode="jet_empty", volume=100)
        names = [c.name for c in found]
        assert names[0] == "StandardVolume_Water_DispenseJet_Empty"  # exact liquid, original first
        assert "MyWater" in names
        assert "MagPip_Water_JetEmpty" not in names and "Core96_Water_JetEmpty" not in names
        assert "HighVolume_Water_DispenseJet_Empty" not in names  # another tip type
        assert "StandardVolume_Water_DispenseSurface_Empty" not in names  # another mode

    def test_a_class_is_judged_by_its_definition_not_its_name(self, root):
        # Real library: the 96 CORE head classes carry "1000ul" in their names (the head), but
        # this one is for the 300 uL tip.
        name = "StandardVolume_96COREHead1000ul_Water_DispenseJet_Empty"
        _write(root, "STAR", "System/Head_96/Tip_300ul/Water/Jet_Empty", name, device="head_96")
        path = root / "STAR" / "System/Head_96/Tip_300ul/Water/Jet_Empty" / f"{name}.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        body["pipettingProperties"] = {"aspirate": {"flowRate": 100, "blowOutVolume": 30},
                                       "dispense": {"flowRate": 180, "stopBackVolume": 0}}
        path.write_text(json.dumps(body), encoding="utf-8")
        lib = LiquidClassLibrary(root, "STAR")

        found, notes = rank_candidates(lib, liquid="Buffer", device="head_96", tip_type_id=0,
                                       dispense_mode="jet_empty", volume=250)
        assert [c.name for c in found] == [name]
        top = found[0]
        assert top.liquid_match == "fallback"  # about the liquid ("Buffer" vs Water), not the tip
        assert top.summary == "96-channel head (MPH96), tip_300ul tip, 0-300 µL, Water, jet_empty"
        assert top.aspirate == {"flowRate": 100.0, "blowOutVolume": 30.0}
        assert top.dispense["flowRate"] == 180.0
        assert any("not by its name" in n for n in notes)
        # For the 1000 uL tip the same name is not a candidate.
        other, _ = rank_candidates(lib, liquid="Water", device="head_96", tip_type_id=4,
                                   dispense_mode="jet_empty", volume=250)
        assert other == []

    def test_closest_liquid_when_none_is_exact(self, root):
        lib = LiquidClassLibrary(root, "VANTAGE")
        found, notes = rank_candidates(lib, liquid="70% ethanol", device="channels_1000ul", tip_type_id=0,
                                       dispense_mode="jet_empty", volume=50)
        assert found[0].name == "StandardVolume_EtOH_DispenseJet_Empty"
        assert found[0].liquid_match == "close"
        assert notes


class _Client(LiquidClassCommandsMixin):
    def __init__(self, root: Path, *, config: ConfigurationResponse | None, pool_tip: int = 0) -> None:
        self._library = LiquidClassLibrary(root, "VANTAGE")
        self._config = config
        self._pool_tip = pool_tip

    @property
    def _connected_instrument(self):
        return SimpleNamespace(liquid_class_library=self._library)

    def get_tip_types(self):
        return TipTypesResponse.model_validate({"returnStatus": "Success", "returnParameters": {"tipTypes": TIP_TYPES}})

    def tip_pool_get_tip_counter(self, tip_pool):
        return SimpleNamespace(return_parameters=SimpleNamespace(tip_type=self._pool_tip))

    def instrument_get_configuration(self):
        if self._config is None:
            raise RuntimeError("not connected")
        return self._config


class TestFindLiquidClasses:
    def test_uses_the_pools_tip_and_a_fitted_device(self, root):
        client = _Client(root, config=_config(channels1mL={"total": 8}))
        result = client.find_liquid_classes("water", dispense_mode="jet_empty", volume=100, tip_pool="Tips300")
        assert result.device == "channels_1000ul"
        assert result.tip.max_liquid_volume == 300
        assert result.candidates[0].name == "StandardVolume_Water_DispenseJet_Empty"

    def test_a_device_that_is_not_fitted_is_refused(self, root):
        client = _Client(root, config=_config(channels1mL={"total": 8}))
        with pytest.raises(ValueError, match="no MagPip channels"):
            client.find_liquid_classes("water", tip_type=0, device="MagPip")

    def test_unregistered_tip_unusable_tip_and_too_much_volume(self, root):
        client = _Client(root, config=_config(channels1mL={"total": 8}, channels5mL={"total": 4}))
        with pytest.raises(ValueError, match="not registered"):
            client.find_liquid_classes("water", tip_type=99)
        with pytest.raises(ValueError, match="cannot be used on the 1 mL channels"):
            client.find_liquid_classes("water", tip_type=25, device="1mL")
        with pytest.raises(ValueError, match="more than"):
            client.find_liquid_classes("water", tip_type=0, volume=500)

    def test_without_a_connection_the_device_is_not_checked_but_noted(self, root):
        client = _Client(root, config=None)
        result = client.find_liquid_classes("water", tip_type=0, dispense_mode="jet_empty")
        assert result.device == "channels_1000ul"
        assert any("not checked" in n for n in result.notes)


class TestDeviceGuard:
    def _client(self, root: Path, instrument: str = "VANTAGE") -> _AsyncInstrumentClient:
        client = object.__new__(_AsyncInstrumentClient)
        client._liquid_class_library = LiquidClassLibrary(root, instrument)
        client._other_instrument_library = LiquidClassLibrary(root, "STAR" if instrument == "VANTAGE" else "VANTAGE")
        return client

    def test_a_magpip_class_on_the_1ml_channels_is_refused(self, root):
        with pytest.raises(LiquidClassMismatchError, match="MagPip channels"):
            self._client(root)._check_liquid_class_devices("channels.1mL.aspirate", ["MagPip_Water_JetEmpty"])

    def test_matching_and_unknown_classes_pass(self, root):
        client = self._client(root)
        client._check_liquid_class_devices(
            "channels.1mL.aspirate", ["StandardVolume_Water_DispenseJet_Empty", "NotInLibrary"])
        client._check_liquid_class_devices("mph96.dispense", ["Core96_Water_JetEmpty"])
        client._check_liquid_class_devices("liquidClass.pushLiquidClasses", ["MagPip_Water_JetEmpty"])

    def test_a_class_from_the_other_instrument_is_refused(self, root):
        with pytest.raises(LiquidClassMismatchError, match="STAR class"):
            self._client(root)._check_liquid_class_devices("channels.1mL.aspirate", ["StarOnly_Water_JetEmpty"])

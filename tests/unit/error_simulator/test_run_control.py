"""Unit tests for instrument / config-path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from hamilton_venus.error_simulator.exceptions import InstrumentNotResolved
from hamilton_venus.error_simulator.run_control import resolve

_CFG_DIR = r"C:\Program Files (x86)\Hamilton\Config"


def _resolve(platform: str, *, inst_cfg_file: str | None, sim: bool = True):
    return resolve(
        instrument_data=[{"defaultName": "whatever", "platform": platform}],
        config_dir=_CFG_DIR,
        is_simulating=sim,
        inst_cfg_file=inst_cfg_file,
    )


def test_star_variants_all_map_to_ml_star_simulator_cfg() -> None:
    # STARlet / STAR / FlexSTAR all report platform ML_STAR and InstCfgFile ML_STAR.cfg
    info = _resolve("ML_STAR", inst_cfg_file="ML_STAR.cfg")
    assert info.instrument == "STAR"
    assert info.instrument_class == "ML_STAR"
    assert info.config_path == Path(_CFG_DIR) / "ML_STAR_Simulator.cfg"


def test_inst_cfg_file_drives_the_name() -> None:
    info = _resolve("ML_STAR", inst_cfg_file="Custom_Rig.cfg")
    assert info.config_path.name == "Custom_Rig_Simulator.cfg"


def test_fallback_when_registry_lookup_unavailable() -> None:
    assert _resolve("ML_STAR", inst_cfg_file=None).config_path.name == "ML_STAR_Simulator.cfg"
    assert _resolve("Vantage", inst_cfg_file=None).config_path.name == "HxVantage_Simulator.cfg"


def test_vantage_platform_is_vantage() -> None:
    info = _resolve("Vantage", inst_cfg_file="HxVantage.cfg")
    assert info.instrument == "VANTAGE"
    assert info.config_path.name == "HxVantage_Simulator.cfg"


def test_missing_platform_raises() -> None:
    with pytest.raises(InstrumentNotResolved, match="missing 'platform'"):
        resolve(instrument_data=[{"defaultName": "x"}], config_dir=_CFG_DIR, is_simulating=True)


def test_empty_instrument_data_raises() -> None:
    with pytest.raises(InstrumentNotResolved, match="no instruments registered"):
        resolve(instrument_data=[], config_dir=_CFG_DIR, is_simulating=True)


def test_simulation_flag_passthrough() -> None:
    assert _resolve("ML_STAR", inst_cfg_file="ML_STAR.cfg", sim=False).is_simulating is False


def test_instrument_override_beats_platform() -> None:
    # A Vantage behind the STAR translator registers with platform ML_STAR; its
    # client passes instrument="VANTAGE" so the Vantage tables are used.
    info = resolve(
        instrument_data=[{"defaultName": "whatever", "platform": "ML_STAR"}],
        config_dir=_CFG_DIR,
        is_simulating=True,
        inst_cfg_file="VStar.cfg",
        instrument="VANTAGE",
    )
    assert info.instrument == "VANTAGE"
    assert info.config_path.name == "VStar_Simulator.cfg"

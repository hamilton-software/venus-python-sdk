"""End-to-end tests for the ErrorSimulator facade with a fake config writer."""

from __future__ import annotations

from pathlib import Path

import pytest

from hamilton_venus.error_simulator import ErrorSimulator, Module, SimulationModeRequired
from hamilton_venus.error_simulator._generated_steps import StarStep
from hamilton_venus.error_simulator.run_control import RunControlInfo


class FakeConfig:
    def __init__(self) -> None:
        self.writes: list[dict[str, str]] = []

    def apply(self, values: dict[str, str]) -> None:
        self.writes.append(dict(values))


def _sim(instrument: str = "STAR", *, simulating: bool = True) -> tuple[ErrorSimulator, FakeConfig]:
    info = RunControlInfo(
        instrument=instrument,
        instrument_class="ML_STAR" if instrument == "STAR" else "Vantage",
        config_path=Path("X_Simulator.cfg"),
        is_simulating=simulating,
    )
    cfg = FakeConfig()
    return ErrorSimulator(info, config=cfg), cfg


def test_set_error_channel_module_writes_expected_cfg() -> None:
    sim, cfg = _sim("STAR")
    sim.set_error(Module.CHANNELS_1ML, StarStep.TIP_PICK_UP, "No tip picked up", channels=[1])

    assert len(cfg.writes) == 1
    written = cfg.writes[0]
    assert "C0TP" in written
    assert written["C0TP"].startswith("er99/00 P1")
    assert written["updateKeyValue"] == "C0TP"
    assert written["updateParamValue"] == "er00/00"
    assert written["reload"] == "1"


def test_channel_module_without_channels_applies_to_all_channels() -> None:
    sim, cfg = _sim("STAR")
    sim.set_error(Module.CHANNELS_1ML, StarStep.TIP_PICK_UP, "No tip picked up")
    written = cfg.writes[0]["C0TP"]
    # one "P<channel><code>" segment per default channel (1..8)
    assert written.startswith("er99/00 P1")
    assert written.count("P") == 8


def test_channel_module_with_empty_channels_list_applies_to_all_channels() -> None:
    sim, cfg = _sim("STAR")
    sim.set_error(Module.CHANNELS_1ML, StarStep.TIP_PICK_UP, "No tip picked up", channels=[])
    assert cfg.writes[0]["C0TP"].count("P") == 8


def test_malformed_micro_syntax_mix_still_raises() -> None:
    sim, _ = _sim("STAR")
    with pytest.raises(Exception, match="per-channel"):
        sim.set_error(Module.CHANNELS_1ML, StarStep.TIP_PICK_UP, "1.No tip picked up;No tip picked up")


def test_channel_micro_syntax() -> None:
    sim, cfg = _sim("STAR")
    sim.set_error(Module.CHANNELS_1ML, StarStep.TIP_PICK_UP, "1.No tip picked up;2.No tip picked up")
    written = cfg.writes[0]["C0TP"]
    assert written.count("P") == 2  # two channel segments


def test_set_error_by_code_is_verbatim() -> None:
    sim, cfg = _sim("STAR")
    sim.set_error_by_code("C0AS", "99", "recovery")
    written = cfg.writes[0]
    # the given code is written exactly as-is...
    assert written["C0AS"] == "99"
    assert written["updateKeyValue"] == "C0AS"
    assert written["updateParamValue"] == "recovery"
    assert written["reload"] == "1"
    # ...but every other known FW command is reset to "no error" in the same write
    assert written["C0TP"] == "er00/00"


def test_set_error_clears_the_previous_error_in_the_same_write() -> None:
    sim, cfg = _sim("STAR")
    sim.set_error(Module.CHANNELS_1ML, StarStep.TIP_PICK_UP, "No tip picked up", channels=[1])
    sim.set_error(Module.CHANNELS_1ML, StarStep.ASPIRATE, "No tip picked up", channels=[1])

    second = cfg.writes[1]
    # the newly targeted command carries the error...
    assert second[second["updateKeyValue"]].startswith("er99/00 ")
    # ...and the previously targeted command is back to "no error"
    assert second["C0TP"] == "er00/00"


def test_reset_writes_no_error_for_every_fw_command() -> None:
    sim, cfg = _sim("STAR")
    sim.reset()
    written = cfg.writes[0]
    assert written["updateKeyValue"] == "0"
    assert written["updateParamValue"] == "0"
    # a handful of known STAR firmware commands set to their no-error reply
    assert written["C0AS"] == "er00/00"
    assert written["C0TP"] == "er00/00"


def test_simulation_mode_guard() -> None:
    sim, _ = _sim("STAR", simulating=False)
    with pytest.raises(SimulationModeRequired):
        sim.set_error(Module.CHANNELS_1ML, StarStep.ASPIRATE, "x", channels=[1])
    with pytest.raises(SimulationModeRequired):
        sim.reset()
    with pytest.raises(SimulationModeRequired):
        sim.set_error_by_code("C0AS", "99")


def test_vantage_channel_reply_shape() -> None:
    sim, cfg = _sim("VANTAGE")
    rows = sim.kb.error_rows("VANTAGE", sim.kb.resolve_module("1mL"))
    desc = next(r.description for r in rows if r.description.lower().startswith("main: tip not loaded"))
    sim.set_error(Module.CHANNELS_1ML, "Aspirate", desc, channels=[1])
    written = cfg.writes[0]
    value = written[written["updateKeyValue"]]
    assert value.startswith('er99es"P1')
    assert value.endswith('"')

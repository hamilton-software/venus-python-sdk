"""Unit tests for the Error Simulator package."""

from __future__ import annotations

from pathlib import Path

import pytest

from hamilton_venus.error_simulator import ErrorSimulator, Module, SimulationModeRequired
from hamilton_venus.error_simulator.exceptions import ErrorSimulatorError
from hamilton_venus.error_simulator.knowledge_base import KnowledgeBase
from hamilton_venus.error_simulator.matching import match_error, match_firmware
from hamilton_venus.error_simulator.reply_builder import build_channel_reply, build_single_reply
from hamilton_venus.error_simulator.run_control import RunControlInfo, resolve


class _FakeConfig:
    def __init__(self) -> None:
        self.applied_values: list[dict[str, str]] = []

    def apply(self, values: dict[str, str]) -> None:
        self.applied_values.append(values)


def _run_info(*, simulating: bool = True) -> RunControlInfo:
    return RunControlInfo(
        instrument="STAR",
        instrument_class="ML_STAR",
        config_path=Path("ML_STAR_Simulator.cfg"),
        is_simulating=simulating,
    )


def test_knowledge_base_resolves_modules_and_exact_rows() -> None:
    knowledge_base = KnowledgeBase.load()
    module = knowledge_base.resolve_module("1000ul")
    firmware_row = knowledge_base.firmware_rows("STAR", module)[0]
    error_row = knowledge_base.error_rows("STAR", module)[0]

    assert module.table == Module.CHANNELS_1ML
    assert match_firmware(firmware_row.description, [firmware_row], exact=True) == firmware_row.code
    assert match_error(error_row.description, [error_row], instrument="STAR", exact=True).endswith(error_row.code)


def test_resolve_uses_platform_and_fallback_simulator_config_name() -> None:
    run_info = resolve(
        instrument_data=[{"platform": "ML_STAR"}],
        config_dir=r"C:\VENUS\Config",
        is_simulating=True,
    )

    assert run_info.instrument == "STAR"
    normalized_path = str(run_info.config_path).replace("\\", "/")
    assert normalized_path == "C:/VENUS/Config/ML_STAR_Simulator.cfg"
    assert run_info.is_simulating


def test_reply_builders_cover_channel_and_vantage_single_replies() -> None:
    channel_reply = build_channel_reply(
        "STAR",
        "P",
        is_magpip=False,
        channel_codes=[(1, "01/02")],
        firmware_command="P1AS",
    )
    vantage_reply = build_single_reply(
        "VANTAGE",
        "M",
        error_code="04/05",
        firmware_command="M0AS",
    )

    assert channel_reply.value == "er99/00 P101/02"
    assert vantage_reply.value == 'er99es"M04/05"'


def test_simulator_writes_one_active_error_and_can_reset() -> None:
    knowledge_base = KnowledgeBase.load()
    module = knowledge_base.resolve_module(Module.CHANNELS_1ML)
    firmware_row = knowledge_base.firmware_rows("STAR", module)[0]
    error_row = knowledge_base.error_rows("STAR", module)[0]
    config = _FakeConfig()
    simulator = ErrorSimulator(_run_info(), knowledge_base=knowledge_base, config=config)  # type: ignore[arg-type]

    simulator.set_error(Module.CHANNELS_1ML, firmware_row.description, error_row.description, channels=[1])
    simulator.reset()

    injected, reset = config.applied_values
    assert injected["reload"] == "1"
    assert injected["updateKeyValue"] == firmware_row.code
    assert firmware_row.code in injected
    assert reset["updateKeyValue"] == "0"


def test_simulator_requires_simulation_mode() -> None:
    simulator = ErrorSimulator(_run_info(simulating=False), config=_FakeConfig())  # type: ignore[arg-type]

    with pytest.raises(SimulationModeRequired):
        simulator.reset()


def test_reset_clears_a_custom_raw_firmware_reply() -> None:
    config = _FakeConfig()
    simulator = ErrorSimulator(_run_info(), config=config)  # type: ignore[arg-type]

    simulator.set_error_by_code("C0RF", "er99/00")
    simulator.reset()

    assert config.applied_values[1]["C0RF"] == "er00/00"


def test_channel_error_argument_rejects_mixed_syntax() -> None:
    simulator = ErrorSimulator(_run_info(), config=_FakeConfig())  # type: ignore[arg-type]

    with pytest.raises(ErrorSimulatorError, match="give every item a channel"):
        simulator.set_error(Module.CHANNELS_1ML, "aspirate", "1.error;other error")

"""Unit tests for ErrorSimulatorCommandsMixin on StarClient / VantageClient."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamilton_venus.config import SdkConfig
from hamilton_venus.error_simulator import Module, SimulationModeRequired
from hamilton_venus.star_client import StarClient
from hamilton_venus.vantage_client import VantageClient


@pytest.fixture
def config() -> SdkConfig:
    return SdkConfig(base_url="http://test:42400")


@pytest.fixture
def writes() -> Iterator[list[dict[str, str]]]:
    captured: list[dict[str, str]] = []

    class _FakeConfig:
        def __init__(self, _path: object) -> None: ...

        def apply(self, values: dict[str, str]) -> None:
            captured.append(dict(values))

    with (
        patch("hamilton_venus.error_simulator.simulator.SimulatorConfig", _FakeConfig),
        patch("hamilton_venus.error_simulator.run_control._inst_cfg_file", return_value="ML_STAR.cfg"),
    ):
        yield captured


def _install(monkeypatch_target: str, *, simulating: bool, default_name: str, platform: str):
    """Return a patch context whose ``_AsyncInstrumentClient`` yields a mock with a
    stub ``venus`` exposing the three Vector calls the mixin makes."""
    ctx = patch(monkeypatch_target)
    async_cls = ctx.start()
    inst = MagicMock()
    inst.start = AsyncMock()
    inst.stop = AsyncMock()
    venus = MagicMock()
    venus.get_simulation = AsyncMock(return_value=simulating)
    venus.get_system_paths = AsyncMock(return_value={"Config": r"C:\Hamilton\Config"})
    venus.get_instrument_data = AsyncMock(
        return_value=[{"defaultName": default_name, "platform": platform}]
    )
    inst.venus = venus
    async_cls.return_value = inst
    return ctx


_TARGET = "hamilton_venus._internal._base_instrument_client._AsyncInstrumentClient"


@pytest.fixture
def star_env(simulating: bool = True):
    ctx = _install(_TARGET, simulating=True, default_name="Microlab STARlet", platform="ML_STAR")
    yield
    ctx.stop()


@pytest.fixture
def star_env_live():
    ctx = _install(_TARGET, simulating=False, default_name="Microlab STARlet", platform="ML_STAR")
    yield
    ctx.stop()


@pytest.fixture
def vantage_env():
    ctx = _install(_TARGET, simulating=True, default_name="Vantage", platform="Vantage")
    yield
    ctx.stop()


def test_star_simulate_error_writes_cfg(config, writes, star_env) -> None:
    with StarClient(config) as client:
        client.simulate_error(Module.CHANNELS_1ML, "Tip Pick Up", "No tip picked up", channels=[1])

    assert len(writes) == 1
    written = writes[0]
    assert written["updateKeyValue"] == "C0TP"
    assert written["reload"] == "1"
    assert written["C0TP"].startswith("er99/00 P1")


def test_vantage_simulate_error_by_code(config, writes, vantage_env) -> None:
    with VantageClient(config) as client:
        client.simulate_error_by_code("A1PM", "42", "retry")

    written = writes[0]
    assert written["A1PM"] == "42"
    assert written["updateKeyValue"] == "A1PM"
    assert written["updateParamValue"] == "retry"
    assert written["reload"] == "1"
    # other known FW commands are cleared in the same write (only one active error)
    assert any(k not in {"A1PM", "updateKeyValue", "updateParamValue", "reload"} for k in written)


def test_clear_simulated_errors(config, writes, star_env) -> None:
    with StarClient(config) as client:
        client.clear_simulated_errors()
    assert writes[0]["updateKeyValue"] == "0"


def test_guard_when_not_simulating(config, writes, star_env_live) -> None:
    with StarClient(config) as client, pytest.raises(SimulationModeRequired):
        client.simulate_error(Module.CHANNELS_1ML, "Aspirate", "x", channels=[1])


def test_list_helpers(config, writes, star_env) -> None:
    with StarClient(config) as client:
        assert "1mL" in client.list_simulatable_modules()
        assert "Aspirate" in client.list_simulatable_steps("1mL")
        assert client.list_simulatable_errors("1mL")

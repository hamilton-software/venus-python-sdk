"""Command-group tests for TiltModuleClient (drives the simulator through the real transport)."""

from __future__ import annotations

import inspect
import runpy
from pathlib import Path

import pytest

from hamilton_venus import TiltModuleClient, TiltModuleError
from hamilton_venus.models import (
    MessageResponse,
    TiltModuleConnectResponse,
    TiltModuleStatusResponse,
)
from hamilton_venus.standalone_devices import STANDALONE_DEVICES, find_standalone_device
from hamilton_venus.tilt_module import TiltModuleTransport, _SimTiltLink

REPO_ROOT = Path(__file__).resolve().parents[3]


def injected_client(**kwargs) -> tuple[TiltModuleClient, dict[int, _SimTiltLink]]:
    """A client whose systems each get their own simulator link (returned by system id)."""
    links: dict[int, _SimTiltLink] = {}

    def factory(system_id: int) -> TiltModuleTransport:
        links[system_id] = _SimTiltLink()
        return TiltModuleTransport(links[system_id], sleep=lambda _s: None)

    return TiltModuleClient(transport_factory=factory, **kwargs), links


class TestHslParity:
    """The commands mirror HSLMultiDaisyChainedTiltModuleAmbient one-to-one."""

    def test_connect_is_initialize_communication(self):
        client, links = injected_client()
        response = client.tilt_module_connect(1, 4)
        assert isinstance(response, TiltModuleConnectResponse)
        assert response.return_status == "Success"
        assert (response.return_parameters.system_id, response.return_parameters.com_port) == (1, "COM4")
        assert links[1].port == "COM4"

    def test_the_hsl_example_method_end_to_end(self):
        client, links = injected_client()
        client.tilt_module_connect(1, 3)
        client.tilt_module_initialize(1, "TM")
        client.tilt_module_move_to_position(1, "TM", 10)
        for angle in range(9, 4, -1):  # the HSL example steps down in 1-degree steps
            client.tilt_module_move_to_position(1, "TM", angle)
        client.tilt_module_terminate_module(1, "TM")
        client.tilt_module_terminate_communication(1)
        assert links[1].port is None
        sent = [r[0] for r in links[1].log]
        assert sent[:3] == ["TMEI", "TMSI", "TMRF"]  # InitializeTiltModuleAmbient: "EI,SI,RF"
        assert sent[3] == "TMGP10"
        assert sent.index("TMGP0") < sent.index("TMPO") == len(sent) - 1  # TerminateTiltModuleAmbient: "GP0,PO"

    def test_initialize_reports_the_firmware(self):
        client, _ = injected_client()
        client.tilt_module_connect(1, 3)
        message = client.tilt_module_initialize(1, "TM").return_parameters.message
        assert "Module TM initialized on system 1" in message and "Tilt module ambient simulation" in message

    def test_error_message_is_evaluate_error_message(self):
        client, _ = injected_client()
        assert client.tilt_module_error_message(0).return_parameters.message == "No error."
        assert client.tilt_module_error_message(3).return_parameters.message == "Drive not initialized!"
        assert client.tilt_module_error_message(-8).return_parameters.message.startswith("Reading from COM port failed")
        assert client.tilt_module_error_message(99).return_parameters.message == "Unknown error code!"


class TestCommands:
    def test_two_systems_on_two_ports(self):
        client, links = injected_client()
        client.tilt_module_connect(1, 3)
        client.tilt_module_connect(2, 4)
        client.tilt_module_initialize(1, "TM")
        client.tilt_module_initialize(2, "TM")  # same name on another system is fine
        client.tilt_module_move_to_position(2, "TM", 5)
        assert links[1].units["TM"].angle == 0 and links[2].units["TM"].angle == 5

    @pytest.mark.parametrize("angle", [-1, 11, 4.5])
    def test_bad_angle_is_a_tilt_module_error_with_code_6(self, angle):
        client, _ = injected_client()
        client.tilt_module_connect(1, 3)
        client.tilt_module_initialize(1, "TM")
        with pytest.raises(TiltModuleError) as info:
            client.tilt_module_move_to_position(1, "TM", angle)
        assert info.value.error_code == 6

    def test_status_reports_the_tracked_angle_and_live_firmware_state(self):
        client, _ = injected_client()
        client.tilt_module_connect(1, 3)
        client.tilt_module_initialize(1, "TM")
        client.tilt_module_move_to_position(1, "TM", 6)
        status = client.tilt_module_get_status(1, "TM")
        assert isinstance(status, TiltModuleStatusResponse)
        params = status.return_parameters
        assert (params.system_id, params.module_name, params.initialized, params.angle) == (1, "TM", True, 6)
        assert (params.busy, params.error_code, params.error_message) == (False, 0, "No error.")
        assert params.powered and params.query_error is None and params.firmware_version

    def test_status_works_on_the_real_transport_path_too(self):
        """Not simulation-only: it is RS/RE over the same transport the hardware uses."""
        client, links = injected_client()
        client.tilt_module_connect(1, 3)
        client.tilt_module_initialize(1, "TM")
        links[1].log.clear()
        client.tilt_module_get_status(1, "TM")
        assert {r[0][2:] for r in links[1].log} == {"RE", "RS"}

    def test_status_after_terminate_shows_powered_off_at_zero(self):
        client, _ = injected_client()
        client.tilt_module_connect(1, 3)
        client.tilt_module_initialize(1, "TM")
        client.tilt_module_move_to_position(1, "TM", 8)
        client.tilt_module_terminate_module(1, "TM")
        params = client.tilt_module_get_status(1, "TM").return_parameters
        assert (params.initialized, params.angle, params.powered) == (False, 0, False)

    def test_commands_before_connect_raise_error_minus_2(self):
        client, _ = injected_client()
        for call in (
            lambda: client.tilt_module_initialize(1, "TM"),
            lambda: client.tilt_module_move_to_position(1, "TM", 3),
            lambda: client.tilt_module_get_status(1, "TM"),
            lambda: client.tilt_module_terminate_communication(1),
        ):
            with pytest.raises(TiltModuleError) as info:
                call()
            assert info.value.error_code == -2

    def test_move_before_initialize_raises_error_minus_4(self):
        client, _ = injected_client()
        client.tilt_module_connect(1, 3)
        with pytest.raises(TiltModuleError) as info:
            client.tilt_module_move_to_position(1, "TM", 3)
        assert info.value.error_code == -4

    def test_closing_a_system_with_a_live_module_is_refused(self):
        client, links = injected_client()
        client.tilt_module_connect(1, 3)
        client.tilt_module_initialize(1, "TM")
        with pytest.raises(TiltModuleError, match="still initialised"):
            client.tilt_module_terminate_communication(1)
        assert links[1].port == "COM3"


class TestLifecycle:
    def test_close_on_unused_client_is_a_noop(self):
        client, links = injected_client()
        client.close()
        assert links == {}

    def test_context_manager_returns_plate_to_flat_and_powers_off(self):
        client, links = injected_client()
        with client:
            client.tilt_module_connect(1, 3)
            client.tilt_module_initialize(1, "TM")
            client.tilt_module_move_to_position(1, "TM", 9)
        assert links[1].units["TM"].angle == 0 and not links[1].units["TM"].powered and links[1].port is None

    def test_can_opt_out_of_returning_to_flat(self):
        client, links = injected_client(return_to_flat_on_close=False)
        with client:
            client.tilt_module_connect(1, 3)
            client.tilt_module_initialize(1, "TM")
            client.tilt_module_move_to_position(1, "TM", 9)
        assert links[1].units["TM"].angle == 9 and links[1].units["TM"].powered and links[1].port is None

    def test_simulate_true_needs_no_injection(self):
        with TiltModuleClient(simulate=True) as client:
            client.tilt_module_connect(1, 3)
            client.tilt_module_initialize(1, "AB")
            client.tilt_module_move_to_position(1, "AB", 3)
            assert client.tilt_module_get_status(1, "AB").return_parameters.angle == 3

    def test_fixed_sim_chain_rejects_unknown_module_names(self):
        with TiltModuleClient(simulate=True, sim_modules=("T1",)) as client:
            client.tilt_module_connect(1, 3)
            with pytest.raises(TiltModuleError, match="no reply"):
                client.tilt_module_initialize(1, "T2")


class TestSerialSettings:
    def test_defaults_are_the_documented_1200_8e1(self):
        client = TiltModuleClient(simulate=True)
        assert (client._tilt_module_baudrate, client._tilt_module_parity) == (1200, "E")

    def test_overrides_reach_the_serial_link(self, monkeypatch):
        import hamilton_venus.tilt_module as tm

        seen: dict[str, object] = {}

        class FakeLink(_SimTiltLink):
            def __init__(self, *, baudrate: int, parity: str) -> None:
                super().__init__()
                seen.update(baudrate=baudrate, parity=parity)

        monkeypatch.setattr(tm, "tilt_module_available", lambda: True)
        monkeypatch.setattr(tm, "_Win32SerialLink", FakeLink)
        with TiltModuleClient(baudrate=9600, parity="N") as client:
            client.tilt_module_connect(1, 3)
        assert seen == {"baudrate": 9600, "parity": "N"}


class TestDemoScript:
    def test_the_team_demo_runs_unchanged(self, capsys):
        """`example_scripts/tilt_module_demo.py` (written against the HSL's API) must keep working as-is."""
        script = REPO_ROOT / "example_scripts" / "tilt_module_demo.py"
        runpy.run_path(str(script), run_name="__main__")
        out = capsys.readouterr().out
        assert "module A1 now at 9 deg" in out and "module A1 now at 0 deg" in out
        assert "Demo complete." in out


class TestRegistration:
    def test_registered_with_its_own_prefix(self):
        spec = find_standalone_device("tilt_module_move_to_position")
        assert spec is not None and spec.client_cls is TiltModuleClient
        assert [s.prefix for s in STANDALONE_DEVICES].count("tilt_module_") == 1

    def test_prefix_does_not_swallow_other_tilt_commands(self):
        assert find_standalone_device("tilt_labware") is None

    def test_public_surface_is_exactly_the_hsl_plus_status(self):
        public = sorted(
            name
            for name, _ in inspect.getmembers(TiltModuleClient, predicate=inspect.isfunction)
            if not name.startswith("_") and name != "close"
        )
        assert public == sorted(
            [
                "tilt_module_connect",
                "tilt_module_initialize",
                "tilt_module_move_to_position",
                "tilt_module_terminate_module",
                "tilt_module_terminate_communication",
                "tilt_module_error_message",
                "tilt_module_get_status",
            ]
        )

    def test_parameter_names_match_the_hsl(self):
        sig = inspect.signature
        assert list(sig(TiltModuleClient.tilt_module_connect).parameters)[1:] == ["system_id", "com_port"]
        assert list(sig(TiltModuleClient.tilt_module_initialize).parameters)[1:] == ["system_id", "module_name"]
        assert list(sig(TiltModuleClient.tilt_module_move_to_position).parameters)[1:] == [
            "system_id",
            "module_name",
            "angle",
        ]

    def test_every_ack_is_a_message_response(self):
        client, _ = injected_client()
        client.tilt_module_connect(1, 3)
        for response in (
            client.tilt_module_initialize(1, "TM"),
            client.tilt_module_move_to_position(1, "TM", 2),
            client.tilt_module_terminate_module(1, "TM"),
            client.tilt_module_terminate_communication(1),
        ):
            assert isinstance(response, MessageResponse)

"""Unit tests for the shared liquid-availability helper (``_liquid_manager``).

Covers :class:`LiquidSourceTracker` reactive seeding, min-across-channels
measurement, in-order source switching, the operator reload prompt loop
(True/False/async/cancel), the strict no-callback ``ValueError``, and the
:func:`ensure_liquid_available` single-shot facade used by ``add_reagent``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hamilton_venus.compound_commands._helpers._liquid_manager import (
    LiquidSourceTracker,
    connected_channel_cap,
    connected_source_labware,
    ensure_liquid_available,
    expand_connected_sources,
    lld_enabled,
    measured_min_volume,
)
from hamilton_venus.exceptions import OperatorCancelledError
from hamilton_venus.models.command_types import ChannelAspirationResponse
from hamilton_venus.models.enums import CapacitiveLLD, PressureLLD
from hamilton_venus.models.liquid_handling_settings import AspirateSettings
from hamilton_venus.models.position import Position


def _pos(well: str, labware: str = "DiluentTrough") -> Position:
    return Position(labwareId=labware, wellId=well)


def _asp(*volumes: float) -> ChannelAspirationResponse:
    """Aspirate response carrying one channel per measured ``liquidVolume_uL``."""
    channels = [{"channel": i + 1, "liquidVolume_uL": v} for i, v in enumerate(volumes)]
    return ChannelAspirationResponse(
        return_status="Success",
        return_code=0,
        return_parameters={"channels": channels},
    )


def _client(callback=None) -> MagicMock:
    client = MagicMock()
    client.on_liquid_reload_prompt = callback
    return client


class TestMeasuredMinVolume:
    def test_min_across_channels(self):
        assert measured_min_volume(_asp(120.0, 90.0, 105.0)) == 90.0

    def test_none_when_no_channels(self):
        assert measured_min_volume(_asp()) is None


class TestLiquidSourceTrackerConstruction:
    def test_empty_sources_raises(self):
        with pytest.raises(ValueError, match="at least one source"):
            LiquidSourceTracker([])

    def test_initial_state(self):
        tracker = LiquidSourceTracker([_pos("A1"), _pos("A2")])
        assert tracker.active_source == _pos("A1")
        assert tracker.budget is None
        assert tracker.sources == [_pos("A1"), _pos("A2")]


class TestReactiveSeeding:
    def test_first_aspirate_not_pre_validated(self):
        # Estimate is None before the first measurement, so any required volume
        # returns the active source immediately (the first stroke cannot be
        # pre-validated).
        tracker = LiquidSourceTracker([_pos("A1")])
        source, budget = tracker.ensure_available(_client(), 500.0, command_name="serial_dilution")
        assert source == _pos("A1")
        assert budget is None

    def test_estimate_seeded_from_measurement(self):
        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.record_aspirate(_asp(300.0, 280.0))
        assert tracker.budget == 280.0

    def test_measured_value_overrides_estimate(self):
        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.record_aspirate(_asp(500.0))
        tracker.consume(100.0)
        assert tracker.budget == 400.0
        # A later measurement (short aspirate) overrides the running estimate.
        tracker.record_aspirate(_asp(50.0))
        assert tracker.budget == 50.0

    def test_consume_before_seeding_is_noop(self):
        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.consume(100.0)
        assert tracker.budget is None

    def test_consume_floors_at_zero(self):
        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.record_aspirate(_asp(30.0))
        tracker.consume(100.0)
        assert tracker.budget == 0.0


class TestSourceSwitching:
    def test_advances_when_active_source_short(self):
        tracker = LiquidSourceTracker([_pos("A1"), _pos("A2")])
        tracker.record_aspirate(_asp(40.0))  # A1 nearly empty
        source, budget = tracker.ensure_available(_client(), 100.0, command_name="serial_dilution")
        assert source == _pos("A2")
        # New source has no measurement yet, so budget resets to None.
        assert budget is None

    def test_no_switch_when_sufficient(self):
        tracker = LiquidSourceTracker([_pos("A1"), _pos("A2")])
        tracker.record_aspirate(_asp(500.0))
        source, budget = tracker.ensure_available(_client(), 100.0, command_name="serial_dilution")
        assert source == _pos("A1")
        assert budget == 500.0

    def test_advances_across_multiple_sources(self):
        tracker = LiquidSourceTracker([_pos("A1"), _pos("A2"), _pos("A3")])
        tracker.record_aspirate(_asp(10.0))
        source, _ = tracker.ensure_available(_client(), 100.0, command_name="serial_dilution")
        assert source == _pos("A2")


class TestOperatorPrompt:
    def test_no_callback_traces_the_shortage_and_carries_on(self, caplog):
        # Nobody can log a refill, so the run must not end over an estimate: the
        # shortage is traced and the estimate starts over from the next aspirate.
        client = _client(callback=None)
        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.record_aspirate(_asp(10.0))
        source, budget = tracker.ensure_available(client, 100.0, command_name="serial_dilution")
        assert source == _pos("A1")
        assert budget is None
        assert "no refill was logged" in caplog.text
        (entry,) = client._run_log.record.call_args_list
        assert entry.args[2] == "liquid_shortage"
        assert entry.args[3]["required_ul"] == 100.0

    def test_a_failing_run_log_does_not_stop_the_run(self):
        client = _client(callback=None)
        client._run_log.record.side_effect = OSError("disk full")
        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.record_aspirate(_asp(10.0))
        tracker.ensure_available(client, 100.0, command_name="serial_dilution")

    def test_callback_true_replenishes(self):
        callback = MagicMock(return_value=True)
        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.record_aspirate(_asp(10.0))
        source, budget = tracker.ensure_available(_client(callback=callback), 100.0, command_name="serial_dilution")
        assert source == _pos("A1")
        # After a reload the estimate is cleared (re-read on next aspirate).
        assert budget is None
        assert callback.call_count == 1

    def test_callback_receives_context(self):
        received: list = []

        def callback(ctx) -> bool:
            received.append(ctx)
            return True

        # A single source guarantees exhaustion (there is nowhere to advance),
        # so the prompt fires and the context reflects that source.
        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.record_aspirate(_asp(5.0))
        tracker.ensure_available(_client(callback=callback), 250.0, command_name="serial_dilution")
        assert len(received) == 1
        ctx = received[0]
        assert ctx.sources == ("DiluentTrough@A1",)
        assert ctx.active_source == "DiluentTrough@A1"
        assert ctx.required == 250.0
        assert ctx.available == 5.0
        assert ctx.command == "serial_dilution"
        assert ctx.attempt == 1

    def test_callback_false_raises_cancelled(self):
        callback = MagicMock(return_value=False)
        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.record_aspirate(_asp(10.0))
        with pytest.raises(OperatorCancelledError, match="cancelled liquid reload"):
            tracker.ensure_available(_client(callback=callback), 100.0, command_name="serial_dilution")

    def test_async_callback_true(self):
        async def callback(ctx) -> bool:
            return True

        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.record_aspirate(_asp(10.0))
        source, budget = tracker.ensure_available(_client(callback=callback), 100.0, command_name="serial_dilution")
        assert source == _pos("A1")
        assert budget is None

    def test_async_callback_false_raises_cancelled(self):
        async def callback(ctx) -> bool:
            return False

        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.record_aspirate(_asp(10.0))
        with pytest.raises(OperatorCancelledError):
            tracker.ensure_available(_client(callback=callback), 100.0, command_name="serial_dilution")


class TestConnectedSourceLabware:
    def test_returns_connected_labware_ids(self):
        client = MagicMock()
        client.get_labware_spec.side_effect = lambda labware: MagicMock(
            connected_container=(labware == "Container")
        )
        result = connected_source_labware(
            client, [_pos("A1", "Container"), _pos("A2", "Container"), _pos("A1", "Trough")]
        )
        assert result == {"Container"}

    def test_looks_up_each_labware_once(self):
        client = MagicMock()
        client.get_labware_spec.return_value = MagicMock(connected_container=True)
        connected_source_labware(client, [_pos("A1", "Container"), _pos("A2", "Container")])
        assert client.get_labware_spec.call_count == 1

    def test_unresolved_labware_treated_as_non_connected(self):
        client = MagicMock()
        client.get_labware_spec.side_effect = RuntimeError("no geometry")
        assert connected_source_labware(client, [_pos("A1", "Container")]) == set()


class TestConnectedChannelCap:
    def test_no_connected_returns_full_channels(self):
        sources = [_pos("A1", "Trough"), _pos("A2", "Trough")]
        assert connected_channel_cap(sources, set(), 8) == 8

    def test_caps_to_connected_position_count(self):
        sources = [_pos(str(i), "Container") for i in range(1, 5)]
        assert connected_channel_cap(sources, {"Container"}, 8) == 4

    def test_never_exceeds_n_channels(self):
        sources = [_pos(str(i), "Container") for i in range(1, 13)]
        assert connected_channel_cap(sources, {"Container"}, 8) == 8

    def test_takes_min_across_connected_labware(self):
        sources = [
            _pos("1", "A"),
            _pos("2", "A"),
            _pos("1", "B"),
            _pos("2", "B"),
            _pos("3", "B"),
        ]
        assert connected_channel_cap(sources, {"A", "B"}, 8) == 2


class TestAspiratePasses:
    def _tracker(self, n_sections: int) -> LiquidSourceTracker:
        sections = [_pos(str(i), "Reservoir") for i in range(1, n_sections + 1)]
        return LiquidSourceTracker(sections, connected_labware={"Reservoir"})

    def test_one_pass_when_the_sections_cover_the_channels(self):
        ((channels, positions),) = self._tracker(8).aspirate_passes([1, 2, 3])
        assert channels == [1, 2, 3]
        assert [p.well for p in positions] == ["1", "2", "3"]

    def test_channels_beyond_the_sections_start_again_at_the_first_section(self):
        passes = self._tracker(8).aspirate_passes(list(range(1, 17)))
        assert [channels for channels, _ in passes] == [list(range(1, 9)), list(range(9, 17))]
        for _, positions in passes:
            assert [p.well for p in positions] == [str(i) for i in range(1, 9)]

    def test_explicit_groups_spread_every_channel_over_their_positions(self):
        tubes = [_pos(str(i), "Tubes") for i in range(1, 5)]
        tracker = LiquidSourceTracker.from_groups([tubes[:1], tubes])
        # One tube: each channel takes its turn.
        assert [c for c, _ in tracker.aspirate_passes([1, 2, 3])] == [[1], [2], [3]]
        tracker.record_aspirate(_asp(0.0))
        tracker.ensure_available(_client(), 10.0, command_name="add_reagent")  # drains to group 2
        assert tracker.aspirate_passes([1, 2, 3, 4, 5, 6]) == [
            ([1, 2, 3, 4], tubes),
            ([5, 6], tubes[:2]),
        ]

    def test_a_non_connected_source_is_one_broadcast_pass(self):
        tracker = LiquidSourceTracker([_pos("A1")])
        assert tracker.aspirate_passes([1, 2]) == [([1, 2], [_pos("A1"), _pos("A1")])]


class TestExpandConnectedSources:
    def test_one_section_of_a_reservoir_means_all_of_it(self, monkeypatch):
        sections = [_pos(str(i), "Reservoir") for i in range(1, 9)]
        monkeypatch.setattr(
            "hamilton_venus.compound_commands._helpers._liquid_manager.resolve_selector_positions",
            lambda client, selector: sections if selector == "Reservoir" else [],
        )
        sources = [_pos("1", "Reservoir"), _pos("3", "Reservoir"), _pos("A1", "Tube")]
        assert expand_connected_sources(_client(), sources, {"Reservoir"}) == [*sections, _pos("A1", "Tube")]


class TestLldEnabled:
    def test_defaults_do_not_detect(self):
        assert not lld_enabled(None)
        assert not lld_enabled(AspirateSettings())

    def test_either_mode_on_any_channel_detects(self):
        assert lld_enabled(AspirateSettings(capacitive_lld=CapacitiveLLD.MID))
        assert lld_enabled(AspirateSettings(pressure_lld=[PressureLLD.OFF, PressureLLD.LOW]))

    def test_readings_without_detection_leave_the_estimate_alone(self):
        tracker = LiquidSourceTracker([_pos("A1")])
        tracker.record_aspirate(_asp(0.0), measured_level=False)
        assert tracker.budget is None


class TestAspiratePlan:
    def test_spreads_across_connected_positions(self):
        sources = [_pos("A1", "Container"), _pos("A2", "Container"), _pos("A3", "Container")]
        tracker = LiquidSourceTracker(sources, connected_labware={"Container"})
        assert tracker.aspirate_plan(3) == sources
        assert tracker.aspirate_plan(2) == sources[:2]

    def test_broadcasts_when_channels_exceed_positions(self):
        sources = [_pos("A1", "Container"), _pos("A2", "Container")]
        tracker = LiquidSourceTracker(sources, connected_labware={"Container"})
        # 3 channels do not fit the 2-position container -> broadcast the first.
        assert tracker.aspirate_plan(3) == [_pos("A1", "Container")] * 3

    def test_broadcasts_when_not_connected(self):
        sources = [_pos("A1"), _pos("A2"), _pos("A3")]
        tracker = LiquidSourceTracker(sources)
        assert tracker.aspirate_plan(3) == [_pos("A1")] * 3

    def test_single_connected_position_broadcasts(self):
        tracker = LiquidSourceTracker([_pos("A1", "Container")], connected_labware={"Container"})
        assert tracker.aspirate_plan(1) == [_pos("A1", "Container")]
        assert tracker.aspirate_plan(4) == [_pos("A1", "Container")] * 4


class TestConnectedGroupSwitching:
    def test_connected_group_drains_as_one_source(self):
        # A connected container's positions form a single logical source, so a
        # short measurement advances past the whole container, not per-position.
        sources = [_pos("A1", "Container"), _pos("A2", "Container"), _pos("A1", "Trough")]
        tracker = LiquidSourceTracker(sources, connected_labware={"Container"})
        assert tracker.active_source == _pos("A1", "Container")
        tracker.record_aspirate(_asp(5.0))
        source, _ = tracker.ensure_available(_client(), 100.0, command_name="add_reagent")
        assert source == _pos("A1", "Trough")

    def test_sources_used_flattens_connected_group(self):
        sources = [_pos("A1", "Container"), _pos("A2", "Container"), _pos("A1", "Trough")]
        tracker = LiquidSourceTracker(sources, connected_labware={"Container"})
        # Before advancing, the whole connected group counts as used.
        assert tracker.sources_used == [_pos("A1", "Container"), _pos("A2", "Container")]
        tracker.record_aspirate(_asp(5.0))
        tracker.ensure_available(_client(), 100.0, command_name="add_reagent")
        assert tracker.sources_used == [
            _pos("A1", "Container"),
            _pos("A2", "Container"),
            _pos("A1", "Trough"),
        ]


class TestEnsureLiquidAvailableFacade:
    def test_single_source_returns_unchanged(self):
        source, budget = ensure_liquid_available(_client(), [_pos("A1")], 500.0, command_name="add_reagent")
        assert source == _pos("A1")
        assert budget is None

    def test_empty_sources_raises(self):
        with pytest.raises(ValueError, match="at least one source"):
            ensure_liquid_available(_client(), [], 500.0, command_name="add_reagent")

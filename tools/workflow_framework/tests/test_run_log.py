"""Unit tests for hamilton_workflow_framework.run_log, on two trimmed real run logs:

- tip_pickup_error_run.json: a STARlet tip pickup that failed with P1:08/78 ("No tip or
  wrong tip type") four times -- three Repeats, then Abort -- ending the run in error.
- split_well_run.json: a Script Manager run that removes media from split wells of a 6-well
  plate into the liquid waste and adds a reagent; carries the Script Manager's own events.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hamilton_workflow_framework.run_log import (
    analyze_errors,
    build_sample_tracking,
    build_trace,
    parse_venus_trace,
)
from hamilton_workflow_framework.run_log._common import run_timezone
from hamilton_workflow_framework.run_log.errors import decode_error_code, likely_cause
from hamilton_workflow_framework.run_log.trace import decode_trace_bytes
from hamilton_workflow_framework.run_log.venus_runs import base_url_for

FIXTURES = Path(__file__).parent / "fixtures" / "run_logs"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tip_error_log() -> dict:
    return _load("tip_pickup_error_run.json")


@pytest.fixture(scope="module")
def split_well_log() -> dict:
    return _load("split_well_run.json")


def _without_sample_markers(log: dict) -> dict:
    stripped = copy.deepcopy(log)
    stripped["log"] = [
        e for e in stripped["log"]
        if not (e.get("type") == "script_output" and e["payload"].get("message", "").startswith(("\x00SAMPLE", "\x00TADM")))
    ]
    return stripped


# --- trace -----------------------------------------------------------------------


def test_trace_is_sorted_and_categorized(split_well_log):
    lines = build_trace(split_well_log)
    stamps = [line["timestamp"] for line in lines if line["timestamp"]]
    assert stamps == sorted(stamps)
    categories = {line["category"] for line in lines}
    assert {"terminal", "communication", "comtrace", "venus", "info"} <= categories
    # Bootstrap markers feed other views and never show as text.
    assert not any("\x00" in line["text"] for line in lines)


def test_trace_command_lines_name_the_action(split_well_log):
    texts = [line["text"] for line in build_trace(split_well_log) if line["category"] == "communication"]
    assert any(t.startswith("→ channels.1mL.aspirate") and "positions=" in t for t in texts)
    assert any(t.startswith("← channels.1mL.aspirate Success") for t in texts)


def test_trace_uses_venus_trace_file_instead_of_runtime_trace(split_well_log):
    lines = build_trace(split_well_log, venus_trace_lines=["2026-10-20 22:53:01.000 From the .trc file"])
    venus = [line for line in lines if line["category"] == "venus"]
    assert [line["text"] for line in venus] == ["2026-10-20 22:53:01.000 From the .trc file"]
    assert venus[0]["timestamp"].startswith("2026-10-20T22:53:01")


def test_trace_marks_errors(tip_error_log):
    errors = [line["text"] for line in build_trace(tip_error_log) if line["category"] == "error"]
    assert any(t.startswith("Instrument error P1:08/78") for t in errors)
    assert any(t.startswith("Session ended: error") for t in errors)


def test_old_log_timezone_comes_from_venus_trace(tip_error_log):
    # This log predates timestamp_local; VENUS's local clock in runtime_trace gives UTC-4.
    assert run_timezone(tip_error_log).utcoffset(None).total_seconds() == -4 * 3600


def test_parse_venus_trace_carries_time_to_continuation_lines():
    from datetime import timezone

    parsed = parse_venus_trace(["2026-10-21 15:03:17.332 First", "  continuation", ""], timezone.utc)
    assert [text for _, text in parsed] == ["2026-10-21 15:03:17.332 First", "  continuation"]
    assert parsed[1][0] == parsed[0][0]


def test_decode_trace_bytes_handles_cp1252():
    assert decode_trace_bytes("2026-10-21 Temp 37 °C".encode("cp1252")) == "2026-10-21 Temp 37 °C"
    assert decode_trace_bytes("abc".encode("utf-16")) == "abc"


# --- errors -------------------------------------------------------------------


def test_repeated_tip_errors_are_one_incident(tip_error_log):
    result = analyze_errors(tip_error_log)
    assert result["counts"] == {"incidents": 1, "instrument_errors": 4, "failed_commands": 0}
    incident = result["incidents"][0]
    assert incident["kind"] == "instrument_error"
    assert incident["command"]["action"] == "channels.1mL.tipPickup"
    assert incident["command"]["tip_pool"] == "300uLTips"
    assert [a["recovery"] for a in incident["attempts"]] == ["Repeat", "Repeat", "Repeat", "Abort"]
    assert {"Repeat", "Abort", "Exclude"} <= set(incident["recoveries_offered"])
    assert incident["details"] == [
        {"message": "No tip or wrong tip type detected.", "code": "78", "channels": ["1", "2", "3", "4"]}
    ]


def test_incident_decodes_code_and_gives_a_hint(tip_error_log):
    incident = analyze_errors(tip_error_log)["incidents"][0]
    assert incident["codes"] == ["P1:08/78"]
    assert incident["decoded"][0]["module"] == "1000ul Channels"
    assert incident["decoded"][0]["description"] == "Tip handling: No tip or wrong tip type detected."
    assert incident["hint"].startswith("Tip pickup or eject failed")


def test_incident_context_highlights_the_failing_firmware_reply(tip_error_log):
    context = analyze_errors(tip_error_log)["incidents"][0]["context"]
    highlighted = [line["text"] for line in context["comtrace"] if line["highlight"]]
    assert any("C0TP" in text and "er99/00 P108/78" in text for text in highlighted)
    assert context["commands"][-1]["action"] == "channels.1mL.tipPickup"


def test_outcome_names_the_command_the_run_stopped_in(tip_error_log):
    outcome = analyze_errors(tip_error_log)["outcome"]
    assert outcome["result"] == "error"
    assert outcome["error_type"] == "VenusCommandAbortedError"
    assert outcome["final_command"]["action"] == "channels.1mL.tipPickup"
    assert outcome["final_command"]["result"] == "running"
    assert outcome["final_incident"] == "incident-1"


def test_clean_run_has_no_incidents(split_well_log):
    result = analyze_errors(split_well_log)
    assert result["incidents"] == []
    assert result["outcome"]["result"] == "success"


def test_decode_error_code_segments():
    decoded = decode_error_code("P1:06/70")
    assert decoded[0]["unit"] == "1"
    assert decoded[0]["description"] == "Level detection: Liquid level error. Liquid level not found."
    assert decode_error_code(None) == []


def test_likely_cause_falls_back_to_generic():
    assert likely_cause("Something unusual happened").startswith("Read the VENUS trace")


# --- sample tracking ------------------------------------------------------------


def test_samples_from_script_manager_events(split_well_log):
    samples = build_sample_tracking(split_well_log)
    assert samples["source"] == "script_manager"
    assert [l["labware"] for l in samples["labware"]] == ["CellPlate"]
    assert all(e["timestamp"] for e in samples["events"])


def test_rebuilt_samples_match_the_script_manager(split_well_log):
    def key(e):
        return (e["labware"], e["well"], e["operation"], e["channel"], e["volume"], round(e["current_volume_ul"], 3),
                e["source_labware"], e["source_well"])

    recorded = build_sample_tracking(split_well_log)
    rebuilt = build_sample_tracking(_without_sample_markers(split_well_log))
    assert rebuilt["source"] == "rebuilt"
    cell_plate = [key(e) for e in rebuilt["events"] if e["labware"] == "CellPlate"]
    assert sorted(cell_plate) == sorted(key(e) for e in recorded["events"])


def test_rebuilt_samples_map_split_slots_to_parent_wells(split_well_log):
    rebuilt = build_sample_tracking(_without_sample_markers(split_well_log))
    info = {l["labware"]: l for l in rebuilt["labware"]}
    assert (info["CellPlate"]["rows"], info["CellPlate"]["cols"], info["CellPlate"]["pattern"]) == (2, 3, "ROW_MAJOR")
    wells = {e["well"] for e in rebuilt["events"] if e["labware"] == "CellPlate"}
    assert wells == {"A1", "B1", "A2", "B2", "A3", "B3"}


def test_rebuilt_samples_track_the_liquid_waste_and_link_aspirates(split_well_log):
    rebuilt = build_sample_tracking(_without_sample_markers(split_well_log))
    waste = [e for e in rebuilt["events"] if e["labware"] == "liquid_waste"]
    assert waste and all(e["operation"] == "dispense" and e["source_labware"] == "CellPlate" for e in waste)
    aspirate_ids = {e["transfer_id"] for e in rebuilt["events"] if e["operation"] == "aspirate"}
    assert {e["source_transfer_id"] for e in waste} <= aspirate_ids
    # The reagent reservoir is a source only: no card for it.
    assert "Trypsin" not in {l["labware"] for l in rebuilt["labware"]}


def test_rebuilt_samples_on_a_log_without_transfers(tip_error_log):
    assert build_sample_tracking(tip_error_log) == {"source": "rebuilt", "labware": [], "events": [], "tadm": []}


def test_malformed_log_degrades_quietly():
    broken = {"log": [None, {"type": "command_response", "payload": "x"}, {"type": "script_output"}]}
    assert build_trace(broken) == []
    assert analyze_errors(broken)["incidents"] == []
    assert build_sample_tracking(broken)["events"] == []


# --- VENUS host ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "expected"),
    [("", "http://localhost:42400"), ("pc1", "http://pc1:42400"), ("pc1:5000", "http://pc1:5000"),
     ("https://pc2/", "https://pc2:42400")],
)
def test_base_url_for(host, expected):
    assert base_url_for(host) == expected


# --- commands -----------------------------------------------------------------


def test_command_list_has_every_command_in_order(tip_error_log):
    from hamilton_workflow_framework.run_log import build_command_list

    rows = build_command_list(tip_error_log)
    assert len(rows) == 27
    assert [r["sequence"] for r in rows] == sorted(r["sequence"] for r in rows)
    last = rows[-1]
    assert (last["action"], last["result"], last["error_count"], last["duration_seconds"]) == (
        "channels.1mL.tipPickup", "running", 4, None,
    )
    assert last["summary"] == "tipPool=300uLTips"
    assert all(r["result"] == "success" for r in rows[:-1])


def test_command_detail_gathers_messages_errors_and_trace(tip_error_log):
    from hamilton_workflow_framework.run_log import build_command_detail, build_command_list

    command_id = build_command_list(tip_error_log)[-1]["command_id"]
    detail = build_command_detail(tip_error_log, command_id, build_trace(tip_error_log))
    assert [c["status"] for c in detail["communication"]] == ["Command Received", "Pickup tips..."]
    assert len(detail["errors"]) == 4
    assert {d["channel"] for d in detail["errors"][0]["details"]} == {"1", "2", "3", "4"}
    assert detail["parameters"]["tipPool"] == "300uLTips"
    assert detail["response"] is None  # the run ended inside this command
    # No response: its window runs to the end of the log, so the abort is in it.
    assert any("er99/00 P108/78" in line["text"] for line in detail["comtrace"])
    assert detail["venus"]


def test_command_detail_of_a_finished_command(split_well_log):
    from hamilton_workflow_framework.run_log import build_command_detail, build_command_list

    row = next(r for r in build_command_list(split_well_log) if r["action"] == "channels.1mL.aspirate")
    detail = build_command_detail(split_well_log, row["command_id"], build_trace(split_well_log))
    assert detail["result"] == "success"
    assert detail["response"]["returnParameters"]["channels"][0]["aspiratedVolume"] == 1000.0
    assert build_command_detail(split_well_log, "no-such-id", []) is None


# --- VENUS run outcomes -----------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b'{\n  "schema_version": "1.0",\n  "reason": "error",\n  "log": [', "error"),
        (b'{"reason": "normal", "log": []}', "ok"),
        (b'{"reason": "recovered", "log": []}', "other"),
        (b'{"schema_version": "1.0", "log": [', "other"),
        (None, "no_log"),
    ],
)
def test_outcome_from_log_head(head, expected):
    from hamilton_workflow_framework.run_log.venus_runs import _outcome_from_head

    assert _outcome_from_head(head) == expected


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b'{"reason": "normal", "log": [{"type": "session_start", "payload": {"simulate": false}}', True),
        (b'{"log": [{"payload": {"config": {}, "simulate": true}}', False),
        (b'{"reason": "normal", "log": [', None),
        (None, None),
    ],
)
def test_live_from_log_head(head, expected):
    from hamilton_workflow_framework.run_log.venus_runs import _live_from_head

    assert _live_from_head(head) is expected


@pytest.mark.parametrize(
    ("instruments", "expected"),
    [
        ([{"instrumentName": "VANTAGE", "instrumentSimulation": True}], False),
        ([{"instrumentName": "STAR", "instrumentSimulation": False}], True),
        ([{"instrumentSimulation": True}, {"instrumentSimulation": False}], True),
        ([], None),
    ],
)
def test_live_from_venus_run_details(instruments, expected):
    from hamilton_workflow_framework.run_log.venus_runs import _live_from_details

    assert _live_from_details({"instruments": instruments}) is expected


def test_run_list_with_an_older_sdk_degrades_and_says_so(monkeypatch, tmp_path):
    """An app reinstalled without "Set up / update VENUS SDK" gets this workflow_framework
    with an SDK whose VenusClient lacks get_file_asset_head and get_run_details."""
    import asyncio

    from hamilton_workflow_framework.run_log import venus_runs

    log_files = tmp_path / "LogFiles"
    log_files.mkdir()
    (log_files / "M_g1_SdkRunLog.json").write_text('{"reason": "error", "log": [{"payload": {"simulate": false}}', encoding="utf-8")

    class OldVenusClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def get_run_history(self, **_kwargs):
            rows = [{"runGuid": g, "methodDisplayName": "M", "runState": "Finished"} for g in ("g1", "g2")]
            return {"subList": rows, "spanCount": 2}

        async def get_system_paths(self):
            return {"LogFiles": str(log_files)}

    monkeypatch.setattr(venus_runs, "VenusClient", OldVenusClient)
    monkeypatch.setattr(venus_runs, "_LIVE_FROM_DETAILS", {})

    local = asyncio.run(venus_runs.list_runs("localhost"))
    # This PC: the log head is read from disk, so g1 is still known; g2 has no SDK log and is left out.
    assert [(r["outcome"], r["live"]) for r in local["runs"]] == [("error", True)]
    assert "older than this viewer" in local["notes"][0]

    monkeypatch.setattr(venus_runs, "_is_this_pc", lambda host: False)
    remote = asyncio.run(venus_runs.list_runs("pc1"))
    assert [(r["outcome"], r["live"]) for r in remote["runs"]] == [("unknown", None), ("unknown", None)]


def test_run_list_skips_trace_only_runs_and_reads_on(monkeypatch, tmp_path):
    """VENUS methods not run from Python have no SDK log; the list reads further pages of
    VENUS's history to fill a page with Python runs."""
    import asyncio

    from hamilton_workflow_framework.run_log import venus_runs

    log_files = tmp_path / "LogFiles"
    log_files.mkdir()
    for guid in ("g2", "g5"):
        (log_files / f"M_{guid}_SdkRunLog.json").write_text('{"reason": "normal", "log": [{"payload": {"simulate": true}}', encoding="utf-8")
    history = [{"runGuid": f"g{i}", "methodDisplayName": "M", "runState": "Finished"} for i in range(1, 7)]
    calls = []

    class FakeVenusClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def get_run_history(self, *, limit, offset):
            calls.append(offset)
            return {"subList": history[offset - 1:offset - 1 + limit], "spanCount": len(history)}

        async def get_system_paths(self):
            return {"LogFiles": str(log_files)}

        async def get_file_asset_head(self, *_args):
            raise AssertionError("this PC's logs are read from disk")

        async def get_run_details(self, _guid):
            raise AssertionError("not needed for runs without an SDK log")

    monkeypatch.setattr(venus_runs, "VenusClient", FakeVenusClient)

    first = asyncio.run(venus_runs.list_runs("localhost", limit=2))
    assert [r["run_guid"] for r in first["runs"]] == ["g2", "g5"]
    assert calls == [1, 3, 5] and first["next_offset"] == 7 and not first["has_more"]

    calls.clear()
    short = asyncio.run(venus_runs.list_runs("localhost", limit=1))
    assert [r["run_guid"] for r in short["runs"]] == ["g2"]
    assert calls == [1, 2] and short["next_offset"] == 3 and short["has_more"]


def test_no_sdk_note_with_the_current_sdk():
    from hamilton_workflow_framework.run_log.venus_runs import sdk_update_note

    assert sdk_update_note() is None

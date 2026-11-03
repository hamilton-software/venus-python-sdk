"""A stand-in for script_runs/child_bootstrap.py, for testing the run manager without VENUS.

It speaks the same protocol. What it does is chosen by the first line of the "script" it is
given, ``# mode: <name>``:

    quick        emit tracking events, print a line, exit 0
    fail         exit 1 with an error and an error line
    prompt       raise an operator_error prompt, wait for the answer; "abort" exits 1, else 0
    reload       raise a tip_reload prompt; "continue" exits 0, else 1
    slow         run until told to stop; understands PAUSE / RESUME / STOP
    ignore_stop  ignores STOP entirely (to exercise the hard kill)
    env          report whether the operator token is in its environment
    silent_exit  exit 0 without ever saying anything
    logged       like "quick", but also writes a real, finalized SdkRunLog.json (+
                 line_timeline.json) to run_log_dir, so RunManager._finish can compute a real
                 summary and record it to the ledger.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from hamilton_venus_mcp.script_runs.protocol import encode_event


FAKE_VENUS_RUN_GUID = "6defca7bf3de498e8b93303bc93a245d"


def emit(event_type: str, **data) -> None:
    sys.stdout.write(encode_event(event_type, **data))
    sys.stdout.flush()


def read_command() -> str | None:
    line = sys.stdin.readline()
    return line.strip() if line else None


def _write_fake_run_log(run_log_dir: Path, script_name: str) -> None:
    print("VenusTrace: 2026-09-23 16:37:41.201 Microlab STARlet : Start method command - progress; Serial number of Instrument: AI68", file=sys.stderr, flush=True)
    """A minimal but valid finalized SdkRunLog.json, hand-built to match the exact shape
    hamilton_workflow_framework.run_summary.summarize_run reads (see that module): one tip rack
    add, one 8-channel tip pickup against pool "P", one aspirate from a reservoir "Trough1"
    (with a matching reservoir_labware entry), wrapped in session_start/session_end SDK entries.
    """
    run_log_dir.mkdir(parents=True, exist_ok=True)
    log = {
        "script_name": script_name,
        "started_at": "2026-09-22T10:00:00+00:00",
        "ended_at": "2026-09-22T10:00:12+00:00",
        "log": [
            {"source": "SDK", "type": "session_start", "payload": {"simulate": True}},
            {
                "type": "command_request",
                "timestamp": "2026-09-22T10:00:01+00:00",
                "payload": {
                    "command_id": "c1",
                    "action_name": "labware.addTipRack",
                    "category": "Deck Layout",
                    "parameters": {"labwareDefinition": "Tip_Rack_50ul", "tipPool": "P"},
                },
            },
            {
                "type": "command_response",
                "payload": {"id": "c1", "returnCode": 0, "returnStatus": "Success", "returnParameters": {"tipPoolName": "P"}},
            },
            {
                "type": "command_request",
                "timestamp": "2026-09-22T10:00:02+00:00",
                "payload": {
                    "command_id": "c2",
                    "action_name": "channels.1mL.tipPickup",
                    "category": "Instrument",
                    "parameters": {"channels": [1, 2, 3, 4, 5, 6, 7, 8], "tipPool": "P"},
                },
            },
            {
                "type": "command_response",
                "payload": {"id": "c2", "returnCode": 0, "returnStatus": "Success", "returnParameters": {"remainingTips": 88}},
            },
            {"type": "reservoir_labware", "payload": {"labware": "Trough1"}},
            {
                "type": "command_request",
                "timestamp": "2026-09-22T10:00:03+00:00",
                "payload": {
                    "command_id": "c3",
                    "action_name": "channels.1mL.aspirate",
                    "category": "Instrument",
                    "parameters": {"positions": [{"labwareId": "Trough1", "wellId": "1"}], "volumes": 50.0},
                },
            },
            {"type": "command_response", "payload": {"id": "c3", "returnCode": 0, "returnStatus": "Success", "returnParameters": {}}},
            {"source": "SDK", "type": "session_end", "payload": {"duration_seconds": 12.0, "reason": "normal"}},
        ],
    }
    for entry in log["log"]:
        entry.setdefault("timestamp", log["started_at"])
    (run_log_dir / f"{script_name}_{FAKE_VENUS_RUN_GUID}_SdkRunLog.json").write_text(json.dumps(log), encoding="utf-8")
    (run_log_dir / "line_timeline.json").write_text(json.dumps([[1758535201.0, 1], [1758535202.0, 3]]), encoding="utf-8")


def main() -> None:
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    first_line = Path(config["script_path"]).read_text(encoding="utf-8").splitlines()[0]
    mode = first_line.split(":", 1)[1].strip() if first_line.startswith("# mode:") else "quick"

    if mode == "silent_exit":
        sys.exit(0)
    emit("started", pid=os.getpid(), script=Path(config["script_path"]).name, simulate=config["simulate"])
    emit("sim_mode", previous=False, current=config["simulate"], changed=config["simulate"] is not False)

    if mode == "quick":
        emit("client", client="StarClient", simulate=config["simulate"])
        emit("labware", method="add_plate", definition="Cos_96_Rd", labware_name="plate1", carrier_id="c1", site="1")
        emit("tips", tip_pool="P", remaining=88, picked_up=8)
        emit("tips", tip_pool="P", remaining=80, picked_up=8)
        emit(
            "aspirate",
            readings=[
                {"labware": "trough", "well": "1", "channel": 1, "liquid_volume_ul": 900.0, "liquid_level_mm": 12.0, "aspirated_ul": 50.0},
                {"labware": "trough", "well": "1", "channel": 2, "liquid_volume_ul": 850.0, "liquid_level_mm": 11.0, "aspirated_ul": 50.0},
            ],
        )
        emit("line", line=7)
        print("quick script says hi", flush=True)
        emit("script_exit", status="completed", exit_code=0, error=None, error_line=None)
        sys.exit(0)

    if mode == "logged":
        emit("client", client="StarClient", simulate=config["simulate"])
        emit("labware", method="add_tip_rack", definition="Tip_Rack_50ul", labware_name="tips1", carrier_id="c1", site="1", tip_pool="P")
        emit("tips", tip_pool="P", remaining=88, capacity=96, picked_up=8)
        emit(
            "aspirate",
            readings=[
                {
                    "labware": "Trough1",
                    "well": "1",
                    "channel": 1,
                    "liquid_volume_ul": 900.0,
                    "liquid_level_mm": 12.0,
                    "aspirated_ul": 50.0,
                    "key": "Trough1",
                    "remaining_volume_ul": 900.0,
                    "total_volume_ul": 1000.0,
                    "percent_full": 0.9,
                }
            ],
        )
        _write_fake_run_log(Path(config["run_log_dir"]), Path(config["script_path"]).name)
        emit("line", line=6)
        print("logged script says hi", flush=True)
        emit("script_exit", status="completed", exit_code=0, error=None, error_line=None)
        sys.exit(0)

    if mode == "fail":
        emit("line", line=3)
        emit(
            "script_exit",
            status="failed",
            exit_code=1,
            error={"type": "VenusError", "message": "Tip pickup failed"},
            error_line=3,
        )
        sys.exit(1)

    if mode in ("prompt", "reload"):
        if mode == "prompt":
            emit(
                "prompt",
                prompt_id="err-1",
                kind="operator_error",
                code="P1:01/32",
                title="Tip pickup - error",
                channel_errors=[
                    {
                        "channels": ["1", "2"],
                        "message": "No tip picked up.",
                        "detail_uuids": ["d1", "d2"],
                        "actions": [{"id": 1026, "name": "Repeat"}, {"id": 1030, "name": "Exclude"}],
                        "default_action_id": 1026,
                    }
                ],
                options=["retry", "abort"],
            )
            prompt_id = "err-1"
        else:
            emit("prompt", prompt_id="tip-1", kind="tip_reload", title="Reload tips", options=["continue", "abort"])
            prompt_id = "tip-1"
        line = read_command() or ""
        parts = line.split(" ", 2)
        response = json.loads(parts[2]) if len(parts) == 3 and parts[0] == "PROMPT_RESPONSE" and parts[1] == prompt_id else None
        emit("log", level="INFO", source="fake", message=f"answer: {json.dumps(response)}")
        chosen = (response or {}).get("action") or (response or {}).get("kind")
        ok = chosen in ("retry", "continue", "channels")
        if mode == "reload" and chosen == "continue":
            # Mirrors child_bootstrap._on_tip_reload_prompt: a continued reload is an operator
            # reload event for the ledger, not tip usage.
            emit("reload", kind="tip", item_key="P", command="add_reagent")
        emit("script_exit", status="completed" if ok else "failed", exit_code=0 if ok else 1, error=None if ok else {"type": "Aborted", "message": "Operator aborted"}, error_line=None)
        sys.exit(0 if ok else 1)

    if mode == "env":
        emit("log", level="INFO", source="fake", message=f"token_in_env={'HAMILTON_MCP_OPERATOR_TOKEN' in os.environ}")
        print(f"token_in_env={'HAMILTON_MCP_OPERATOR_TOKEN' in os.environ}", flush=True)
        emit("script_exit", status="completed", exit_code=0, error=None, error_line=None)
        sys.exit(0)

    # slow / ignore_stop: run until stopped
    emit("line", line=1)
    while True:
        command = read_command()
        if command is None:
            sys.exit(3)
        if command == "PAUSE":
            emit("state", state="paused")
        elif command == "RESUME":
            emit("state", state="running")
        elif command == "STOP" and mode == "slow":
            emit("script_exit", status="stopped", exit_code=0, error=None, error_line=None)
            sys.exit(0)
        elif command == "STOP" and mode == "ignore_stop":
            while True:
                time.sleep(1)


if __name__ == "__main__":
    main()

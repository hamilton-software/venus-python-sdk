"""The Claude Code plugin's hardware approval hook (ai_harness/claude_code/hamilton-venus/hooks/hardware_gate.py)."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from hamilton_venus_mcp.command_kinds import STANDALONE_DEVICE_PREFIXES

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK = REPO_ROOT / "tools" / "ai_harness" / "claude_code" / "hamilton-venus" / "hooks" / "hardware_gate.py"
PREFIX = "mcp__plugin_hamilton-venus_hamilton-venus__"

_spec = importlib.util.spec_from_file_location("hardware_gate", HOOK)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


@pytest.fixture(autouse=True)
def harness_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HAMILTON_AI_HARNESS_DIR", str(tmp_path))
    return tmp_path


def run(event: dict, monkeypatch) -> dict | None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    assert gate.main() == 0
    text = out.getvalue().strip()
    return json.loads(text) if text else None


def pre(tool: str, tool_input: dict, monkeypatch, session: str = "s1") -> str | None:
    result = run(
        {"hook_event_name": "PreToolUse", "session_id": session, "tool_name": PREFIX + tool, "tool_input": tool_input},
        monkeypatch,
    )
    return None if result is None else result["hookSpecificOutput"]["permissionDecision"]


def post(tool: str, tool_input: dict, monkeypatch, response=None, session: str = "s1") -> None:
    event = {
        "hook_event_name": "PostToolUse",
        "session_id": session,
        "tool_name": PREFIX + tool,
        "tool_input": tool_input,
        "tool_response": response if response is not None else {},
    }
    assert run(event, monkeypatch) is None


def test_simulated_session_commands_pass(monkeypatch):
    post("start_session", {"simulate": True}, monkeypatch)
    assert pre("call_sdk_command", {"name": "aspirate", "kwargs": {"volumes": 50}}, monkeypatch) is None


def test_live_session_is_approved_once(monkeypatch):
    assert pre("start_session", {"simulate": False, "instrument_type": "STAR"}, monkeypatch) == "ask"
    post("start_session", {"simulate": False}, monkeypatch)  # it ran: the user approved it
    assert pre("call_sdk_command", {"name": "aspirate", "kwargs": {"volumes": 50}}, monkeypatch) is None
    assert pre("connect_instrument", {"initialize": True}, monkeypatch) is None
    assert pre("resolve_operator_prompt", {"error_uuid": "e", "action": "retry"}, monkeypatch) is None
    post("close_session", {}, monkeypatch)
    assert pre("call_sdk_command", {"name": "aspirate"}, monkeypatch) == "ask"  # the grant ended with it


def test_a_live_session_found_later_is_asked_once(monkeypatch):
    status = {"session_active": True, "simulate": False}
    post("get_session_status", {}, monkeypatch, response=[{"type": "text", "text": json.dumps(status)}])
    assert pre("call_sdk_command", {"name": "aspirate"}, monkeypatch) == "ask"
    post("call_sdk_command", {"name": "aspirate"}, monkeypatch)  # approved and run
    assert pre("call_sdk_command", {"name": "dispense"}, monkeypatch) is None


def test_queries_pass_even_on_hardware(monkeypatch):
    post("start_session", {"simulate": False}, monkeypatch)
    assert pre("call_sdk_command", {"name": "tip_pool_get_tip_counter"}, monkeypatch) is None
    assert pre("call_sdk_command", {"name": "instrument_is_idle"}, monkeypatch) is None


def test_unknown_session_asks(monkeypatch):
    assert pre("call_sdk_command", {"name": "tip_pickup"}, monkeypatch, session="never-started") == "ask"


def test_session_mode_from_get_session_status(monkeypatch):
    content = [{"type": "text", "text": json.dumps({"session_active": True, "simulate": True})}]
    post("get_session_status", {}, monkeypatch, response=content)
    assert pre("call_sdk_command", {"name": "tip_pickup"}, monkeypatch) is None


def test_session_status_without_a_session_is_not_simulated(monkeypatch):
    # Seen live: with no session open, get_session_status still says simulate=true (the default).
    post("start_session", {"simulate": True}, monkeypatch)
    status = {"session_active": False, "simulate": True, "connection_id": None}
    post("get_session_status", {}, monkeypatch, response=[{"type": "text", "text": json.dumps(status)}])
    assert pre("call_sdk_command", {"name": "tip_pickup"}, monkeypatch) == "ask"


def test_live_chosen_in_the_form_is_the_grant(monkeypatch):
    # simulate left unset: the user picked live in start_session's own form.
    result = [{"type": "text", "text": json.dumps({"session_id": "x", "simulate": False})}]
    post("start_session", {}, monkeypatch, response=result)
    assert pre("call_sdk_command", {"name": "tip_pickup"}, monkeypatch) is None
    post("start_session", {}, monkeypatch, response={"content": "not json"})
    assert pre("call_sdk_command", {"name": "tip_pickup"}, monkeypatch) == "ask"


def test_close_session_forgets_mode(monkeypatch):
    post("start_session", {"simulate": True}, monkeypatch)
    post("close_session", {}, monkeypatch)
    assert pre("call_sdk_command", {"name": "tip_pickup"}, monkeypatch) == "ask"


def test_standalone_device_asks_in_simulated_session_unless_simulated(monkeypatch):
    post("start_session", {"simulate": True}, monkeypatch)
    assert pre("call_sdk_command", {"name": "tilt_module_move_to_position", "kwargs": {}}, monkeypatch) == "ask"
    assert pre("call_sdk_command", {"name": "hhc_connect", "kwargs": {"simulate": True}}, monkeypatch) is None
    assert pre("call_sdk_command", {"name": "tilt_module_get_status"}, monkeypatch) is None


def test_each_device_is_approved_once(monkeypatch):
    post("call_sdk_command", {"name": "tilt_module_connect", "kwargs": {}}, monkeypatch)  # approved and run
    assert pre("call_sdk_command", {"name": "tilt_module_move_to_position", "kwargs": {}}, monkeypatch) is None
    assert pre("call_sdk_command", {"name": "hhc_set_temperature", "kwargs": {}}, monkeypatch) == "ask"


def test_venus_run_control_is_asked_every_time(monkeypatch):
    post("start_session", {"simulate": False}, monkeypatch)
    post("venus_pause", {}, monkeypatch)
    assert pre("venus_pause", {}, monkeypatch) == "ask"


def test_raw_command_asks_outside_simulation(monkeypatch):
    assert pre("send_raw_command", {"category": "status", "action_name": "x"}, monkeypatch) == "ask"


def test_run_control_and_initialize(monkeypatch):
    assert pre("venus_abort", {}, monkeypatch) == "ask"
    assert pre("run_script", {"script": "a.py", "simulate": False}, monkeypatch) == "ask"
    assert pre("run_script", {"script": "a.py"}, monkeypatch) is None
    assert pre("connect_instrument", {"initialize": True}, monkeypatch) == "ask"
    post("start_session", {"simulate": True}, monkeypatch)
    assert pre("connect_instrument", {"initialize": True}, monkeypatch) is None


def test_operator_prompt_denied(monkeypatch):
    assert pre("operator_resolve_prompt", {"run_id": "r", "prompt_id": "p", "token": "t"}, monkeypatch) == "deny"


def test_docs_and_catalog_pass(monkeypatch):
    assert pre("search_labware", {"search": "96"}, monkeypatch) is None
    assert pre("read_sdk_doc", {"relative_path": "README.md"}, monkeypatch) is None


def test_bad_input_asks(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    gate.main()
    assert json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_executed_hardware_calls_are_audited(monkeypatch, harness_dir):
    post("start_session", {"simulate": False}, monkeypatch)
    post("call_sdk_command", {"name": "aspirate", "kwargs": {"volumes": 50}}, monkeypatch)
    post("call_sdk_command", {"name": "get_added_plates"}, monkeypatch)
    lines = [json.loads(line) for line in (harness_dir / "hardware_calls.jsonl").read_text().splitlines()]
    assert [line["tool"] for line in lines] == ["start_session", "call_sdk_command"]
    assert lines[1]["input"]["name"] == "aspirate"


def test_hook_runs_as_a_script(harness_dir):
    event = {"hook_event_name": "PreToolUse", "session_id": "x", "tool_name": PREFIX + "venus_abort", "tool_input": {}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env={"HAMILTON_AI_HARNESS_DIR": str(harness_dir), "SYSTEMROOT": "C:\\Windows"},
        check=True,
    )
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_standalone_prefixes_match_sdk():
    from hamilton_venus.standalone_devices import STANDALONE_DEVICES

    assert set(STANDALONE_DEVICE_PREFIXES) == {spec.prefix for spec in STANDALONE_DEVICES}

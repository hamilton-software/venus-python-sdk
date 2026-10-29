"""Tests for ConsoleProxy."""

from __future__ import annotations

import builtins
import json
import threading
from pathlib import Path

import pytest

from hamilton_venus._internal._console_proxy import ConsoleProxy
from hamilton_venus._internal._run_log import RunLog
from hamilton_venus.config import RunLogConfig


@pytest.fixture()
def run_log(tmp_path: Path) -> RunLog:
    config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
    log = RunLog(config, session_id="console-test", sdk_version="0.4.0")
    yield log
    log.close()


def _read_entries(tmp_path: Path) -> list[dict]:
    jsonl_files = list(tmp_path.glob("*.jsonl"))
    assert len(jsonl_files) == 1
    return [json.loads(line) for line in jsonl_files[0].read_text().splitlines() if line.strip()]


class TestConsoleProxy:
    def test_print_captured_as_script_output(
        self,
        run_log: RunLog,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        proxy = ConsoleProxy(run_log)
        proxy.install()
        try:
            print("hello")
        finally:
            proxy.uninstall()

        entries = _read_entries(tmp_path)
        console_entries = [e for e in entries if e["source"] == "Console"]
        assert len(console_entries) == 1
        assert console_entries[0]["type"] == "script_output"
        assert console_entries[0]["payload"]["message"] == "hello"

    def test_input_captured_as_operator_input(self, run_log: RunLog, tmp_path: Path) -> None:
        proxy = ConsoleProxy(run_log, input_fn=lambda prompt="": "96")
        proxy.install()
        try:
            result = builtins.input("How many samples? ")
        finally:
            proxy.uninstall()

        assert result == "96"
        entries = _read_entries(tmp_path)
        console_entries = [e for e in entries if e["source"] == "Console"]
        assert len(console_entries) == 1
        assert console_entries[0]["type"] == "operator_input"
        assert console_entries[0]["payload"]["prompt"] == "How many samples? "
        assert console_entries[0]["payload"]["value"] == "96"

    def test_print_still_writes_to_stdout(self, run_log: RunLog, capsys: pytest.CaptureFixture[str]) -> None:
        proxy = ConsoleProxy(run_log)
        proxy.install()
        try:
            print("visible")
        finally:
            proxy.uninstall()

        captured = capsys.readouterr()
        assert "visible" in captured.out

    def test_uninstall_restores_original_print(self, run_log: RunLog) -> None:
        original = builtins.print
        proxy = ConsoleProxy(run_log)
        proxy.install()
        assert builtins.print is not original
        proxy.uninstall()
        assert builtins.print is original

    def test_uninstall_restores_original_input(self, run_log: RunLog) -> None:
        original = builtins.input
        proxy = ConsoleProxy(run_log)
        proxy.install()
        assert builtins.input is not original
        proxy.uninstall()
        assert builtins.input is original

    def test_uninstall_is_idempotent(self, run_log: RunLog) -> None:
        proxy = ConsoleProxy(run_log)
        proxy.install()
        proxy.uninstall()
        proxy.uninstall()  # Should not raise

    def test_proxy_thread_safe(self, run_log: RunLog, tmp_path: Path) -> None:
        proxy = ConsoleProxy(run_log)
        proxy.install()
        try:
            threads = []
            for i in range(10):
                t = threading.Thread(target=print, args=(f"msg-{i}",))
                threads.append(t)
                t.start()
            for t in threads:
                t.join()
        finally:
            proxy.uninstall()

        entries = _read_entries(tmp_path)
        console_entries = [e for e in entries if e["source"] == "Console"]
        assert len(console_entries) == 10
        messages = {e["payload"]["message"] for e in console_entries}
        assert messages == {f"msg-{i}" for i in range(10)}

    def test_default_input_wraps_and_restores_builtins(
        self,
        run_log: RunLog,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fake_input(prompt: str = "") -> str:
            return "42"

        monkeypatch.setattr(builtins, "input", fake_input)

        proxy = ConsoleProxy(run_log)
        assert proxy._original_input is fake_input
        proxy.install()
        try:
            result = builtins.input("Enter value: ")
        finally:
            proxy.uninstall()

        assert builtins.input is fake_input
        assert result == "42"
        entries = _read_entries(tmp_path)
        console_entries = [e for e in entries if e["source"] == "Console"]
        assert len(console_entries) == 1
        assert console_entries[0]["type"] == "operator_input"
        assert console_entries[0]["payload"]["prompt"] == "Enter value: "
        assert console_entries[0]["payload"]["value"] == "42"

    def test_print_to_other_file_not_captured(self, run_log: RunLog, tmp_path: Path) -> None:
        """Prints to a file other than stdout should not be captured in the run log."""
        import io

        proxy = ConsoleProxy(run_log)
        proxy.install()
        try:
            other_file = io.StringIO()
            print("logged")  # Default to stdout
            print("not-logged", file=other_file)
        finally:
            proxy.uninstall()

        entries = _read_entries(tmp_path)
        console_entries = [e for e in entries if e["source"] == "Console"]
        messages = [e["payload"]["message"] for e in console_entries]
        assert "logged" in messages
        assert "not-logged" not in messages

    def test_print_to_stderr_not_captured(self, run_log: RunLog, tmp_path: Path) -> None:
        """Prints to stderr should not be captured in the run log."""
        import sys

        proxy = ConsoleProxy(run_log)
        proxy.install()
        try:
            print("stdout-msg")
            print("stderr-msg", file=sys.stderr)
        finally:
            proxy.uninstall()

        entries = _read_entries(tmp_path)
        console_entries = [e for e in entries if e["source"] == "Console"]
        messages = [e["payload"]["message"] for e in console_entries]
        assert "stdout-msg" in messages
        assert "stderr-msg" not in messages

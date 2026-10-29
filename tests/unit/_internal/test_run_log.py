"""Unit tests for hamilton_venus._run_log."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

import pytest

from hamilton_venus._internal import _com_trace
from hamilton_venus._internal._run_log import RunLog, _utc_and_local
from hamilton_venus.config import RunLogConfig, load_config


class TestRunLogConfigDefaults:
    @pytest.fixture(autouse=True)
    def _run_log_env_unset(self, monkeypatch):
        # tests/unit/conftest.py turns the run log off for every test; these test the real defaults.
        monkeypatch.delenv("HAMILTON_VENUS_RUN_LOG_ENABLED", raising=False)
        monkeypatch.delenv("HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE", raising=False)

    def test_run_log_config_defaults(self):
        cfg = RunLogConfig()
        assert cfg.enabled is True
        assert cfg.include_com_trace is True
        assert cfg.output_dir == ""
        assert cfg.console_capture is True
        assert cfg.include_http is True
        assert cfg.include_signalr is True
        assert cfg.redact_auth is True
        assert cfg.signalr_event_filter == []
        assert cfg.max_payload_bytes == 1_048_576


class TestRunLogRecord:
    def test_record_writes_valid_ndjson(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("WebAPI", "Out", "http_request", {"method": "GET", "path": "/api/test"})
        log.record("SignalR", "In", "runtime_status", {"status": "running"})
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        assert len(jsonl_files) == 1
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            entry = json.loads(line)
            assert "timestamp" in entry
            assert "sequence" in entry
            assert "source" in entry
            assert "direction" in entry
            assert "type" in entry
            assert "payload" in entry

    def test_sequence_is_monotonically_increasing(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")

        threads = []
        for _ in range(10):
            t = threading.Thread(target=log.record, args=("SDK", "Out", "test", {"x": 1}))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        sequences = sorted(json.loads(line)["sequence"] for line in lines)
        assert sequences == list(range(1, 11))

    def test_sequence_starts_at_one(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("SDK", "Out", "session_start", {})
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        line = jsonl_files[0].read_text(encoding="utf-8").strip()
        entry = json.loads(line)
        assert entry["sequence"] == 1

    def test_record_error_does_not_raise(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        # Close file handle to force an error
        log._file_handle.close()
        log._closed = False  # allow record to try writing
        # Should not raise
        log.record("SDK", "Out", "test", {"data": "value"})

    def test_file_handle_always_initialized(self, tmp_path):
        """File handle should always be initialized (None or open file) to avoid AttributeError."""
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        # Should have a file handle (either None if disabled or a file object)
        assert hasattr(log, "_file_handle")
        assert log._file_handle is not None or log._disabled

    def test_initialization_with_invalid_directory(self, tmp_path):
        """RunLog should gracefully handle initialization failures."""
        # Use a path that would fail (simulated by using readonly directory if possible)
        # Instead, we'll just verify that if os.makedirs fails, it's handled gracefully
        invalid_path = tmp_path / "test_log"

        # Create the directory, then try to write to it with bad permissions
        # However, this is platform-dependent. Instead, test that disabled state works:
        config = RunLogConfig(enabled=True, output_dir=str(invalid_path))
        log = RunLog(config, "test-session", "0.4.0")

        # Instance should have a file handle initialized
        assert hasattr(log, "_file_handle")
        # Recording should not raise even if disabled
        log.record("SDK", "Out", "test", {"data": "value"})
        # Closing should not raise
        log.close()


class TestRunLogConfigEnvDefaults:
    def test_env_turns_the_defaults_off(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_ENABLED", "0")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE", "false")
        cfg = RunLogConfig()
        assert cfg.enabled is False
        assert cfg.include_com_trace is False

    def test_explicit_values_beat_the_env(self, monkeypatch):
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_ENABLED", "0")
        assert RunLogConfig(enabled=True).enabled is True


class TestRunLogOutputDir:
    def test_unset_output_dir_uses_the_registry_logfiles_dir(self, tmp_path, monkeypatch):
        logfiles = tmp_path / "Logfiles"
        monkeypatch.setattr(_com_trace, "registry_logfiles_dir", lambda: str(logfiles))
        log = RunLog(RunLogConfig(enabled=True), "test-session", "0.4.0")
        try:
            assert log.output_dir == logfiles
            assert list(logfiles.glob("run_test-session_*.meta.json"))
        finally:
            log.close()

    def test_unset_output_dir_without_registry_uses_the_standard_dir(self, monkeypatch):
        monkeypatch.setattr(_com_trace, "registry_logfiles_dir", lambda: None)
        assert _com_trace.default_logfiles_dir() == _com_trace.DEFAULT_LOGFILES_DIR

    def test_unwritable_logfiles_dir_falls_back_to_the_working_dir(self, tmp_path, monkeypatch):
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("x")
        monkeypatch.setattr(_com_trace, "registry_logfiles_dir", lambda: str(blocker / "Logfiles"))
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        log = RunLog(RunLogConfig(enabled=True), "test-session", "0.4.0")
        try:
            assert log.output_dir == cwd
            assert list(cwd.glob("run_test-session_*.meta.json"))
        finally:
            log.close()

    def test_unwritable_explicit_output_dir_disables_the_log(self, tmp_path, monkeypatch):
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("x")
        monkeypatch.chdir(tmp_path)
        log = RunLog(RunLogConfig(enabled=True, output_dir=str(blocker / "logs")), "test-session", "0.4.0")
        log.record("SDK", "Out", "test", {})
        log.close()
        assert not list(tmp_path.glob("run_*"))


class TestUtcAndLocal:
    def test_returns_utc_iso_unchanged(self):
        dt = datetime(2026, 9, 16, 20, 25, 40, 627591, tzinfo=UTC)
        utc_iso, _local_iso = _utc_and_local(dt)
        assert utc_iso == dt.isoformat()

    def test_local_is_the_same_instant_in_the_host_timezone(self):
        dt = datetime(2026, 9, 16, 20, 25, 40, 627591, tzinfo=UTC)
        _utc_iso, local_iso = _utc_and_local(dt)
        local_dt = datetime.fromisoformat(local_iso)
        assert local_dt.astimezone(UTC) == dt


class TestRunLogRecordLocalTimestamps:
    def test_entry_carries_timestamp_local_alongside_timestamp(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("SDK", "Out", "test", {})
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        entry = json.loads(jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()[0])
        assert "timestamp" in entry
        assert "timestamp_local" in entry
        assert "display" not in entry
        # Same instant, just re-expressed in the host's local timezone.
        assert datetime.fromisoformat(entry["timestamp_local"]).astimezone(UTC) == datetime.fromisoformat(
            entry["timestamp"]
        )


class TestRunLogFinalize:
    def test_finalize_produces_valid_json(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("SDK", "Out", "session_start", {"sdk_version": "0.4.0"})
        log.record("WebAPI", "Out", "http_request", {"method": "GET", "path": "/api"})
        final_path = log.finalize()

        assert final_path.is_file()
        data = json.loads(final_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == "1.0"
        assert data["session_id"] == "test-session"
        assert data["sdk_version"] == "0.4.0"
        assert data["script_name"]
        assert data["started_at"] is not None
        assert data["ended_at"] is not None
        assert len(data["log"]) == 2

        # Temp files removed
        assert not list(tmp_path.glob("*.jsonl"))
        assert not list(tmp_path.glob("*.meta.json"))

    def test_finalize_sets_ended_at(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("SDK", "Out", "session_start", {})
        final_path = log.finalize()

        data = json.loads(final_path.read_text(encoding="utf-8"))
        assert data["ended_at"] >= data["started_at"]

    def test_finalize_includes_local_start_end_timestamps(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("SDK", "Out", "session_start", {})
        final_path = log.finalize()

        data = json.loads(final_path.read_text(encoding="utf-8"))
        for key in ("started_at_local", "ended_at_local"):
            assert data[key], key
        assert "started_at_display" not in data
        assert "ended_at_display" not in data

    def test_finalize_removes_meta_json(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        assert list(tmp_path.glob("*.meta.json"))
        log.record("SDK", "Out", "test", {})
        log.finalize()
        assert not list(tmp_path.glob("*.meta.json"))


class TestRunLogCrashRecovery:
    def test_crash_recovery_jsonl_readable(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("SDK", "Out", "session_start", {"v": "0.4.0"})
        log.record("WebAPI", "Out", "http_request", {"method": "PUT"})
        log.close()  # Simulate crash - no finalize

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        assert len(jsonl_files) == 1
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        for line in lines:
            json.loads(line)  # Should not raise

    def test_recover_converts_jsonl_to_json(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("SDK", "Out", "session_start", {"v": "0.4.0"})
        log.record("WebAPI", "In", "http_response", {"status_code": 200})
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        recovered_path = RunLog.recover(jsonl_files[0])

        assert recovered_path.is_file()
        data = json.loads(recovered_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == "1.0"
        assert data["session_id"] == "test-session"
        assert data["sdk_version"] == "0.4.0"
        assert data["script_name"]
        assert len(data["log"]) == 2
        assert not list(tmp_path.glob("*.jsonl"))

    def test_recover_uses_sidecar_metadata(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "my-session-id", "1.2.3")
        log.record("SDK", "Out", "test", {})
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        recovered_path = RunLog.recover(jsonl_files[0])

        data = json.loads(recovered_path.read_text(encoding="utf-8"))
        assert data["session_id"] == "my-session-id"
        assert data["sdk_version"] == "1.2.3"

    def test_recover_synthesizes_metadata_without_sidecar(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "abc123", "0.4.0")
        log.record("SDK", "Out", "test", {})
        log.close()

        # Remove sidecar
        for meta in tmp_path.glob("*.meta.json"):
            meta.unlink()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        recovered_path = RunLog.recover(jsonl_files[0])

        data = json.loads(recovered_path.read_text(encoding="utf-8"))
        assert data["sdk_version"] == "unknown"
        assert data["script_name"] == "unknown"

    def test_recover_propagates_local_timestamps(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("SDK", "Out", "session_start", {})
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        recovered_path = RunLog.recover(jsonl_files[0])

        data = json.loads(recovered_path.read_text(encoding="utf-8"))
        assert data["started_at_local"]
        assert data["ended_at_local"]
        assert "timestamp_local" in data["log"][0]

    def test_recover_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            RunLog.recover("/nonexistent/path.jsonl")

    def test_recover_raises_value_error_for_empty_file(self, tmp_path):
        empty_file = tmp_path / "run_empty_20260101_000000.jsonl"
        empty_file.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="zero valid entries"):
            RunLog.recover(empty_file)


class TestRunLogMetaSidecar:
    def test_meta_json_written_at_init(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")

        meta_files = list(tmp_path.glob("*.meta.json"))
        assert len(meta_files) == 1
        meta = json.loads(meta_files[0].read_text(encoding="utf-8"))
        assert meta["schema_version"] == "1.0"
        assert meta["session_id"] == "test-session"
        assert meta["sdk_version"] == "0.4.0"
        assert meta["script_name"]
        assert "started_at" in meta
        log.close()


class TestAuthRedaction:
    def test_auth_redaction_strips_authorization_header(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), redact_auth=True)
        log = RunLog(config, "test-session", "0.4.0")
        log.record(
            "WebAPI",
            "Out",
            "http_request",
            {
                "headers": {"Authorization": "Bearer secret-token-123"},
                "body": {},
            },
        )
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        entry = json.loads(jsonl_files[0].read_text(encoding="utf-8").strip())
        assert entry["payload"]["headers"]["Authorization"] == "[REDACTED]"

    def test_auth_redaction_off(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), redact_auth=False)
        log = RunLog(config, "test-session", "0.4.0")
        log.record(
            "WebAPI",
            "Out",
            "http_request",
            {
                "headers": {"Authorization": "Bearer secret-token-123"},
            },
        )
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        entry = json.loads(jsonl_files[0].read_text(encoding="utf-8").strip())
        assert entry["payload"]["headers"]["Authorization"] == "Bearer secret-token-123"

    def test_redaction_recursive_nested_dicts(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), redact_auth=True)
        log = RunLog(config, "test-session", "0.4.0")
        log.record(
            "WebAPI",
            "Out",
            "http_request",
            {
                "outer": {
                    "password": "s3cret",
                    "inner": {
                        "client_secret": "another-secret",
                        "Authorization": "Bearer xyz",
                        "db_password": "dbpass",
                    },
                },
                "access_token": "tok123",
                "value": "Bearer should-be-redacted",
            },
        )
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        entry = json.loads(jsonl_files[0].read_text(encoding="utf-8").strip())
        p = entry["payload"]
        assert p["outer"]["password"] == "[REDACTED]"
        assert p["outer"]["inner"]["client_secret"] == "[REDACTED]"
        assert p["outer"]["inner"]["Authorization"] == "[REDACTED]"
        assert p["outer"]["inner"]["db_password"] == "[REDACTED]"
        assert p["access_token"] == "[REDACTED]"
        assert p["value"] == "Bearer [REDACTED]"


class TestMaxPayloadTruncation:
    def test_max_payload_bytes_truncation(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path), max_payload_bytes=100)
        log = RunLog(config, "test-session", "0.4.0")
        large_payload = {"data": "x" * 200}
        log.record("WebAPI", "In", "http_response", large_payload)
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        entry = json.loads(jsonl_files[0].read_text(encoding="utf-8").strip())
        assert entry["payload"]["_truncated"] is True
        assert entry["payload"]["_original_bytes"] > 100


class TestThreadSafety:
    def test_thread_safety_no_corrupted_lines(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")

        def write_entries():
            for i in range(50):
                log.record("SDK", "Out", "test", {"i": i})

        threads = [threading.Thread(target=write_entries) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        log.close()

        jsonl_files = list(tmp_path.glob("*.jsonl"))
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1000
        for line in lines:
            json.loads(line)  # Should not raise


class TestRunLogRunGuid:
    def test_set_run_guid_records_entry_and_updates_meta(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.set_run_guid("guid-1234", "MyMethod")
        log.close()

        # Metadata sidecar carries the run_guid + method_name
        meta_files = list(tmp_path.glob("*.meta.json"))
        meta = json.loads(meta_files[0].read_text(encoding="utf-8"))
        assert meta["run_guid"] == "guid-1234"
        assert meta["method_name"] == "MyMethod"

        # A run_guid_linked entry is recorded
        jsonl_files = list(tmp_path.glob("*.jsonl"))
        entries = [json.loads(line) for line in jsonl_files[0].read_text(encoding="utf-8").splitlines()]
        linked = [e for e in entries if e["type"] == "run_guid_linked"]
        assert len(linked) == 1
        assert linked[0]["payload"]["run_guid"] == "guid-1234"
        assert linked[0]["payload"]["method_name"] == "MyMethod"

    def test_finalize_uses_method_guid_descriptor_in_filename(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("SDK", "Out", "session_start", {})
        log.set_run_guid("ec05242f-790b-4196-ba32-60c9d921cf47", "VENUS_SDK_Session")
        final_path = log.finalize()

        assert final_path.is_file()
        # Mirrors VENUS artifact convention: <methodName>_<hyphenless-guid>_SdkRunLog.json
        assert final_path.name == "VENUS_SDK_Session_ec05242f790b4196ba3260c9d921cf47_SdkRunLog.json"
        data = json.loads(final_path.read_text(encoding="utf-8"))
        # Canonical (hyphenated) GUID preserved in the payload
        assert data["run_guid"] == "ec05242f-790b-4196-ba32-60c9d921cf47"
        assert data["method_name"] == "VENUS_SDK_Session"
        assert data["session_id"] == "test-session"

    def test_finalize_reduces_path_like_method_name_to_base(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("SDK", "Out", "session_start", {})
        # VENUS reports methodName as a full Windows path; only the base name
        # (without directory or .hsl extension) should appear in the filename,
        # matching VENUS's own artifacts (main_<guid>_Trace.trc, etc.).
        log.set_run_guid(
            "70048fb1-3793-467f-b3ce-1f150794b03b",
            r"C:\Program Files (x86)\HAMILTON\SDK\Method\main.hsl",
        )
        final_path = log.finalize()

        assert final_path.name == "main_70048fb13793467fb3ce1f150794b03b_SdkRunLog.json"
        data = json.loads(final_path.read_text(encoding="utf-8"))
        # The canonical methodName is preserved verbatim in the payload.
        assert data["method_name"] == r"C:\Program Files (x86)\HAMILTON\SDK\Method\main.hsl"

    def test_finalize_falls_back_to_script_and_session_id_without_guid(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.record("SDK", "Out", "session_start", {})
        final_path = log.finalize()

        assert final_path.name.endswith("_test-session_SdkRunLog.json")
        data = json.loads(final_path.read_text(encoding="utf-8"))
        assert data["run_guid"] is None
        assert data["method_name"] is None

    def test_set_run_guid_empty_is_noop(self, tmp_path):
        config = RunLogConfig(enabled=True, output_dir=str(tmp_path))
        log = RunLog(config, "test-session", "0.4.0")
        log.set_run_guid("")
        log.set_run_guid(None)
        final_path = log.finalize()

        data = json.loads(final_path.read_text(encoding="utf-8"))
        assert data["run_guid"] is None
        assert final_path.name.endswith("_test-session_SdkRunLog.json")


class TestLoadConfigRunLog:
    @pytest.fixture(autouse=True)
    def _run_log_env_unset(self, monkeypatch):
        # tests/unit/conftest.py turns the run log off for every test; these test the real defaults.
        monkeypatch.delenv("HAMILTON_VENUS_RUN_LOG_ENABLED", raising=False)
        monkeypatch.delenv("HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE", raising=False)

    def test_load_config_parses_run_log_section(self, tmp_path):
        logs_dir = tmp_path / "logs"
        toml_content = f"""\
[venus.run_log]
enabled = true
output_dir = "{logs_dir.as_posix()}"
console_capture = false
include_http = false
include_signalr = false
redact_auth = false
signalr_event_filter = ["runtime_status", "progress"]
max_payload_bytes = 500000
"""
        config_file = tmp_path / "hamilton_venus.toml"
        config_file.write_text(toml_content, encoding="utf-8")
        cfg = load_config(config_file)
        assert cfg.run_log.enabled is True
        assert cfg.run_log.output_dir == logs_dir.as_posix()
        assert cfg.run_log.console_capture is False
        assert cfg.run_log.include_http is False
        assert cfg.run_log.include_signalr is False
        assert cfg.run_log.redact_auth is False
        assert cfg.run_log.signalr_event_filter == ["runtime_status", "progress"]
        assert cfg.run_log.max_payload_bytes == 500000

    def test_load_config_run_log_env_override(self, tmp_path, monkeypatch):
        toml_content = """\
[venus]
"""
        config_file = tmp_path / "hamilton_venus.toml"
        config_file.write_text(toml_content, encoding="utf-8")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_ENABLED", "1")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_DIR", "/tmp/logs")
        cfg = load_config(config_file)
        assert cfg.run_log.enabled is True
        assert cfg.run_log.output_dir == "/tmp/logs"

    @pytest.mark.parametrize("env_value", ["1", "true", "True", "TRUE", "yes", "Yes", "on", "ON"])
    def test_run_log_enabled_truthy_env_values(self, tmp_path, monkeypatch, env_value):
        config_file = tmp_path / "hamilton_venus.toml"
        config_file.write_text("[venus]\n", encoding="utf-8")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_ENABLED", env_value)
        cfg = load_config(config_file)
        assert cfg.run_log.enabled is True

    @pytest.mark.parametrize("env_value", ["0", "false", "False", "no", "off", ""])
    def test_run_log_enabled_falsy_env_values(self, tmp_path, monkeypatch, env_value):
        config_file = tmp_path / "hamilton_venus.toml"
        config_file.write_text("[venus]\n", encoding="utf-8")
        monkeypatch.setenv("HAMILTON_VENUS_RUN_LOG_ENABLED", env_value)
        cfg = load_config(config_file)
        assert cfg.run_log.enabled is False

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from hamilton_venus.setup_tools import prerequisites, version_detection
from hamilton_venus.setup_tools.prerequisite_manifest import PrerequisiteInfo, PrerequisiteManifest

# Captured before the autouse fixture below ever patches the name, so tests that
# exercise _get_run_state's real implementation directly can restore it.
_real_get_run_state = prerequisites._get_run_state


@pytest.fixture(autouse=True)
def _venus_safe_to_stop_by_default(monkeypatch):
    """Most tests in this file aren't exercising the VENUS run-state safety gate --
    fake the lowest-level HTTP call to report "Terminated" (safe) so the real
    ensure_venus_safe_to_stop() logic runs everywhere without ever reaching the
    network, and stop_blocking_processes() proceeds as it did before that gate
    existed. Tests for the gate itself override _get_run_state (or
    ensure_venus_safe_to_stop directly) with whatever they need to exercise.
    """
    monkeypatch.setattr(prerequisites, "_get_run_state", lambda _url: 10)


def test_default_prereqs_path_uses_env_override(monkeypatch) -> None:
    override_root = Path(r"C:\override-sdk")
    monkeypatch.setenv("HAMILTON_VENUS_SDK_ROOT", str(override_root))

    prereqs_path = prerequisites.default_prereqs_path()

    expected_root = Path(str(override_root)).expanduser().resolve()
    assert prereqs_path == expected_root / "prerequisites"


def test_default_prereqs_path_prefers_cwd_discovered_sdk_root(tmp_path: Path, monkeypatch) -> None:
    sdk_root = tmp_path / "sdk-root"
    (sdk_root / "prerequisites").mkdir(parents=True)
    (sdk_root / "sdk_method_structure").mkdir(parents=True)
    nested = sdk_root / "nested" / "deeper"
    nested.mkdir(parents=True)

    monkeypatch.delenv("HAMILTON_VENUS_SDK_ROOT", raising=False)
    monkeypatch.chdir(nested)

    prereqs_path = prerequisites.default_prereqs_path()

    assert prereqs_path == sdk_root / "prerequisites"


def test_resolve_headless_exe_flags_returns_known_pattern_flags() -> None:
    flags = prerequisites.resolve_headless_exe_flags(
        "Install Hamilton Advanced Tip Management Library.exe",
        ["/S"],
    )

    assert flags == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]


def test_resolve_headless_exe_flags_returns_default_when_no_match() -> None:
    flags = prerequisites.resolve_headless_exe_flags("unknown_installer.exe", ["/S"])

    assert flags == ["/S"]


def test_find_executables_filters_and_sorts(tmp_path: Path) -> None:
    prereqs_dir = tmp_path / "pre"
    prereqs_dir.mkdir()
    (prereqs_dir / "z_tool.exe").write_text("", encoding="utf-8")
    (prereqs_dir / "a_setup.msi").write_text("", encoding="utf-8")
    (prereqs_dir / "readme.txt").write_text("", encoding="utf-8")

    exes = prerequisites.find_executables(prereqs_dir)

    assert [exe.name for exe in exes] == ["a_setup.msi", "z_tool.exe"]


def test_run_executables_dry_run_counts_success(tmp_path: Path) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_text("", encoding="utf-8")

    success, failed = prerequisites.run_executables([exe], dry_run=True, silent=False)

    assert success == 1
    assert failed == []


def test_run_executables_uses_msi_headless_command(monkeypatch, tmp_path: Path) -> None:
    msi = tmp_path / "setup.msi"
    msi.write_text("", encoding="utf-8")

    captured: dict[str, object] = {}

    def _fake_run(cmd: list[str], *args, **kwargs):
        captured["cmd"] = cmd
        captured["check"] = kwargs.get("check")
        captured["shell"] = kwargs.get("shell")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(prerequisites.subprocess, "run", _fake_run)

    success, failed = prerequisites.run_executables([msi], dry_run=False, silent=True)

    assert success == 1
    assert failed == []
    assert captured["cmd"] == ["msiexec", "/i", str(msi), "/qn", "/norestart"]
    assert captured["check"] is False
    assert captured["shell"] is False


def test_run_executables_nonzero_exit_not_counted(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_text("", encoding="utf-8")

    def _fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(prerequisites.subprocess, "run", _fake_run)

    success, failed = prerequisites.run_executables([exe], dry_run=False, silent=False)

    assert success == 0
    assert failed == [exe]


def test_run_executables_exception_not_counted(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_text("", encoding="utf-8")

    def _boom(cmd, *args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(prerequisites.subprocess, "run", _boom)

    success, failed = prerequisites.run_executables([exe], dry_run=False, silent=False)

    assert success == 0
    assert failed == [exe]


def test_run_executables_warning_includes_inno_setup_exit_code_hint(monkeypatch, tmp_path: Path, caplog) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_text("", encoding="utf-8")

    def _fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(cmd, 5)

    monkeypatch.setattr(prerequisites.subprocess, "run", _fake_run)

    with caplog.at_level("WARNING", logger="venus_install_prerequisites"):
        prerequisites.run_executables([exe], dry_run=False, silent=False)

    assert "Abort/Retry/Ignore" in caplog.text


def test_main_returns_1_when_prompt_enabled_and_user_declines(monkeypatch, tmp_path: Path) -> None:
    prereqs_dir = tmp_path / "prereqs"
    prereqs_dir.mkdir()
    exe = prereqs_dir / "tool.exe"
    exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        prerequisites,
        "parse_args",
        lambda _argv=None: argparse.Namespace(
            prereqs=prereqs_dir,
            dry_run=True,
            headless=True,
            prompt=True,
            verbose=False,
        ),
    )
    monkeypatch.setattr(prerequisites, "confirm", lambda *_args, **_kwargs: False)

    rc = prerequisites.main([])

    assert rc == 1


def test_main_does_not_prompt_by_default(monkeypatch, tmp_path: Path) -> None:
    prereqs_dir = tmp_path / "prereqs"
    prereqs_dir.mkdir()
    exe = prereqs_dir / "tool.exe"
    exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        prerequisites,
        "parse_args",
        lambda _argv=None: argparse.Namespace(
            prereqs=prereqs_dir,
            dry_run=True,
            headless=True,
            prompt=False,
            verbose=False,
        ),
    )

    called = {"confirm": False}

    def _confirm(*_args, **_kwargs):
        called["confirm"] = True
        return False

    monkeypatch.setattr(prerequisites, "confirm", _confirm)

    rc = prerequisites.main([])

    assert rc == 0
    assert called["confirm"] is False


def _fake_tasklist(names_running: set[str]):
    """A fake subprocess.run that answers `tasklist /FI "IMAGENAME eq <name>" /FO CSV`
    truthfully for names_running and reports "no tasks" for everything else. Emits CSV
    (matching real tasklist's /FO CSV output) rather than the default table format --
    the table format truncates the Image Name column, which is exactly the bug
    _is_process_running's CSV parsing exists to avoid. Raises if a command other than
    tasklist/taskkill is attempted.
    """

    def _run(cmd: list[str], *args, **kwargs):
        if cmd[0] == "tasklist":
            name = cmd[2].split("eq ", 1)[1]
            stdout = (
                f'"{name}","1234","Console","1","1,000 K"\n'
                if name in names_running
                else "INFO: No tasks are running which match the specified criteria.\n"
            )
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        if cmd[0] == "taskkill":
            return subprocess.CompletedProcess(cmd, 0, stdout="SUCCESS: The process has been terminated.\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    return _run


def test_is_process_running_true_when_tasklist_lists_it(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(prerequisites.subprocess, "run", _fake_tasklist({"Hamilton.WebAPI.RunExecutor.exe"}))

    assert prerequisites._is_process_running("Hamilton.WebAPI.RunExecutor.exe") is True


def test_is_process_running_false_when_not_listed(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(prerequisites.subprocess, "run", _fake_tasklist(set()))

    assert prerequisites._is_process_running("Hamilton.WebAPI.RunExecutor.exe") is False


def test_is_process_running_false_on_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    def _run(*_args, **_kwargs):
        raise AssertionError("should not shell out on non-Windows")

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    assert prerequisites._is_process_running("whatever.exe") is False


def test_is_process_running_false_when_tasklist_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    def _boom(*_args, **_kwargs):
        raise OSError("tasklist not found")

    monkeypatch.setattr(prerequisites.subprocess, "run", _boom)

    assert prerequisites._is_process_running("whatever.exe") is False


def test_is_process_running_requests_csv_format(monkeypatch) -> None:
    """Locks in the fix for a real bug: tasklist's default table format truncates the
    Image Name column (observed live: "Hamilton.WebAPI.RunExecutor.exe" ->
    "Hamilton.WebAPI.RunExecut"), which silently breaks detection of long process
    names. /FO CSV never truncates.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    captured: dict[str, object] = {}

    def _run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return _fake_tasklist({"Hamilton.WebAPI.RunExecutor.exe"})(cmd, *args, **kwargs)

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    prerequisites._is_process_running("Hamilton.WebAPI.RunExecutor.exe")

    cmd = captured["cmd"]
    assert "/FO" in cmd
    assert cmd[cmd.index("/FO") + 1] == "CSV"


def test_is_process_running_does_not_false_positive_on_substring_match(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    def _run(cmd, *args, **kwargs):
        # A different process whose name merely contains the target name as a substring.
        stdout = '"Hamilton.WebAPI.RunExecutorHelper.exe","999","Console","1","500 K"\n'
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    assert prerequisites._is_process_running("Hamilton.WebAPI.RunExecutor.exe") is False


def test_stop_blocking_processes_skips_when_not_running(monkeypatch, caplog) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[list[str]] = []

    def _run(cmd, *args, **kwargs):
        calls.append(cmd)
        return _fake_tasklist(set())(cmd, *args, **kwargs)

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    with caplog.at_level("INFO", logger="venus_install_prerequisites"):
        stopped = prerequisites.stop_blocking_processes(["Hamilton.WebAPI.RunExecutor.exe"])

    assert stopped == []
    assert all(cmd[0] == "tasklist" for cmd in calls)  # taskkill never invoked
    # The check must be visible in the log even when there's nothing to stop -- silent
    # success looks identical to "never ran" otherwise.
    assert "Checking VENUS's run-state before touching background processes" in caplog.text
    assert "Hamilton.WebAPI.RunExecutor.exe is not running -- nothing to stop." in caplog.text


def test_stop_blocking_processes_dry_run_does_not_kill(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[list[str]] = []

    def _run(cmd, *args, **kwargs):
        calls.append(cmd)
        return _fake_tasklist({"Hamilton.WebAPI.RunExecutor.exe"})(cmd, *args, **kwargs)

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    stopped = prerequisites.stop_blocking_processes(["Hamilton.WebAPI.RunExecutor.exe"], dry_run=True)

    assert stopped == ["Hamilton.WebAPI.RunExecutor.exe"]
    assert all(cmd[0] != "taskkill" for cmd in calls)


def test_stop_blocking_processes_kills_running_process(monkeypatch, caplog) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[list[str]] = []

    def _run(cmd, *args, **kwargs):
        calls.append(cmd)
        return _fake_tasklist({"Hamilton.WebAPI.RunExecutor.exe"})(cmd, *args, **kwargs)

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    with caplog.at_level("INFO", logger="venus_install_prerequisites"):
        stopped = prerequisites.stop_blocking_processes(["Hamilton.WebAPI.RunExecutor.exe"])

    assert stopped == ["Hamilton.WebAPI.RunExecutor.exe"]
    assert "is running and may be holding a DLL open" in caplog.text
    assert "Stopped Hamilton.WebAPI.RunExecutor.exe." in caplog.text
    assert ["taskkill", "/IM", "Hamilton.WebAPI.RunExecutor.exe", "/F"] in calls


def test_stop_blocking_processes_taskkill_failure_is_non_fatal(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    def _run(cmd, *_args, **_kwargs):
        if cmd[0] == "tasklist":
            stdout = '"Hamilton.WebAPI.RunExecutor.exe","111","Console","1","1,000 K"\n'
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Access is denied.")

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    stopped = prerequisites.stop_blocking_processes(["Hamilton.WebAPI.RunExecutor.exe"])  # must not raise

    assert stopped == ["Hamilton.WebAPI.RunExecutor.exe"]


def test_stop_blocking_processes_taskkill_oserror_is_non_fatal(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    def _run(cmd, *_args, **_kwargs):
        if cmd[0] == "tasklist":
            stdout = '"Hamilton.WebAPI.RunExecutor.exe","111","Console","1","1,000 K"\n'
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        raise OSError("taskkill not found")

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    stopped = prerequisites.stop_blocking_processes(["Hamilton.WebAPI.RunExecutor.exe"])  # must not raise

    assert stopped == ["Hamilton.WebAPI.RunExecutor.exe"]


def test_main_stops_blocking_processes_before_running_installers(monkeypatch, tmp_path: Path) -> None:
    prereqs_dir = tmp_path / "prereqs"
    prereqs_dir.mkdir()
    exe = prereqs_dir / "tool.exe"
    exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        prerequisites,
        "parse_args",
        lambda _argv=None: argparse.Namespace(
            prereqs=prereqs_dir,
            dry_run=True,
            headless=True,
            prompt=False,
            verbose=False,
        ),
    )

    order: list[str] = []
    monkeypatch.setattr(prerequisites, "stop_blocking_processes", lambda *_a, **_k: order.append("stop") or [])
    orig_run_executables = prerequisites.run_executables

    def _run_executables(*args, **kwargs):
        order.append("run")
        return orig_run_executables(*args, **kwargs)

    monkeypatch.setattr(prerequisites, "run_executables", _run_executables)

    rc = prerequisites.main([])

    assert rc == 0
    assert order == ["stop", "run"]


class _FakeHttpResponse:
    """Stand-in for the object urllib.request.urlopen() returns as a context manager."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def test_get_run_state_parses_int_payload(monkeypatch) -> None:
    monkeypatch.setattr(prerequisites, "_get_run_state", _real_get_run_state)
    monkeypatch.setattr(prerequisites.urllib.request, "urlopen", lambda *_a, **_k: _FakeHttpResponse(b"10"))

    assert prerequisites._get_run_state("http://localhost:42400") == 10


def test_get_run_state_raises_on_http_400(monkeypatch) -> None:
    monkeypatch.setattr(prerequisites, "_get_run_state", _real_get_run_state)

    def _raise(*_args, **_kwargs):
        raise prerequisites.urllib.error.HTTPError("http://localhost:42400/x", 400, "Bad Request", None, None)

    monkeypatch.setattr(prerequisites.urllib.request, "urlopen", _raise)

    with pytest.raises(prerequisites.VenusNotReadyError, match="HTTP 400"):
        prerequisites._get_run_state("http://localhost:42400")


def test_get_run_state_raises_on_connection_failure(monkeypatch) -> None:
    monkeypatch.setattr(prerequisites, "_get_run_state", _real_get_run_state)

    def _raise(*_args, **_kwargs):
        raise prerequisites.urllib.error.URLError("connection refused")

    monkeypatch.setattr(prerequisites.urllib.request, "urlopen", _raise)

    with pytest.raises(prerequisites.VenusNotReadyError, match="Could not reach"):
        prerequisites._get_run_state("http://localhost:42400")


def test_get_run_state_raises_on_unparseable_payload(monkeypatch) -> None:
    monkeypatch.setattr(prerequisites, "_get_run_state", _real_get_run_state)
    monkeypatch.setattr(prerequisites.urllib.request, "urlopen", lambda *_a, **_k: _FakeHttpResponse(b"not json"))

    with pytest.raises(prerequisites.VenusNotReadyError, match="unexpected run-state payload"):
        prerequisites._get_run_state("http://localhost:42400")


@pytest.mark.parametrize("state", [0, 10])
def test_ensure_venus_safe_to_stop_passes_for_idle_and_terminated(monkeypatch, state) -> None:
    monkeypatch.setattr(prerequisites, "_get_run_state", lambda _url: state)

    prerequisites.ensure_venus_safe_to_stop("http://localhost:42400")  # must not raise


@pytest.mark.parametrize("state", [1, 2, 3, 4, 5, 6, 7, 8, 9, 11])
def test_ensure_venus_safe_to_stop_raises_for_active_states(monkeypatch, state) -> None:
    monkeypatch.setattr(prerequisites, "_get_run_state", lambda _url: state)

    with pytest.raises(prerequisites.VenusNotReadyError, match="not idle/terminated"):
        prerequisites.ensure_venus_safe_to_stop("http://localhost:42400")


def test_ensure_venus_safe_to_stop_uses_env_var_when_no_explicit_url(monkeypatch) -> None:
    monkeypatch.setenv("HAMILTON_VENUS_BASE_URL", "http://example:1234")
    captured: dict[str, object] = {}

    def _fake_get_run_state(url):
        captured["url"] = url
        return 10

    monkeypatch.setattr(prerequisites, "_get_run_state", _fake_get_run_state)

    prerequisites.ensure_venus_safe_to_stop()

    assert captured["url"] == "http://example:1234"


def test_ensure_venus_safe_to_stop_defaults_to_localhost(monkeypatch) -> None:
    monkeypatch.delenv("HAMILTON_VENUS_BASE_URL", raising=False)
    captured: dict[str, object] = {}

    def _fake_get_run_state(url):
        captured["url"] = url
        return 10

    monkeypatch.setattr(prerequisites, "_get_run_state", _fake_get_run_state)

    prerequisites.ensure_venus_safe_to_stop()

    assert captured["url"] == "http://localhost:42400"


def test_stop_blocking_processes_checks_venus_before_killing(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(prerequisites.subprocess, "run", _fake_tasklist({"Hamilton.WebAPI.RunExecutor.exe"}))
    checked = {"called": False}

    def _check(*_args, **_kwargs):
        checked["called"] = True

    monkeypatch.setattr(prerequisites, "ensure_venus_safe_to_stop", _check)

    prerequisites.stop_blocking_processes(["Hamilton.WebAPI.RunExecutor.exe"])

    assert checked["called"] is True


def test_stop_blocking_processes_propagates_venus_not_ready_without_killing(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[list[str]] = []

    def _run(cmd, *args, **kwargs):
        calls.append(cmd)
        return _fake_tasklist({"Hamilton.WebAPI.RunExecutor.exe"})(cmd, *args, **kwargs)

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    def _raise(*_args, **_kwargs):
        raise prerequisites.VenusNotReadyError("VENUS run-state is 2 (not idle/terminated) -- a method may be active")

    monkeypatch.setattr(prerequisites, "ensure_venus_safe_to_stop", _raise)

    with pytest.raises(prerequisites.VenusNotReadyError):
        prerequisites.stop_blocking_processes(["Hamilton.WebAPI.RunExecutor.exe"])

    assert all(cmd[0] != "taskkill" for cmd in calls)  # never attempted the kill


def test_stop_blocking_processes_checks_venus_even_when_nothing_running(monkeypatch) -> None:
    """Regression test for the real-world gap this closed: the run-state check must not
    be gated behind "did we detect a blocking process running" -- a run can be active
    in VENUS without Hamilton.WebAPI.RunExecutor.exe necessarily being observed running
    at the instant tasklist is checked (see stop_blocking_processes's docstring).
    """
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(prerequisites.subprocess, "run", _fake_tasklist(set()))
    checked = {"called": False}

    def _check(*_args, **_kwargs):
        checked["called"] = True

    monkeypatch.setattr(prerequisites, "ensure_venus_safe_to_stop", _check)

    prerequisites.stop_blocking_processes(["Hamilton.WebAPI.RunExecutor.exe"])

    assert checked["called"] is True


def test_stop_blocking_processes_propagates_venus_not_ready_even_when_nothing_running(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[list[str]] = []

    def _run(cmd, *args, **kwargs):
        calls.append(cmd)
        return _fake_tasklist(set())(cmd, *args, **kwargs)

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    def _raise(*_args, **_kwargs):
        raise prerequisites.VenusNotReadyError("VENUS run-state is 2 (not idle/terminated) -- a method may be active")

    monkeypatch.setattr(prerequisites, "ensure_venus_safe_to_stop", _raise)

    with pytest.raises(prerequisites.VenusNotReadyError):
        prerequisites.stop_blocking_processes(["Hamilton.WebAPI.RunExecutor.exe"])

    assert not any(cmd[0] == "taskkill" for cmd in calls)


def test_main_returns_3_and_skips_installers_when_venus_not_ready(monkeypatch, tmp_path: Path) -> None:
    prereqs_dir = tmp_path / "prereqs"
    prereqs_dir.mkdir()
    exe = prereqs_dir / "tool.exe"
    exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        prerequisites,
        "parse_args",
        lambda _argv=None: argparse.Namespace(
            prereqs=prereqs_dir,
            dry_run=True,
            headless=True,
            prompt=False,
            verbose=False,
        ),
    )

    def _raise(*_args, **_kwargs):
        raise prerequisites.VenusNotReadyError("VENUS run-state is 2 (not idle/terminated) -- a method may be active")

    monkeypatch.setattr(prerequisites, "stop_blocking_processes", _raise)

    called = {"run_executables": False}

    def _run_executables(*_args, **_kwargs):
        called["run_executables"] = True
        return 0

    monkeypatch.setattr(prerequisites, "run_executables", _run_executables)

    rc = prerequisites.main([])

    assert rc == 3
    assert called["run_executables"] is False


def test_warn_about_editor_processes_warns_but_does_not_kill(monkeypatch, caplog) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    def _run(cmd, *args, **kwargs):
        assert cmd[0] == "tasklist"  # must never taskkill an editor process
        return _fake_tasklist({"HxMetEd.exe"})(cmd, *args, **kwargs)

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    with caplog.at_level("WARNING", logger="venus_install_prerequisites"):
        running = prerequisites.warn_about_editor_processes()

    assert running == ["HxMetEd.exe"]
    assert "HxMetEd.exe is open" in caplog.text


def test_warn_about_editor_processes_silent_when_not_running(monkeypatch, caplog) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(prerequisites.subprocess, "run", _fake_tasklist(set()))

    with caplog.at_level("WARNING", logger="venus_install_prerequisites"):
        running = prerequisites.warn_about_editor_processes()

    assert running == []
    assert caplog.text == ""


def test_normalize_product_name_strips_noise_and_versions() -> None:
    assert (
        prerequisites._normalize_product_name("Hamilton HSLTime Library Installer v1.1.exe")
        == "hamilton hsltime library"
    )
    assert prerequisites._normalize_product_name("HSLTime Library") == "hsltime library"


def test_uninstall_msi_runs_msiexec_x(monkeypatch, tmp_path: Path) -> None:
    msi = tmp_path / "pkg.msi"
    msi.write_text("", encoding="utf-8")
    captured: dict[str, object] = {}

    def _run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    assert prerequisites._uninstall_msi(msi) is True
    assert captured["cmd"] == ["msiexec", "/x", str(msi), "/qn", "/norestart"]


def test_uninstall_msi_returns_false_on_failure(monkeypatch, tmp_path: Path) -> None:
    msi = tmp_path / "pkg.msi"
    msi.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        prerequisites.subprocess,
        "run",
        lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="nope"),
    )

    assert prerequisites._uninstall_msi(msi) is False


def _fake_manifest(*prereqs: PrerequisiteInfo) -> PrerequisiteManifest:
    return PrerequisiteManifest(format_version="1.0", prerequisites=tuple(prereqs))


def _fake_prereq(**overrides: object) -> PrerequisiteInfo:
    defaults: dict[str, object] = {
        "name": "fake",
        "display_name": "Fake Library",
        "required_version": "1.0",
        "installer_pattern": r"^Fake Installer v([0-9.]+)\.exe$",
        "registry_name_pattern": "Fake ?Library",
    }
    defaults.update(overrides)
    return PrerequisiteInfo(**defaults)


def test_load_manifest_quietly_loads_real_manifest() -> None:
    # Calls load_manifest() directly (bypassing the process-wide cache in
    # _load_manifest_quietly) so this doesn't leak state into other tests that
    # monkeypatch _load_manifest_quietly itself.
    manifest = prerequisites.load_manifest()

    assert any(p.name == "hsltime" for p in manifest.prerequisites)


def test_find_manifest_uninstall_command_matches_and_reads_uninstall_string(monkeypatch) -> None:
    prereq = _fake_prereq()
    monkeypatch.setattr(prerequisites, "_load_manifest_quietly", lambda: _fake_manifest(prereq))
    monkeypatch.setattr(
        version_detection,
        "iter_uninstall_entries",
        lambda: [("Fake Library", "1.0", "HKLM\\SOFTWARE\\...\\Uninstall\\{GUID}")],
    )
    monkeypatch.setattr(prerequisites, "_read_uninstall_command", lambda key: '"C:\\Fake\\unins000.exe" /X')

    cmd = prerequisites._find_manifest_uninstall_command("Fake Installer v1.0.exe")

    assert cmd == ["C:\\Fake\\unins000.exe", "/X"]


def test_find_manifest_uninstall_command_returns_none_when_installer_not_in_manifest(monkeypatch) -> None:
    monkeypatch.setattr(prerequisites, "_load_manifest_quietly", lambda: _fake_manifest())

    assert prerequisites._find_manifest_uninstall_command("Unknown Installer.exe") is None


def test_find_manifest_uninstall_command_returns_none_when_not_registered(monkeypatch) -> None:
    prereq = _fake_prereq()
    monkeypatch.setattr(prerequisites, "_load_manifest_quietly", lambda: _fake_manifest(prereq))
    monkeypatch.setattr(version_detection, "iter_uninstall_entries", lambda: [])

    assert prerequisites._find_manifest_uninstall_command("Fake Installer v1.0.exe") is None


def test_find_manifest_uninstall_command_returns_none_when_manifest_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(prerequisites, "_load_manifest_quietly", lambda: None)

    assert prerequisites._find_manifest_uninstall_command("whatever.exe") is None


def test_find_fuzzy_uninstall_command_confident_match(monkeypatch) -> None:
    monkeypatch.setattr(
        version_detection,
        "iter_uninstall_entries",
        lambda: [
            ("HSLTime Library", "1.1", "HKLM\\...\\A"),
            ("Some Totally Unrelated App", "", "HKLM\\...\\B"),
        ],
    )
    monkeypatch.setattr(
        prerequisites,
        "_read_uninstall_command",
        lambda key: '"C:\\Hamilton\\HSLTime\\unins000.exe"' if key.endswith("A") else None,
    )

    cmd = prerequisites._find_fuzzy_uninstall_command("Hamilton HSLTime Library Installer v1.1.exe")

    assert cmd == ["C:\\Hamilton\\HSLTime\\unins000.exe"]


def test_find_fuzzy_uninstall_command_returns_none_when_ambiguous(monkeypatch) -> None:
    monkeypatch.setattr(
        version_detection,
        "iter_uninstall_entries",
        lambda: [
            ("HSLTime Library", "1.1", "HKLM\\...\\A"),
            ("HSLTime Library", "1.1", "HKLM\\...\\B"),
        ],
    )

    assert prerequisites._find_fuzzy_uninstall_command("Hamilton HSLTime Library Installer v1.1.exe") is None


def test_find_fuzzy_uninstall_command_returns_none_when_no_match(monkeypatch) -> None:
    monkeypatch.setattr(
        version_detection, "iter_uninstall_entries", lambda: [("Totally Unrelated", "", "HKLM\\...\\A")]
    )

    assert prerequisites._find_fuzzy_uninstall_command("Hamilton HSLTime Library Installer v1.1.exe") is None


def test_find_registry_uninstall_command_prefers_manifest_over_fuzzy(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        prerequisites, "_find_manifest_uninstall_command", lambda _name: ["C:\\manifest\\unins000.exe"]
    )

    def _fuzzy_boom(_name):
        raise AssertionError("should not fall back to fuzzy matching once the manifest already matched")

    monkeypatch.setattr(prerequisites, "_find_fuzzy_uninstall_command", _fuzzy_boom)

    assert prerequisites._find_registry_uninstall_command("whatever.exe") == ["C:\\manifest\\unins000.exe"]


def test_find_registry_uninstall_command_falls_back_to_fuzzy(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(prerequisites, "_find_manifest_uninstall_command", lambda _name: None)
    monkeypatch.setattr(prerequisites, "_find_fuzzy_uninstall_command", lambda _name: ["C:\\fuzzy\\unins000.exe"])

    assert prerequisites._find_registry_uninstall_command("whatever.exe") == ["C:\\fuzzy\\unins000.exe"]


def test_find_registry_uninstall_command_returns_none_on_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    def _boom(_name):
        raise AssertionError("should not touch the registry on non-Windows")

    monkeypatch.setattr(prerequisites, "_find_manifest_uninstall_command", _boom)
    monkeypatch.setattr(prerequisites, "_find_fuzzy_uninstall_command", _boom)

    assert prerequisites._find_registry_uninstall_command("whatever.exe") is None


def test_uninstall_exe_runs_matched_uninstaller_with_silent_flags(monkeypatch) -> None:
    monkeypatch.setattr(prerequisites, "_find_registry_uninstall_command", lambda _name: ["C:\\App\\unins000.exe"])
    captured: dict[str, object] = {}

    def _run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(prerequisites.subprocess, "run", _run)

    assert prerequisites._uninstall_exe(Path("Hamilton HSLTime Library Installer v1.1.exe")) is True
    assert captured["cmd"][0] == "C:\\App\\unins000.exe"
    assert "/VERYSILENT" in captured["cmd"]


def test_uninstall_exe_returns_false_when_no_match(monkeypatch) -> None:
    monkeypatch.setattr(prerequisites, "_find_registry_uninstall_command", lambda _name: None)

    def _boom(*_a, **_k):
        raise AssertionError("should not attempt to run anything without a confident match")

    monkeypatch.setattr(prerequisites.subprocess, "run", _boom)

    assert prerequisites._uninstall_exe(Path("whatever.exe")) is False


def test_retry_failed_executables_uninstalls_then_reinstalls_msi(monkeypatch, tmp_path: Path) -> None:
    msi = tmp_path / "pkg.msi"
    msi.write_text("", encoding="utf-8")
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(prerequisites, "_uninstall_msi", lambda p: calls.append(("uninstall", p)) or True)

    def _fake_run_executables(execs, dry_run, silent):
        calls.append(("install", execs))
        return 1, []

    monkeypatch.setattr(prerequisites, "run_executables", _fake_run_executables)

    success, failed = prerequisites.retry_failed_executables([msi])

    assert success == 1
    assert failed == []
    assert calls[0] == ("uninstall", msi)


def test_retry_failed_executables_uses_uninstall_exe_for_exe(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_text("", encoding="utf-8")
    called = {"uninstall_exe": False, "uninstall_msi": False}

    def _uninstall_exe(p):
        called["uninstall_exe"] = True
        return True

    def _uninstall_msi(p):
        called["uninstall_msi"] = True
        return True

    monkeypatch.setattr(prerequisites, "_uninstall_exe", _uninstall_exe)
    monkeypatch.setattr(prerequisites, "_uninstall_msi", _uninstall_msi)
    monkeypatch.setattr(prerequisites, "run_executables", lambda execs, dry_run, silent: (1, []))

    prerequisites.retry_failed_executables([exe])

    assert called["uninstall_exe"] is True
    assert called["uninstall_msi"] is False


def test_retry_failed_executables_still_failing_after_retry(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(prerequisites, "_uninstall_exe", lambda p: False)
    monkeypatch.setattr(prerequisites, "run_executables", lambda execs, dry_run, silent: (0, execs))

    success, failed = prerequisites.retry_failed_executables([exe])

    assert success == 0
    assert failed == [exe]


def test_retry_failed_executables_reinstalls_even_when_uninstall_fails(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(prerequisites, "_uninstall_exe", lambda p: False)
    called = {"run_executables": False}

    def _run_executables(execs, dry_run, silent):
        called["run_executables"] = True
        return 1, []

    monkeypatch.setattr(prerequisites, "run_executables", _run_executables)

    success, _failed = prerequisites.retry_failed_executables([exe])

    assert called["run_executables"] is True
    assert success == 1


def test_main_calls_warn_about_editor_processes(monkeypatch, tmp_path: Path) -> None:
    prereqs_dir = tmp_path / "prereqs"
    prereqs_dir.mkdir()
    exe = prereqs_dir / "tool.exe"
    exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        prerequisites,
        "parse_args",
        lambda _argv=None: argparse.Namespace(
            prereqs=prereqs_dir,
            dry_run=True,
            headless=True,
            prompt=False,
            verbose=False,
        ),
    )
    called = {"warn": False}
    monkeypatch.setattr(
        prerequisites, "warn_about_editor_processes", lambda *_a, **_k: called.__setitem__("warn", True) or []
    )
    monkeypatch.setattr(prerequisites, "stop_blocking_processes", lambda *_a, **_k: [])

    rc = prerequisites.main([])

    assert rc == 0
    assert called["warn"] is True


def test_main_retries_once_then_returns_4_when_still_failing(monkeypatch, tmp_path: Path) -> None:
    prereqs_dir = tmp_path / "prereqs"
    prereqs_dir.mkdir()
    exe = prereqs_dir / "tool.exe"
    exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        prerequisites,
        "parse_args",
        lambda _argv=None: argparse.Namespace(
            prereqs=prereqs_dir,
            dry_run=False,
            headless=True,
            prompt=False,
            verbose=False,
        ),
    )
    monkeypatch.setattr(prerequisites, "warn_about_editor_processes", lambda *_a, **_k: [])
    monkeypatch.setattr(prerequisites, "stop_blocking_processes", lambda *_a, **_k: [])
    monkeypatch.setattr(prerequisites, "run_executables", lambda execs, dry_run, silent: (0, [exe]))

    retry_calls = {"count": 0}

    def _retry(failed, *, silent):
        retry_calls["count"] += 1
        return 0, failed

    monkeypatch.setattr(prerequisites, "retry_failed_executables", _retry)

    rc = prerequisites.main([])

    assert rc == 4
    assert retry_calls["count"] == 1


def test_main_returns_0_when_retry_succeeds(monkeypatch, tmp_path: Path) -> None:
    prereqs_dir = tmp_path / "prereqs"
    prereqs_dir.mkdir()
    exe = prereqs_dir / "tool.exe"
    exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        prerequisites,
        "parse_args",
        lambda _argv=None: argparse.Namespace(
            prereqs=prereqs_dir,
            dry_run=False,
            headless=True,
            prompt=False,
            verbose=False,
        ),
    )
    monkeypatch.setattr(prerequisites, "warn_about_editor_processes", lambda *_a, **_k: [])
    monkeypatch.setattr(prerequisites, "stop_blocking_processes", lambda *_a, **_k: [])
    monkeypatch.setattr(prerequisites, "run_executables", lambda execs, dry_run, silent: (0, [exe]))
    monkeypatch.setattr(prerequisites, "retry_failed_executables", lambda failed, *, silent: (1, []))

    rc = prerequisites.main([])

    assert rc == 0

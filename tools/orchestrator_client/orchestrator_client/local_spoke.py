"""A spoke on this same PC, for an orchestrator that runs on the instrument PC itself.

Cards are separate processes, so something has to keep the instrument session alive between
them -- that is the spoke. When the orchestrator and the instrument share a PC, that spoke
never needs to be on the network: these helpers run it on 127.0.0.1 only (nothing else on
the network can reach it, so no token, firewall rule or HTTPS is needed) and start it on
demand, so nobody has to manage it by hand.

    from orchestrator_client import Instrument, InstrumentType

    instrument = Instrument.local()        # starts the local spoke if it isn't running yet
    instrument.start(simulate=True, instrument_type=InstrumentType.VANTAGE, load_previous_deck=True)

    local_spoke_status()                   # running? pid, url, uptime, started by us?
    local_spoke_health()                   # process, /ping, MCP round trip, VENUS, session
    stop_local_spoke()                     # closes any open session first, then stops it

A spoke started here runs detached: it outlives the card that started it, logs to
%LOCALAPPDATA%\\Hamilton\\mcp_local_spoke\\spoke-<port>.log, and is remembered in a small
state file next to that log. A spoke someone started another way (e.g. Start MCP Spoke.bat)
on the same port is used as-is, and can be checked and stopped the same way.

Stdlib-only, like the rest of orchestrator_client.
"""

from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import orchestrator_session
from .orchestrator_session import OrchestratorCallError

DEFAULT_PORT = 8000
LOCAL_HOST = "127.0.0.1"
SPOKE_EXE_ENV = "HAMILTON_MCP_SPOKE_EXE"
_DEFAULT_EXE = Path(r"C:\Program Files (x86)\Hamilton\Python\.venv\Scripts\hamilton-venus-mcp.exe")
_SERVICE = "hamilton-venus-mcp"

# Windows process-creation flags. CREATE_NO_WINDOW gives the spoke a console of its own that
# is never shown -- not tied to the card's console, so the spoke keeps running after the card
# exits, and the processes it starts (hamilton-venus-mcp.exe is a launcher that starts
# python.exe) share that hidden console. Not DETACHED_PROCESS: Windows ignores
# CREATE_NO_WINDOW alongside it, and a console-less launcher's python.exe then gets a new,
# visible, empty console window. Own process group: a Ctrl+C in the card's window can't reach it.
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000


def _hidden_startupinfo() -> Any:
    """Also ask for any window the spoke opens at startup to start hidden (belt and braces)."""
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0  # SW_HIDE
    return info


def local_url(port: int = DEFAULT_PORT) -> str:
    return f"http://{LOCAL_HOST}:{port}/mcp"


def state_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Hamilton" / "mcp_local_spoke"


def _state_file(port: int) -> Path:
    return state_dir() / f"spoke-{port}.json"


def _log_file(port: int) -> Path:
    return state_dir() / f"spoke-{port}.log"


def _lock_file(port: int) -> Path:
    return state_dir() / f"spoke-{port}.lock"


# -- finding the spoke ------------------------------------------------------------------------


def spoke_command(exe: str | os.PathLike[str] | list[str] | None = None) -> list[str]:
    """The command that runs a spoke: *exe* if given (a path, or a full command list), else
    HAMILTON_MCP_SPOKE_EXE, else the hamilton-venus-mcp next to this Python (same venv), else
    one on PATH, else the installer's default location, else ``python -m hamilton_venus_mcp``
    when that package is importable here."""
    if isinstance(exe, list):
        return list(exe)
    for candidate in (exe, os.environ.get(SPOKE_EXE_ENV, "").strip() or None):
        if candidate:
            return [str(candidate)]
    # The spoke installed alongside this Python (same venv) first, so a client running in a
    # given install starts that install's spoke, not another copy found on PATH.
    beside_python = Path(sys.executable).with_name("hamilton-venus-mcp.exe" if os.name == "nt" else "hamilton-venus-mcp")
    if beside_python.is_file():
        return [str(beside_python)]
    on_path = shutil.which("hamilton-venus-mcp")
    if on_path:
        return [on_path]
    if _DEFAULT_EXE.is_file():
        return [str(_DEFAULT_EXE)]
    if importlib.util.find_spec("hamilton_venus_mcp") is not None:
        return [sys.executable, "-m", "hamilton_venus_mcp"]
    raise OrchestratorCallError(
        "Could not find the spoke (hamilton-venus-mcp). Install the MCP server with the SDK installer, "
        f"or set {SPOKE_EXE_ENV} to its .exe."
    )


# -- probing ----------------------------------------------------------------------------------


def _port_open(port: int, timeout_s: float = 0.5) -> bool:
    """Is anything listening on 127.0.0.1:*port*? A plain connect with a short timeout: on
    Windows a refused loopback connect is retried for ~2 s before failing, while a listening
    port completes the handshake in the kernel at once -- so this answers "no" fast."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout_s)
        return probe.connect_ex((LOCAL_HOST, port)) == 0


def _ping(port: int, timeout_s: float = 2.0) -> dict[str, Any] | None:
    """The spoke's /ping answer, or None if nothing answers on the port."""
    if not _port_open(port):
        return None
    try:
        with urllib.request.urlopen(f"http://{LOCAL_HOST}:{port}/ping", timeout=timeout_s) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    # Never os.kill on Windows: any signal but CTRL_* terminates the process there.
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_listening_on(port: int) -> int | None:
    """The PID listening on *port* (any address), from netstat -- for a spoke this module did
    not start itself (e.g. Start MCP Spoke.bat)."""
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[1].rsplit(":", 1)[-1] == str(port) and parts[4].isdigit():
                return int(parts[4])
    return None


def _read_state(port: int) -> dict[str, Any] | None:
    try:
        return json.loads(_state_file(port).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _log_tail(port: int, lines: int = 20) -> list[str]:
    try:
        return _log_file(port).read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


# -- status / start / stop / health -----------------------------------------------------------


def local_spoke_status(port: int = DEFAULT_PORT) -> dict[str, Any]:
    """Whether a spoke is running on this PC's *port*, without starting one.

    Returns running, url, pid, name, auth_required, started_by_client (True if
    Instrument.local() / start_local_spoke() started it), started_at, uptime_s and log_file.
    "running" is False when something else (not a spoke) holds the port -- see "detail".
    """
    ping = _ping(port)
    state = _read_state(port)
    ours = state is not None and _pid_alive(state.get("pid")) and ping is not None
    pid = state.get("pid") if ours else (_pid_listening_on(port) if ping is not None else None)
    status: dict[str, Any] = {
        "running": ping is not None and ping.get("service") == _SERVICE,
        "url": local_url(port),
        "port": port,
        "pid": pid,
        "name": (ping or {}).get("name"),
        "auth_required": (ping or {}).get("auth_required"),
        "started_by_client": ours,
        "started_at": state.get("started_at") if ours else None,
        "uptime_s": round(time.time() - state["started_at"], 1) if ours and state.get("started_at") else None,
        "log_file": str(_log_file(port)) if ours or (state and state.get("log")) else None,
    }
    if ping is not None and ping.get("service") != _SERVICE:
        status["detail"] = f"Port {port} is answered by something that is not a spoke ({ping})."
    return status


def start_local_spoke(
    port: int = DEFAULT_PORT,
    *,
    exe: str | os.PathLike[str] | list[str] | None = None,
    token: str | None = None,
    env: dict[str, str] | None = None,
    startup_timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Make sure a spoke answers on 127.0.0.1:*port*, starting one in the background if not.
    Returns local_spoke_status(). Safe to call from every card: an already-running spoke is
    left alone, and two cards starting at once start only one spoke between them.

    Args:
        exe: The spoke to run (see spoke_command); default: found automatically.
        token: Start it with HAMILTON_MCP_AUTH_TOKEN (not needed on 127.0.0.1).
        env: Extra environment variables for the spoke (e.g. HAMILTON_MCP_OPERATOR_TOKEN).
        startup_timeout_s: How long to wait for it to answer.
    """
    status = local_spoke_status(port)
    if status["running"]:
        return status
    if status.get("detail"):
        raise OrchestratorCallError(status["detail"])

    state_dir().mkdir(parents=True, exist_ok=True)
    if not _take_lock(port, startup_timeout_s):
        # Another card is starting it right now: just wait for it to answer.
        return _wait_until_running(port, startup_timeout_s, process=None)
    try:
        if _ping(port) is not None:  # started by someone else while we took the lock
            return _wait_until_running(port, startup_timeout_s, process=None)
        command = spoke_command(exe)
        spoke_env = {**os.environ, **(env or {})}
        spoke_env.update(
            {"HAMILTON_MCP_TRANSPORT": "streamable-http", "HAMILTON_MCP_HOST": LOCAL_HOST, "HAMILTON_MCP_PORT": str(port)}
        )
        if token:
            spoke_env["HAMILTON_MCP_AUTH_TOKEN"] = token
        log = open(_log_file(port), "ab")  # noqa: SIM115 - handed to the child process
        try:
            flags = _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen(
                command,
                env=spoke_env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                startupinfo=_hidden_startupinfo(),
                start_new_session=os.name != "nt",
                close_fds=True,
            )
        finally:
            log.close()
        _state_file(port).write_text(
            json.dumps(
                {"pid": process.pid, "port": port, "command": command, "started_at": time.time(), "log": str(_log_file(port))}
            ),
            encoding="utf-8",
        )
        return _wait_until_running(port, startup_timeout_s, process=process)
    finally:
        _release_lock(port)


def _wait_until_running(port: int, timeout_s: float, process: subprocess.Popen[bytes] | None) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _ping(port, timeout_s=1.0) is not None:
            return local_spoke_status(port)
        if process is not None and process.poll() is not None:
            tail = "\n".join(_log_tail(port))
            raise OrchestratorCallError(f"The local spoke exited during startup (code {process.returncode}):\n{tail}")
        time.sleep(0.25)
    raise OrchestratorCallError(
        f"The local spoke did not answer on port {port} within {timeout_s:g} s. See {_log_file(port)}."
    )


def _take_lock(port: int, stale_after_s: float) -> bool:
    lock = _lock_file(port)
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > stale_after_s:
            lock.unlink(missing_ok=True)  # left behind by a card that died mid-start
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock(port: int) -> None:
    _lock_file(port).unlink(missing_ok=True)


def stop_local_spoke(
    port: int = DEFAULT_PORT,
    *,
    close_session: bool = True,
    force: bool = False,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Stop the spoke on this PC's *port*.

    An open session is closed first (close_session=True, the default), which ends the VENUS
    method cleanly and turns the status light off -- stopping the process under an open
    session would leave that method running, and the next start_session would refuse until
    it is cleared. With close_session=False an open session makes this refuse instead.
    A whole-script run in progress also makes it refuse, unless force=True.

    Returns {"stopped", "was_running", "pid", "closed_session"}.
    """
    status = local_spoke_status(port)
    if not status["running"]:
        _state_file(port).unlink(missing_ok=True)
        return {"stopped": False, "was_running": False, "pid": None, "closed_session": False}

    url = status["url"]
    closed = False
    try:
        state = orchestrator_session._dispatch(url, None, "get_spoke_state", {}, timeout_s=timeout_s)
    except OrchestratorCallError:
        state = {}
        if not force:
            raise
    if state.get("run") and not force:
        raise OrchestratorCallError(
            f"A script run ({state['run'].get('script')}) is in progress on the local spoke; abort it first, or pass force=True."
        )
    if state.get("session_active"):
        if close_session:
            orchestrator_session.finish(url, None, connect_timeout_s=timeout_s * 4)
            closed = True
        elif not force:
            raise OrchestratorCallError("A session is open on the local spoke; pass close_session=True (default) or force=True.")

    pid = status["pid"]
    if pid is None:
        raise OrchestratorCallError(f"Could not find the process listening on port {port}.")
    _terminate(pid)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and _ping(port, timeout_s=1.0) is not None:
        time.sleep(0.25)
    _state_file(port).unlink(missing_ok=True)
    return {"stopped": _ping(port, timeout_s=1.0) is None, "was_running": True, "pid": pid, "closed_session": closed}


def _terminate(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:  # pragma: no cover - the spoke is a Windows process
        os.kill(pid, 15)


def local_spoke_health(port: int = DEFAULT_PORT, *, timeout_s: float = 15.0) -> dict[str, Any]:
    """A health check of the local spoke, without starting or changing anything.

    Checks, each reported with ok and detail: process (alive), ping (answers /ping, with
    latency), mcp (a full MCP round trip to get_spoke_state, with latency), venus (the spoke
    can reach the VENUS Web API). "healthy" is True only if all of them pass. Also returns
    the spoke's status (idle / running / error / hold / paused / terminated), whether a
    session is open, the stop/resume state, pending prompts, and the last lines of its log
    when this client started it.
    """
    status = local_spoke_status(port)
    checks: dict[str, dict[str, Any]] = {}
    pid = status["pid"]
    checks["process"] = {"ok": _pid_alive(pid), "detail": f"pid {pid}" if pid else "no process listening"}

    started = time.perf_counter()
    ping = _ping(port, timeout_s=timeout_s)
    checks["ping"] = {
        "ok": ping is not None and ping.get("service") == _SERVICE,
        "detail": ping or "no answer",
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }

    state: dict[str, Any] = {}
    if checks["ping"]["ok"]:
        started = time.perf_counter()
        try:
            state = orchestrator_session._dispatch(status["url"], None, "get_spoke_state", {}, timeout_s=timeout_s)
            checks["mcp"] = {"ok": True, "detail": "get_spoke_state answered", "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
        except OrchestratorCallError as exc:
            checks["mcp"] = {"ok": False, "detail": str(exc)}
    else:
        checks["mcp"] = {"ok": False, "detail": "skipped: the spoke does not answer"}

    venus = state.get("venus_run_state")
    if not state:
        checks["venus"] = {"ok": False, "detail": "unknown: no answer from the spoke"}
    elif isinstance(venus, dict) and venus.get("error"):
        checks["venus"] = {"ok": False, "detail": f"VENUS Web API unreachable: {venus['error']}"}
    else:
        checks["venus"] = {"ok": True, "detail": venus}

    return {
        "healthy": all(check["ok"] for check in checks.values()),
        "url": status["url"],
        "checks": checks,
        "status": (state.get("status") or {}).get("status"),
        "status_detail": (state.get("status") or {}).get("detail"),
        "session_active": state.get("session_active"),
        "connection_id": state.get("connection_id"),
        "command_control": state.get("command_control"),
        "pending_prompts": len(state.get("pending_prompts") or []),
        "started_by_client": status["started_by_client"],
        "uptime_s": status["uptime_s"],
        "log_tail": _log_tail(port) if status["started_by_client"] else [],
    }

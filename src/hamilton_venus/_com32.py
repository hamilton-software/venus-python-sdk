"""Shared 32-bit-COM bridge for vendor drivers that ship a 32-bit-only COM server.

Several peripherals in this SDK (Hamilton Heater Cooler, Inheco ODTC, ...) are
driven directly from Python -- no VENUS runtime involved -- via a vendor COM
object that is registered **32-bit only** (``WOW6432Node`` / ``mscoree.dll``).
On 64-bit Python that object cannot be created in-process
(``0x80040154`` class-not-registered), so the SDK bridges through a private
32-bit Python worker subprocess (:mod:`hamilton_venus._com32_worker`) talking
line-delimited JSON over stdin/stdout. On 32-bit Python the object is created
directly in-process instead.

This module was extracted from :mod:`hamilton_venus.heater_cooler` (the first
driver to need this) when a second driver (Inheco ODTC) needed the identical
fix -- see ``installer/HANDOFF.md``. ``heater_cooler.py`` now delegates to the
generic names here; every public name it exposed before the extraction still
exists, as a thin wrapper, so existing imports/tests are unaffected.

The bundled 32-bit interpreter (``hamilton_venus/_com32_py32/python.exe``) is
now **shared** across every 32-bit-COM driver, so :func:`merge_binding_redirects`
is additive: each driver's ``configure_*()`` may write its own TransportLayer
redirects into the same ``python.exe.config`` in any order without clobbering
another driver's entries already there.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys

_IS_64BIT = sys.maxsize > 2**32

#: Where a private 32-bit CPython is looked up when one is bundled with the SDK.
_BUNDLED_PY32 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_com32_py32", "python.exe")

_WORKER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_com32_worker.py")


def shared_python32_dir() -> str:
    """The program-data folder shared by every venv (survives ``pip install -U``)."""
    return os.path.join(os.environ.get("PROGRAMDATA") or r"C:\ProgramData", "Hamilton", "VenusSDK", "py32")


def shared_python32_exe() -> str:
    """The 32-bit Python installed by ``setup-venus-sdk --install-py32``."""
    return os.path.join(shared_python32_dir(), "python.exe")


def _is_python_32bit(exe: str) -> bool:
    import subprocess

    try:
        out = subprocess.run(
            [exe, "-c", "import sys;print(sys.maxsize <= 2**32)"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and out.stdout.strip() == "True"


def find_python32(*env_vars: str) -> str | None:
    """Locate a 32-bit Python that can host a 32-bit-COM worker.

    Order: the first set env var in *env_vars* (e.g. ``HAMILTON_HHC_PYTHON32``),
    the SDK's bundled ``hamilton_venus/_com32_py32/python.exe`` (shared by every
    driver), the runtime installed by ``setup-venus-sdk --install-py32`` under
    ``%PROGRAMDATA%\\Hamilton\\VenusSDK\\py32``, this interpreter if it is
    already 32-bit, the ``py`` launcher's ``-3-32`` targets, then the per-user
    ``%LOCALAPPDATA%\\Programs\\Python\\Python3*-32`` installs. Returns the
    executable path, or ``None``.
    """
    if sys.platform != "win32":
        return None
    for env_var in env_vars:
        override = os.environ.get(env_var, "").strip().strip('"')
        if override:
            return override if _is_python_32bit(override) else None
    if os.path.isfile(_BUNDLED_PY32):  # our own artifact -- trust it, skip the probe
        return _BUNDLED_PY32
    if os.path.isfile(shared_python32_exe()):  # setup-venus-sdk artifact -- trust it, skip the probe
        return shared_python32_exe()
    if not _IS_64BIT:
        return sys.executable

    import shutil
    import subprocess

    launcher = shutil.which("py")
    if launcher:
        for tag in ("-3-32", "-3.13-32", "-3.12-32", "-3.11-32", "-3.10-32"):
            try:
                out = subprocess.run(
                    [launcher, tag, "-c", "import sys;print(sys.executable)"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            exe = out.stdout.strip()
            if out.returncode == 0 and exe and _is_python_32bit(exe):
                return exe

    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        base = os.path.join(local, "Programs", "Python")
        if os.path.isdir(base):
            for name in sorted(os.listdir(base), reverse=True):
                if name.lower().startswith("python3") and name.endswith("-32"):
                    exe = os.path.join(base, name, "python.exe")
                    if os.path.isfile(exe) and _is_python_32bit(exe):
                        return exe
    return None


class Bridge32Backend:
    """Runs :mod:`hamilton_venus._com32_worker` under a 32-bit Python and proxies calls.

    One instance drives one ProgID. *bin_dirs* are added to the worker's DLL
    search path (``os.add_dll_directory``); *tl_bin_dir*, if given, is where the
    worker looks for ``Hamilton.Components.TransportLayer.*`` DLLs when it needs
    to self-write a binding-redirect ``.exe.config`` (see
    :mod:`hamilton_venus._com32_worker`).
    """

    def __init__(
        self,
        python32: str,
        progid: str,
        *,
        bin_dirs: list[str] | None = None,
        tl_bin_dir: str | None = None,
        error_cls: type[Exception] = RuntimeError,
    ) -> None:
        self._python32 = python32
        self._progid = progid
        self._bin_dirs = list(bin_dirs or [])
        self._tl_bin_dir = tl_bin_dir
        self._error_cls = error_cls
        self._proc: subprocess.Popen[str] | None = None

    def _ensure(self) -> object:
        import subprocess

        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        args = [self._python32, "-u", _WORKER_PATH, self._progid]
        for bin_dir in self._bin_dirs:
            args += ["--bin-dir", bin_dir]
        if self._tl_bin_dir:
            args += ["--tl-bin-dir", self._tl_bin_dir]
        try:
            self._proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise self._error_cls(
                f"could not launch the 32-bit worker for {self._progid!r} ({self._python32}): {exc}"
            ) from exc
        # Confirm the worker can actually create the COM object before committing.
        self._request("__ping__")
        return self._proc

    def _request(self, name: str, *args: object) -> object:
        import json

        proc = self._proc
        proc.stdin.write(json.dumps({"call": name, "args": list(args)}) + "\n")  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]
        line = proc.stdout.readline()  # type: ignore[union-attr]
        if not line:
            err = proc.stderr.read() if proc.stderr else ""  # type: ignore[union-attr]
            raise self._error_cls(f"32-bit worker for {self._progid!r} exited unexpectedly. {err.strip()}")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise self._error_cls(f"{self._progid} {name}: {reply.get('error', 'worker error')}")
        return reply.get("raw")

    def raw_call(self, name: str, *args: object) -> object:
        self._ensure()
        return self._request(name, *args)

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            import json

            proc.stdin.write(json.dumps({"call": "__shutdown__"}) + "\n")  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
            proc.wait(timeout=5)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()


class InProcBackend32:
    """Creates a COM object in this interpreter. Only viable on 32-bit Python
    (the vendor server is a 32-bit inproc COM DLL)."""

    def __init__(
        self,
        progid: str,
        *,
        bin_dirs: list[str] | None = None,
        error_cls: type[Exception] = RuntimeError,
        diagnosis: str = "",
    ) -> None:
        self._progid = progid
        self._bin_dirs = list(bin_dirs or [])
        self._error_cls = error_cls
        self._diagnosis = diagnosis
        self._obj: object | None = None
        self._com_ready = False
        self._dll_dir_cookies: list[object] = []

    def _add_bin_dirs(self) -> None:
        if self._dll_dir_cookies:
            return
        for bin_dir in self._bin_dirs:
            if not os.path.isdir(bin_dir):
                continue
            with contextlib.suppress(OSError, AttributeError):  # pragma: no cover
                self._dll_dir_cookies.append(os.add_dll_directory(bin_dir))

    def _ensure(self) -> object:
        if self._obj is not None:
            return self._obj
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:  # pragma: no cover - non-Windows
            raise self._error_cls(f"pywin32 is required for the {self._progid} COM transport") from exc
        self._add_bin_dirs()
        if not self._com_ready:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            self._com_ready = True
        try:
            self._obj = win32com.client.Dispatch(self._progid)
        except Exception as exc:
            raise self._error_cls(
                f"could not create {self._progid!r} in-process: {exc}. {self._diagnosis}"
            ) from exc
        return self._obj

    def raw_call(self, name: str, *args: object) -> object:
        obj = self._ensure()
        return getattr(obj, name)(*args)

    def close(self) -> None:
        self._obj = None


def candidate_backends(
    *,
    progid: str,
    bin_dirs: list[str] | None = None,
    tl_bin_dir: str | None = None,
    env_vars: tuple[str, ...] = (),
    error_cls: type[Exception] = RuntimeError,
    diagnosis: str = "",
) -> list[object]:
    """The backend to use for creating *progid*: in-process on 32-bit Python,
    otherwise the 32-bit worker bridge."""
    if not _IS_64BIT:
        return [InProcBackend32(progid, bin_dirs=bin_dirs, error_cls=error_cls, diagnosis=diagnosis)]
    py32 = find_python32(*env_vars)
    if py32 is not None:
        return [
            Bridge32Backend(
                py32, progid, bin_dirs=bin_dirs, tl_bin_dir=tl_bin_dir, error_cls=error_cls
            )
        ]
    # will raise the diagnosis on first use
    return [InProcBackend32(progid, bin_dirs=bin_dirs, error_cls=error_cls, diagnosis=diagnosis)]


# --------------------------------------------------------------------------- #
# TransportLayer binding-redirect helpers                                     #
# --------------------------------------------------------------------------- #

_TRANSPORT_LAYER_DLLS = {
    "Hamilton.Components.TransportLayer.ComLink": "Hamilton.Components.TransportLayer.ComLink.dll",
    "Hamilton.Components.TransportLayer.Protocols": "Hamilton.Components.TransportLayer.Protocols.dll",
    "Hamilton.Components.TransportLayer.ComLib": "Hamilton.Components.TransportLayer.ComLib.dll",
    "Hamilton.Components.TransportLayer.HamCli": "Hamilton.Components.TransportLayer.HamCli.dll",
    "Hamilton.Components.TransportLayer.Canalyzer.Net": "Hamilton.Components.TransportLayer.Canalyzer.Net.dll",
}
_TRANSPORT_LAYER_PKT = "c71dc4479fe700d7"


def dll_file_version(path: str) -> str | None:
    try:
        import win32api

        info = win32api.GetFileVersionInfo(path, "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return None


def transport_layer_redirects(bin_dir: str) -> dict[str, str]:
    """Read the on-disk versions of ``Hamilton.Components.TransportLayer.*`` in
    *bin_dir* -> ``{assembly_name: version}`` for every one found."""
    out: dict[str, str] = {}
    for name, filename in _TRANSPORT_LAYER_DLLS.items():
        version = dll_file_version(os.path.join(bin_dir, filename))
        if version and not version.startswith("0."):
            out[name] = version
    return out


_REDIRECT_MARKER_PREFIX = "<!-- hamilton-com32 TransportLayer redirects: "


def _dependent_assembly_block(name: str, version: str) -> str:
    return (
        f'    <dependentAssembly>\n'
        f'      <assemblyIdentity name="{name}" publicKeyToken="{_TRANSPORT_LAYER_PKT}" culture="neutral" />\n'
        f'      <bindingRedirect oldVersion="0.0.0.0-99.0.0.0" newVersion="{version}" />\n'
        f'    </dependentAssembly>'
    )


def _existing_redirect_names(text: str) -> set[str]:
    import re

    return set(re.findall(r'<assemblyIdentity name="([^"]+)"[^>]*publicKeyToken="' + _TRANSPORT_LAYER_PKT + '"', text))


def merge_binding_redirects(config_path: str, redirects: dict[str, str]) -> bool:
    """Ensure *config_path* carries a ``<bindingRedirect>`` entry for each of
    *redirects* (``{assembly_name: version}``).

    **Additive across drivers**: the bundled interpreter is shared, so two
    different drivers may each call this against the same
    ``python.exe.config`` -- entries already present (by assembly name,
    regardless of which driver wrote them) are left untouched; only genuinely
    new assembly names are appended. Returns True if the file was created or
    changed.

    Kept string-based -- the .NET config namespace rules make ElementTree
    round-trips fragile, and these host .config files are tiny.
    """
    if not redirects:
        return False
    if os.path.isfile(config_path):
        text = open(config_path, encoding="utf-8").read()  # noqa: SIM115
        existing = _existing_redirect_names(text)
        missing = {name: version for name, version in redirects.items() if name not in existing}
        if not missing:
            return False
        deps = "".join(f"\n{_dependent_assembly_block(name, version)}" for name, version in missing.items())
        if "<assemblyBinding" in text:
            # Append new dependentAssembly entries into the first existing assemblyBinding block.
            idx = text.index("<assemblyBinding")
            close_idx = text.index("</assemblyBinding>", idx)
            new = text[:close_idx] + deps + "\n  " + text[close_idx:]
        else:
            block = (
                f'  {_REDIRECT_MARKER_PREFIX}{",".join(sorted(missing))} -->\n'
                f'  <assemblyBinding xmlns="urn:schemas-microsoft-com:asm.v1">{deps}\n'
                f'  </assemblyBinding>'
            )
            if "<runtime>" in text:
                new = text.replace("<runtime>", "<runtime>\n" + block, 1)
            elif "</configuration>" in text:
                new = text.replace(
                    "</configuration>", f"  <runtime>\n{block}\n  </runtime>\n</configuration>", 1
                )
            else:  # not a recognisable config; leave it alone
                return False
    else:
        deps = "".join(f"\n{_dependent_assembly_block(name, version)}" for name, version in redirects.items())
        block = (
            f'  {_REDIRECT_MARKER_PREFIX}{",".join(sorted(redirects))} -->\n'
            f'  <assemblyBinding xmlns="urn:schemas-microsoft-com:asm.v1">{deps}\n'
            f'  </assemblyBinding>'
        )
        new = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<configuration>\n  <runtime>\n" + block + "\n  </runtime>\n</configuration>\n"
        )
    os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


def write_py32_binding_config(python32: str, bin_dir: str) -> tuple[bool, str]:
    """Write ``<python32>.exe.config`` with the TransportLayer binding redirects
    read from the vendor DLLs in *bin_dir*. ``(ok, msg)``."""
    if sys.platform != "win32":
        return False, "not Windows"
    if not os.path.isfile(python32):
        return False, f"no such interpreter: {python32}"
    redirects = transport_layer_redirects(bin_dir)
    if not redirects:
        return False, f"no TransportLayer DLLs found under {bin_dir}"
    cfg = python32 + ".config"
    try:
        changed = merge_binding_redirects(cfg, redirects)
    except OSError as exc:
        return False, f"could not write {cfg}: {exc}"
    return True, (f"wrote binding redirects to {cfg}" if changed else f"{cfg} already configured")


# --------------------------------------------------------------------------- #
# ProgramData ACL grant                                                       #
# --------------------------------------------------------------------------- #

_USERS_SID = "*S-1-5-32-545"  # BUILTIN\Users


def grant_data_access(data_dir: str) -> tuple[bool, str]:
    """Give BUILTIN\\Users modify access to *data_dir* (recursively) so scripts
    can activate a vendor COM object **without elevation** -- needed when a
    driver's own log target directory was created by an earlier elevated run
    and is no longer writable by a standard user. Needs admin. Returns
    ``(ok, message)``; never raises.
    """
    if sys.platform != "win32":
        return False, "not Windows"
    import subprocess

    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError as exc:
        return False, f"could not create {data_dir}: {exc}"
    try:
        result = subprocess.run(
            ["icacls", data_dir, "/grant", f"{_USERS_SID}:(OI)(CI)M", "/T", "/C", "/Q"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"icacls failed to launch: {exc}"
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-1:] or [""]
        return False, f"icacls exit {result.returncode}: {tail[0]} (run elevated)"
    return True, f"granted Users modify on {data_dir}"


__all__ = [
    "Bridge32Backend",
    "InProcBackend32",
    "candidate_backends",
    "dll_file_version",
    "find_python32",
    "grant_data_access",
    "merge_binding_redirects",
    "shared_python32_dir",
    "shared_python32_exe",
    "transport_layer_redirects",
    "write_py32_binding_config",
]

"""Generic 32-bit worker process for a vendor 32-bit-only COM object.

The SDK's Python is usually 64-bit; some vendor drivers (Hamilton Heater
Cooler, Inheco ODTC, ...) ship a 32-bit-only .NET COM server. The 64-bit
:class:`hamilton_venus._com32.Bridge32Backend` spawns this module under a
**32-bit** Python and drives it over a line-delimited JSON protocol on
stdin/stdout::

    -> {"call": "Connect", "args": ["COM4", 5, 0, []]}
    <- {"ok": true, "raw": [0, 1, ["HC-...","HC-..."]]}
    <- {"ok": false, "error": "..."}

The ProgID to create is given on the command line (this module stays
import-free of ``hamilton_venus`` -- the bundled interpreter has no packages
installed beyond ``pywin32`` -- so it cannot import :mod:`hamilton_venus._com32`
and necessarily duplicates its binding-redirect-writing logic; a shared-fixture
test (``tests/unit/test_com32_worker.py``) feeds both implementations the same
input and asserts identical output so they cannot silently drift).

Some vendor DLLs (e.g. ``HamiltonHeaterCoolerCOM.dll``) are built against an
older ``Hamilton.Components.TransportLayer.*`` than the one shipped in the
vendor's own Bin folder, and their ``.dll.config`` binding redirect does not
cover the newer build -- so a plain host fails to bind the dependency
(HRESULT ``0x80070002``). ``setup-venus-sdk`` writes matching
``<bindingRedirect>`` entries into ``<this python>.exe.config`` at install
time; as a fallback this module writes them itself (derived from the on-disk
versions in ``--tl-bin-dir``, if given) and re-runs once so the CLR picks
them up.

Run directly for a smoke check::

    <python-32> -m hamilton_venus._com32_worker <ProgID> [--bin-dir DIR ...] [--tl-bin-dir DIR] --selftest
"""

from __future__ import annotations

import contextlib
import json
import os
import sys

_REEXEC_FLAG = "_HAMILTON_COM32_WORKER_CONFIGURED"

# assembly name -> file in the TransportLayer bin folder
_REDIRECT_ASSEMBLIES = {
    "Hamilton.Components.TransportLayer.ComLink": "Hamilton.Components.TransportLayer.ComLink.dll",
    "Hamilton.Components.TransportLayer.Protocols": "Hamilton.Components.TransportLayer.Protocols.dll",
    "Hamilton.Components.TransportLayer.ComLib": "Hamilton.Components.TransportLayer.ComLib.dll",
    "Hamilton.Components.TransportLayer.HamCli": "Hamilton.Components.TransportLayer.HamCli.dll",
    "Hamilton.Components.TransportLayer.Canalyzer.Net": "Hamilton.Components.TransportLayer.Canalyzer.Net.dll",
}
_PUBLIC_KEY_TOKEN = "c71dc4479fe700d7"
_MARKER_PREFIX = "<!-- hamilton-com32 TransportLayer redirects: "


def _parse_args(argv: list[str]) -> tuple[str, list[str], str | None, bool]:
    """``(progid, bin_dirs, tl_bin_dir, selftest)`` from *argv* (``sys.argv[1:]``)."""
    progid = ""
    bin_dirs: list[str] = []
    tl_bin_dir: str | None = None
    selftest = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--bin-dir":
            i += 1
            bin_dirs.append(argv[i])
        elif arg == "--tl-bin-dir":
            i += 1
            tl_bin_dir = argv[i]
        elif arg == "--selftest":
            selftest = True
        elif not progid and not arg.startswith("--"):
            progid = arg
        i += 1
    return progid, bin_dirs, tl_bin_dir, selftest


def _dll_version(path: str) -> str | None:
    try:
        import win32api

        info = win32api.GetFileVersionInfo(path, "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return None


def _wanted_redirects(tl_bin_dir: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, filename in _REDIRECT_ASSEMBLIES.items():
        version = _dll_version(os.path.join(tl_bin_dir, filename))
        if version and not version.startswith("0."):
            out[name] = version
    return out


def _existing_redirect_names(text: str) -> set[str]:
    import re

    return set(re.findall(r'<assemblyIdentity name="([^"]+)"[^>]*publicKeyToken="' + _PUBLIC_KEY_TOKEN + '"', text))


def _ensure_binding_config(tl_bin_dir: str | None) -> bool:
    """Make sure <python>.exe.config redirects the TransportLayer deps needed by
    *tl_bin_dir*'s DLLs. Returns True if it wrote a change (caller should re-exec).

    Additive, matching :func:`hamilton_venus._com32.merge_binding_redirects`:
    only assembly names not already present are appended, so a config another
    driver already wrote to is never clobbered.
    """
    if not tl_bin_dir or os.environ.get(_REEXEC_FLAG) or sys.maxsize > 2**32:
        return False  # only meaningful for a 32-bit worker
    redirects = _wanted_redirects(tl_bin_dir)
    if not redirects:
        return False

    cfg_path = sys.executable + ".config"
    try:
        if os.path.isfile(cfg_path):
            with open(cfg_path, encoding="utf-8") as fh:
                text = fh.read()
            existing = _existing_redirect_names(text)
            missing = {name: version for name, version in redirects.items() if name not in existing}
            if not missing:
                return False
            deps = "".join(
                f'\n    <dependentAssembly>\n'
                f'      <assemblyIdentity name="{name}" publicKeyToken="{_PUBLIC_KEY_TOKEN}" culture="neutral" />\n'
                f'      <bindingRedirect oldVersion="0.0.0.0-99.0.0.0" newVersion="{version}" />\n'
                f'    </dependentAssembly>'
                for name, version in missing.items()
            )
            if "<assemblyBinding" in text:
                idx = text.index("<assemblyBinding")
                close_idx = text.index("</assemblyBinding>", idx)
                new = text[:close_idx] + deps + "\n  " + text[close_idx:]
            else:
                block = (
                    f'  {_MARKER_PREFIX}{",".join(sorted(missing))} -->\n'
                    f'  <assemblyBinding xmlns="urn:schemas-microsoft-com:asm.v1">{deps}\n  </assemblyBinding>'
                )
                if "<runtime>" in text:
                    new = text.replace("<runtime>", "<runtime>\n" + block, 1)
                elif "</configuration>" in text:
                    new = text.replace(
                        "</configuration>", f"  <runtime>\n{block}\n  </runtime>\n</configuration>", 1
                    )
                else:
                    return False
        else:
            deps = "".join(
                f'\n    <dependentAssembly>\n'
                f'      <assemblyIdentity name="{name}" publicKeyToken="{_PUBLIC_KEY_TOKEN}" culture="neutral" />\n'
                f'      <bindingRedirect oldVersion="0.0.0.0-99.0.0.0" newVersion="{version}" />\n'
                f'    </dependentAssembly>'
                for name, version in redirects.items()
            )
            block = (
                f'  {_MARKER_PREFIX}{",".join(sorted(redirects))} -->\n'
                f'  <assemblyBinding xmlns="urn:schemas-microsoft-com:asm.v1">{deps}\n  </assemblyBinding>'
            )
            new = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                "<configuration>\n  <runtime>\n" + block + "\n  </runtime>\n</configuration>\n"
            )
        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write(new)
        return True
    except OSError as exc:
        print(f"warning: could not update {cfg_path}: {exc}", file=sys.stderr)
        return False


def _reexec(argv: list[str]) -> None:
    """Restart under the same interpreter so a freshly written .exe.config is read.

    Uses ``subprocess`` (not ``os.execv``, which does not quote spaces in paths on
    Windows) and inherits this process's stdio, so the parent keeps talking to the
    same pipe.
    """
    import subprocess

    os.environ[_REEXEC_FLAG] = "1"
    sys.exit(subprocess.call([sys.executable, "-u", os.path.abspath(__file__), *argv]))


def _jsonable(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class _Com:
    def __init__(self, progid: str, bin_dirs: list[str]) -> None:
        self._progid = progid
        self._bin_dirs = bin_dirs
        self._obj: object | None = None

    def _ensure(self) -> object:
        if self._obj is not None:
            return self._obj
        import pythoncom
        import win32com.client

        for bin_dir in self._bin_dirs:
            if os.path.isdir(bin_dir):
                with contextlib.suppress(OSError, AttributeError):
                    os.add_dll_directory(bin_dir)
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        self._obj = win32com.client.Dispatch(self._progid)
        return self._obj

    def call(self, name: str, args: list[object]) -> object:
        obj = self._ensure()
        method = getattr(obj, name)
        return _jsonable(method(*args))


def _run_selftest(progid: str, bin_dirs: list[str], tl_bin_dir: str | None, argv: list[str]) -> int:
    if _ensure_binding_config(tl_bin_dir):
        _reexec(argv)
    try:
        _Com(progid, bin_dirs)._ensure()
    except Exception as exc:
        print(f"selftest FAILED: {exc}", file=sys.stderr)
        return 1
    print("selftest OK: created " + progid)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    progid, bin_dirs, tl_bin_dir, selftest = _parse_args(argv)
    if not progid:
        print("usage: _com32_worker.py <ProgID> [--bin-dir DIR ...] [--tl-bin-dir DIR] [--selftest]", file=sys.stderr)
        return 2

    if selftest:
        return _run_selftest(progid, bin_dirs, tl_bin_dir, argv)

    if _ensure_binding_config(tl_bin_dir):
        _reexec(argv)

    com = _Com(progid, bin_dirs)
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            call = request.get("call")
            if call == "__shutdown__":
                break
            if call == "__ping__":
                com._ensure()
                out.write(json.dumps({"ok": True, "raw": [0]}) + "\n")
                out.flush()
                continue
            raw = com.call(call, list(request.get("args", [])))
            out.write(json.dumps({"ok": True, "raw": raw}) + "\n")
        except Exception as exc:
            out.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}) + "\n")
        out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Install/remove the private 32-bit Python + pywin32 runtime shared by the
Heater/Cooler, Inheco TEC and ODTC drivers on 64-bit Python.

Those drivers talk to 32-bit-only COM servers, so on 64-bit Python the SDK
bridges through a private 32-bit interpreter (see :mod:`hamilton_venus._com32`)
that only needs ``pythoncom`` and ``win32com.client``. This module downloads
pinned, hash-verified artifacts (an official python.org embeddable zip and the
matching pywin32 wheel), lays them out under ``%PROGRAMDATA%\\Hamilton\\
VenusSDK\\py32`` and verifies the result, so the SDK's normal 32-bit-Python
lookup finds it. All functions return ``(ok, message)`` / ``bool`` and never
raise.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from hamilton_venus import _com32

logger = logging.getLogger("venus_setup")


@dataclass(frozen=True)
class Artifact:
    """A pinned file to download/install, verified against *sha256*."""

    filename: str
    url: str
    sha256: str


PYTHON_EMBED = Artifact(
    filename="python-3.12.10-embed-win32.zip",
    url="https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-win32.zip",
    sha256="084b9eb24cb848605c895d05b738fbc2572efc8b4c18c415a824065864a2b853",
)
PYWIN32_WHEEL = Artifact(
    filename="pywin32-312-cp312-cp312-win32.whl",
    url=(
        "https://files.pythonhosted.org/packages/83/ff/"
        "32aa7d2ed0ab12b323aaa64f9b75e6ad4f8fd09f9ccfc28c79414d46838d/"
        "pywin32-312-cp312-cp312-win32.whl"
    ),
    sha256="dab4f65ac9c4e48400a2a0530c46c3c579cd5905ecd11b80692373915269208b",
)
#: ``(embed, wheel)`` order; tests inject fakes with their own hashes instead.
ARTIFACTS = (PYTHON_EMBED, PYWIN32_WHEEL)


def default_install_dir() -> Path:
    """The shared install location (``%PROGRAMDATA%\\Hamilton\\VenusSDK\\py32``)."""
    return Path(_com32.shared_python32_dir())


class Py32InstallError(Exception):
    """Raised internally when the 32-bit runtime cannot be fetched or installed."""


def _is_windows() -> bool:
    return sys.platform == "win32"


def _sha256(path: Path) -> str:
    """The lowercase hex SHA-256 of *path*, streamed in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(artifact: Artifact, dest_dir: Path, *, timeout: float = 60) -> Path:
    """Download *artifact* into *dest_dir* and return the local path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / artifact.filename
    try:
        with urllib.request.urlopen(artifact.url, timeout=timeout) as response, open(dest, "wb") as fh:
            shutil.copyfileobj(response, fh)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise Py32InstallError(
            f"could not download {artifact.filename} from {artifact.url}: {exc}"
            " (offline PC? use --py32-from <folder> with the pinned files)"
        ) from exc
    return dest


def _fetch(artifact: Artifact, work_dir: Path, source_dir: Path | None) -> Path:
    """Get *artifact* (from *source_dir* or the network) and verify its sha256."""
    if source_dir is not None:
        path = source_dir / artifact.filename
        if not path.is_file():
            raise Py32InstallError(f"missing expected file {artifact.filename} in {source_dir}")
    else:
        path = _download(artifact, work_dir)
    actual = _sha256(path)
    if actual.lower() != artifact.sha256.lower():
        raise Py32InstallError(f"hash mismatch for {artifact.filename}: expected {artifact.sha256}, got {actual}")
    return path


def _safe_extract(zip_path: Path, dest: Path) -> None:
    """Extract *zip_path* into *dest*, rejecting members whose path escapes it."""
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if target != dest and not target.is_relative_to(dest):
                raise Py32InstallError(f"refusing to extract {member.filename!r}: path escapes {dest}")
        zf.extractall(dest)


def _enable_site_packages(runtime_dir: Path) -> None:
    """Enable ``site`` and add ``Lib\\site-packages`` to the embeddable's ``._pth``.

    The embeddable zip ships with ``site`` disabled via a commented-out
    ``#import site`` line; the pywin32 wheel only bootstraps its DLL path when
    site is enabled and the ``Lib\\site-packages`` entry is what puts the wheel
    on ``sys.path``.
    """
    matches = sorted(runtime_dir.glob("python3*._pth"))
    if not matches:
        raise Py32InstallError(f"no python3*._pth file found in {runtime_dir}")
    pth = matches[0]
    with open(pth, encoding="utf-8", newline="") as fh:
        lines = fh.readlines()
    site_enabled = False
    for index, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        if stripped == "#import site":
            lines[index] = line.replace("#import site", "import site", 1)
            site_enabled = True
        elif stripped == "import site":
            site_enabled = True
    if not site_enabled:
        lines.append("import site\n")
    if not any(line.rstrip("\r\n") == r"Lib\site-packages" for line in lines):
        lines.append(r"Lib\site-packages" + "\n")
    with open(pth, "w", encoding="utf-8", newline="") as fh:
        fh.writelines(lines)


def verify_py32_runtime(python_exe: Path) -> tuple[bool, str]:
    """Check that *python_exe* is 32-bit and can import ``win32com.client``."""
    try:
        result = subprocess.run(
            [str(python_exe), "-c", "import sys, win32com.client; print(sys.maxsize <= 2**32)"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run {python_exe}: {exc}"
    if result.returncode == 0 and result.stdout.strip() == "True":
        return True, f"{python_exe} verified (32-bit, win32com importable)"
    tail = (result.stderr or "").strip().splitlines()[-1:] or [""]
    return False, f"{python_exe} failed verification (exit {result.returncode}): {tail[0]}"


def install_py32_runtime(
    target: Path | None = None,
    *,
    source_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    artifacts: tuple[Artifact, Artifact] = ARTIFACTS,
) -> tuple[bool, str]:
    """Install the pinned 32-bit Python + pywin32 runtime under *target*.

    All hashes are verified **before** anything under *target* is touched; the
    new layout is staged next to *target* and renamed into place, so a failed or
    interrupted run leaves any previous install intact. Returns ``(ok, message)``
    and never raises.
    """
    if target is None:
        target = default_install_dir()
    if not _is_windows():
        return False, "skipped: the 32-bit COM runtime is only needed on Windows"
    if (target / "python.exe").is_file() and not force:
        ok, message = verify_py32_runtime(target / "python.exe")
        if ok:
            return True, f"already installed at {target}"
        logger.warning("Existing 32-bit runtime at %s failed verification (%s); reinstalling", target, message)
    if dry_run:
        embed, wheel = artifacts
        logger.info(
            "Would download %s and %s and install the 32-bit COM runtime at %s",
            embed.filename,
            wheel.filename,
            target,
        )
        return True, f"[DRY-RUN] Would install the 32-bit COM runtime at {target}"

    embed, wheel = artifacts
    staging = target.with_name(target.name + ".staging")
    try:
        with tempfile.TemporaryDirectory() as work:
            work_dir = Path(work)
            embed_zip = _fetch(embed, work_dir, source_dir)
            wheel_zip = _fetch(wheel, work_dir, source_dir)
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(parents=True)
            _safe_extract(embed_zip, staging)
            _enable_site_packages(staging)
            (staging / "Lib" / "site-packages").mkdir(parents=True)
            _safe_extract(wheel_zip, staging / "Lib" / "site-packages")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            _rename_with_retry(staging, target)
    except (Py32InstallError, OSError) as exc:
        with contextlib.suppress(OSError):
            shutil.rmtree(staging)
        if isinstance(exc, PermissionError):
            return False, f"{exc} (re-run from an elevated Administrator terminal)"
        return False, str(exc)

    ok, verify_msg = verify_py32_runtime(target / "python.exe")
    if ok:
        logger.info("32-bit COM runtime installed at %s", target)
        return True, f"installed 32-bit COM runtime at {target}"
    return False, verify_msg


def _rename_with_retry(src: Path, dst: Path, attempts: int = 20, delay: float = 0.5) -> None:
    """Rename *src* to *dst*, retrying while antivirus/indexers briefly lock new executables."""
    for attempt in range(attempts):
        try:
            src.rename(dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def remove_py32_runtime(target: Path | None = None, *, dry_run: bool = False) -> bool:
    """Remove the 32-bit COM runtime install; True if anything was (or would be) removed.

    Never raises; failures are logged as warnings.
    """
    if target is None:
        target = default_install_dir()
    if not target.is_dir():
        return False
    if dry_run:
        logger.info("[DRY-RUN] Would remove the 32-bit COM runtime from %s", target)
        return True
    try:
        shutil.rmtree(target)
    except OSError as exc:
        logger.warning("Could not remove the 32-bit COM runtime at %s: %s", target, exc)
        return False
    logger.info("Removed the 32-bit COM runtime from %s", target)
    return True

"""Read VENUS's firmware communication trace (``.trc``) files.

VENUS writes a line-oriented firmware COM trace to a per-day file in its
``LogFiles`` directory. This module resolves that file's path from the
instrument type + simulation flag and tails the bytes appended to it while a
client session is open, so the trace can be embedded into the SDK run log
(see :mod:`hamilton_venus._internal._base_instrument_client`) or streamed
live by an application.

The trace file format (observed):

* One file per calendar day, appended to across every run that day.
* Lines are CRLF-terminated ASCII. Each line looks like
  ``<D> HH:MM:SS.mmm <port>: <firmware payload>`` where ``<D>`` is ``<``
  (sent to the instrument), ``>`` (received), ``!`` (info) or two spaces
  (Vantage broadcast / connection events).
* The timestamp is time-only -- the date lives only in the filename.
* The final line may lack its trailing newline while VENUS is mid-write.

This module is internal and not part of the public API.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from datetime import date
from pathlib import Path

from hamilton_venus.models import InstrumentType

_logger = logging.getLogger(__name__)

#: Standard VENUS ``LogFiles`` directory, used when the registry does not
#: name one -- see :func:`default_logfiles_dir`.
DEFAULT_LOGFILES_DIR = r"C:\Program Files (x86)\Hamilton\Logfiles"

#: Where VENUS records its ``LogFiles`` directory: the key's default value,
#: under the 32-bit registry view (``SOFTWARE\WOW6432Node\...`` on 64-bit Windows).
_LOGFILES_REGISTRY_KEY = r"SOFTWARE\Phoenix\Directories\Logfiles"

_PREFIX_SIMULATOR = "ComTrace_Simulator"
_PREFIX_STAR = "HxUsbComm"
_PREFIX_VANTAGE = "HxTcpIpBdzComm"


def registry_logfiles_dir() -> str | None:
    """VENUS's ``LogFiles`` directory as this PC's registry records it, or
    ``None`` when the key is missing (no VENUS installed, or not Windows)."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            _LOGFILES_REGISTRY_KEY,
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
        ) as key:
            value, _type = winreg.QueryValueEx(key, "")
    except OSError:
        return None
    return str(value).strip() or None


def default_logfiles_dir() -> str:
    """The ``LogFiles`` directory to use when none is configured: the
    registry's (:func:`registry_logfiles_dir`), else :data:`DEFAULT_LOGFILES_DIR`."""
    return registry_logfiles_dir() or DEFAULT_LOGFILES_DIR


def fetch_logfiles_dir(base_url: str, *, timeout: float = 5.0) -> str | None:
    """Ask VENUS where it writes its log files.

    ``GET <base_url>/api/vector/v3/system/paths`` and return ``paths["LogFiles"]``.
    Best-effort: returns ``None`` on any failure (server unreachable, auth
    required, unexpected shape). Runs a plain one-shot request so it works
    before the async client is started.
    """
    import httpx

    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/api/vector/v3/system/paths",
            headers={"accept": "text/plain; x-api-version=3.0"},
            timeout=timeout,
        )
        response.raise_for_status()
        value = response.json().get("paths", {}).get("LogFiles")
    except Exception as exc:
        _logger.debug("system/paths lookup failed: %s", exc)
        return None
    return str(value) if value else None


def resolve_logfiles_dir(configured_dir: str, base_url: str | None = None) -> str:
    """Pick the VENUS ``LogFiles`` directory.

    An explicit *configured_dir* always wins. Otherwise, if *base_url* is
    given, ask VENUS via :func:`fetch_logfiles_dir`. Otherwise (or if that
    lookup fails) use :func:`default_logfiles_dir`.
    """
    if configured_dir:
        return configured_dir
    if base_url:
        from_api = fetch_logfiles_dir(base_url)
        if from_api:
            return from_api
    return default_logfiles_dir()


def com_trace_prefix(instrument_type: InstrumentType, simulate: bool) -> str:
    """Return the trace-file name prefix for *instrument_type* / *simulate*.

    Mirrors VENUS's own selection (``System_Helper.hsi``): a simulated run
    always writes ``ComTrace_Simulator`` regardless of instrument; a live run
    writes ``HxUsbComm`` for STAR (USB) or ``HxTcpIpBdzComm`` for Vantage
    (TCP/IP). Raises :class:`ValueError` for any other live instrument type.
    """
    if simulate:
        return _PREFIX_SIMULATOR
    if instrument_type == InstrumentType.STAR:
        return _PREFIX_STAR
    if instrument_type == InstrumentType.Vantage:
        return _PREFIX_VANTAGE
    raise ValueError(
        f"no COM trace file naming known for a live {instrument_type} instrument"
    )


def com_trace_filename(
    instrument_type: InstrumentType, simulate: bool, when: date
) -> str:
    """Return ``<prefix><YYYYMMDD>.trc`` for the trace file covering *when*."""
    return f"{com_trace_prefix(instrument_type, simulate)}{when:%Y%m%d}.trc"


def resolve_com_trace_path(
    logfiles_dir: str,
    instrument_type: InstrumentType,
    simulate: bool,
    when: date,
) -> Path:
    """Return the full path to the trace file for *when* (no existence check).

    An empty *logfiles_dir* falls back to :func:`default_logfiles_dir`.
    """
    base = logfiles_dir or default_logfiles_dir()
    return Path(base) / com_trace_filename(instrument_type, simulate, when)


def iter_line_batches(
    lines: Sequence[str], *, max_bytes: int, max_lines: int
) -> Iterator[list[str]]:
    """Yield sub-lists of *lines* bounded by *max_bytes* and *max_lines*.

    Each batch's approximate UTF-8 size (``len(line.encode()) + 1`` per line)
    stays ``<= max_bytes`` and its length ``<= max_lines``. A single line
    already larger than *max_bytes* is emitted alone rather than split. A
    non-positive *max_bytes* or *max_lines* disables that bound; if both are
    non-positive a single batch containing every line is yielded.
    """
    if not lines:
        return
    if max_bytes <= 0 and max_lines <= 0:
        yield list(lines)
        return

    batch: list[str] = []
    batch_bytes = 0
    for line in lines:
        line_bytes = len(line.encode("utf-8", "replace")) + 1
        if batch and (
            (max_lines > 0 and len(batch) >= max_lines)
            or (max_bytes > 0 and batch_bytes + line_bytes > max_bytes)
        ):
            yield batch
            batch = []
            batch_bytes = 0
        batch.append(line)
        batch_bytes += line_bytes
    if batch:
        yield batch


class ComTraceTailer:
    """Yields newly-appended complete lines from a VENUS ``.trc`` file.

    Construct one when a client session opens: it records the trace file's
    current size as the starting offset, so :meth:`read_new_lines` returns
    only what VENUS writes from that point on. Safe to call against a file
    that does not exist yet (it starts appearing mid-run).

    Handles, without raising:

    * a partial trailing line (buffered until its newline arrives, unless
      ``flush_partial=True``);
    * the file being shorter than the last read offset (truncation / a
      same-named file being recreated) -- the offset resets to 0;
    * a local midnight rollover to a new day's filename -- the old file is
      drained to EOF, then tracking switches to the new file at offset 0.
      Rollover only applies when *when* is left to default (tracking "today");
      a pinned *when* always reads exactly that day's file.
    """

    def __init__(
        self,
        logfiles_dir: str,
        instrument_type: InstrumentType,
        simulate: bool,
        *,
        when: date | None = None,
        start_offset: int | None = None,
        clock: Callable[[], date] = date.today,
        encoding: str = "latin-1",
    ) -> None:
        self._logfiles_dir = logfiles_dir
        self._instrument_type = instrument_type
        self._simulate = simulate
        self._clock = clock
        self._encoding = encoding
        self._follow_clock = when is None
        self._when = when or clock()
        self._path = resolve_com_trace_path(
            logfiles_dir, instrument_type, simulate, self._when
        )
        if start_offset is not None:
            self._start_offset = max(0, start_offset)
        else:
            self._start_offset = self._current_size(self._path)
        self._offset = self._start_offset
        self._buf = ""

    @property
    def path(self) -> Path:
        """The trace file currently being tracked (changes on rollover)."""
        return self._path

    @property
    def start_offset(self) -> int:
        """Byte offset captured when the tailer was created."""
        return self._start_offset

    @property
    def offset(self) -> int:
        """Current read position in :attr:`path`."""
        return self._offset

    @staticmethod
    def _current_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def _read_from(self, path: Path, offset: int, max_bytes: int | None) -> tuple[str, int]:
        """Read text from *path* starting at *offset*; return (text, new_offset)."""
        try:
            with path.open("rb") as handle:
                handle.seek(offset)
                raw = handle.read() if max_bytes is None else handle.read(max_bytes)
        except FileNotFoundError:
            # The day's trace file may not exist until VENUS sends its first
            # firmware command -- expected, not an error.
            return "", offset
        except OSError as exc:
            _logger.warning("could not read COM trace %s: %s", path, exc)
            return "", offset
        text = raw.decode(self._encoding, "replace").replace("\r\n", "\n").replace("\r", "\n")
        return text, offset + len(raw)

    def _split_complete_lines(self, text: str, *, flush_partial: bool) -> list[str]:
        parts = (self._buf + text).split("\n")
        if flush_partial:
            self._buf = ""
            if parts and parts[-1] == "":
                parts.pop()
            return parts
        self._buf = parts.pop()
        return parts

    def read_new_lines(
        self, *, max_bytes: int | None = None, flush_partial: bool = False
    ) -> list[str]:
        """Return trace lines appended since the previous call.

        *max_bytes* bounds a single read (the next call continues where this
        one stopped). *flush_partial* returns any buffered partial trailing
        line too -- use it for a final read once the session has ended.
        """
        lines: list[str] = []

        # Midnight rollover: drain the day we were tracking, then move on.
        # Only when tracking "today" (no pinned `when`).
        today = self._clock()
        if self._follow_clock and today != self._when:
            tail, self._offset = self._read_from(self._path, self._offset, max_bytes)
            lines.extend(self._split_complete_lines(tail, flush_partial=True))
            self._when = today
            self._path = resolve_com_trace_path(
                self._logfiles_dir, self._instrument_type, self._simulate, today
            )
            self._offset = 0
            self._buf = ""

        size = self._current_size(self._path)
        if size < self._offset:
            # Truncated / recreated smaller -- restart from the top.
            self._offset = 0
            self._buf = ""

        text, self._offset = self._read_from(self._path, self._offset, max_bytes)
        lines.extend(self._split_complete_lines(text, flush_partial=flush_partial))
        return lines

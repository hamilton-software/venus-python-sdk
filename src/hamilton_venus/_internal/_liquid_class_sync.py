"""Push custom liquid classes to VENUS before the commands that use them.

The VENUS method does not import liquid classes itself (doing it inside every
aspirate cost about 1.5 s per command), so the SDK keeps VENUS's liquid class
database in step with the JSON library in the SDK ``Liquid Class`` folder:

* Original (Hamilton ``System``) liquid classes are never pushed -- VENUS skips
  them on import anyway, and checking costs nothing once the folder is indexed.
* Custom (``User``) liquid classes are pushed the first time a session uses them,
  and again whenever their JSON changes (content hash), so someone developing a
  liquid class sees each edit on the next command.
* Several changed classes go out in one push -- the call costs about the same for
  one class or many.

The library layout is ``<root>/<STAR|VANTAGE>/<System|User>/.../<name>.json``;
the file name is the liquid class name, and one name can exist in more than one
``User`` sub-folder (e.g. for both the channels and the 96 head), so a name's hash
covers all of its files.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from hamilton_venus.exceptions import LiquidClassPushError, VenusCommandFailedError
from hamilton_venus.models import CommandResponse

_logger = logging.getLogger(__name__)

_ORIGINALS_FOLDER = "system"

PushFn = Callable[[list[str]], Awaitable[CommandResponse]]


def liquid_class_names(value: Any) -> list[str]:
    """Flatten a liquid class argument (a name, a per-channel list, or None) into names."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [name for item in value for name in liquid_class_names(item)]
    return []


def liquid_class_names_in(parameters: Any) -> list[str]:
    """Every name under a ``liquidClass`` key anywhere in a command's parameters."""
    found: list[str] = []
    if isinstance(parameters, dict):
        for key, value in parameters.items():
            if key == "liquidClass":
                found.extend(liquid_class_names(value))
            else:
                found.extend(liquid_class_names_in(value))
    elif isinstance(parameters, (list, tuple)):
        for item in parameters:
            found.extend(liquid_class_names_in(item))
    return found


class _LiquidClassSync:
    """Per-session record of which custom liquid classes VENUS has, and at which content."""

    def __init__(self, root: Path, instrument_folder: str, push: PushFn) -> None:
        self._library = root / instrument_folder
        self._push = push
        self._index: dict[str, list[Path]] | None = None
        self._originals: set[str] = set()
        self._pushed_hashes: dict[str, str] = {}
        # Names already pushed this session when there is no local library to hash.
        self._pushed_blind: set[str] = set()
        self._held: dict[str, int] = {}

    # -- library index ---------------------------------------------------------

    def _scan(self) -> None:
        index: dict[str, list[Path]] = {}
        custom: set[str] = set()
        for path in self._library.rglob("*.json"):
            index.setdefault(path.stem, []).append(path)
            relative = path.relative_to(self._library).parts
            if not relative or relative[0].lower() != _ORIGINALS_FOLDER:
                custom.add(path.stem)
        self._index = index
        self._originals = set(index) - custom

    def _files(self, name: str) -> list[Path]:
        if self._index is None:
            self._scan()
        files = self._index.get(name) if self._index is not None else None
        if not files:
            # A liquid class created during this session (e.g. copied in while
            # developing one) is not in the first index yet.
            self._scan()
            files = self._index.get(name) if self._index is not None else None
        return sorted(files or [])

    def _hash(self, files: list[Path]) -> str:
        digest = hashlib.sha256()
        for path in files:
            digest.update(path.as_posix().encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    # -- public API --------------------------------------------------------------

    async def ensure(self, names: Iterable[str]) -> None:
        """Push every custom liquid class in *names* that VENUS does not have at its
        current content, in one call. Originals, held names, and names not in the JSON
        library are skipped."""
        wanted = [name for name in dict.fromkeys(names) if name and name not in self._held]
        if not wanted:
            return

        if not self._library.is_dir():
            # No local library (e.g. VENUS on another machine): nothing to hash, so push
            # each name once per session and let VENUS skip the originals.
            to_push = [name for name in wanted if name not in self._pushed_blind]
            if to_push:
                await self._push_and_check(to_push)
                self._pushed_blind.update(to_push)
            return

        changed: dict[str, str] = {}
        for name in wanted:
            files = self._files(name)
            if not files:
                _logger.debug("Liquid class %r is not in the JSON library; not pushing it", name)
                continue
            if name in self._originals:
                continue
            content_hash = self._hash(files)
            if self._pushed_hashes.get(name) != content_hash:
                changed[name] = content_hash
        if not changed:
            return
        await self._push_and_check(list(changed))
        self._pushed_hashes.update(changed)

    def record_pushed(self, names: Iterable[str]) -> None:
        """Note that *names* were just pushed outside :meth:`ensure` (an explicit
        ``push_liquid_classes``), so the next command does not push them again."""
        for name in names:
            if not self._library.is_dir():
                self._pushed_blind.add(name)
                continue
            files = self._files(name)
            if files and name not in self._originals:
                self._pushed_hashes[name] = self._hash(files)

    @contextmanager
    def hold(self, names: Iterable[str]) -> Iterator[None]:
        """Skip *names* in :meth:`ensure` until the block exits -- a compound command
        pushes its liquid classes once up front and then uses them throughout."""
        held = list(dict.fromkeys(names))
        for name in held:
            self._held[name] = self._held.get(name, 0) + 1
        try:
            yield
        finally:
            for name in held:
                remaining = self._held.get(name, 0) - 1
                if remaining > 0:
                    self._held[name] = remaining
                else:
                    self._held.pop(name, None)

    # -- push ------------------------------------------------------------------

    async def _push_and_check(self, names: list[str]) -> None:
        _logger.info("Pushing liquid classes to VENUS: %s", ", ".join(names))
        try:
            response = await self._push(names)
        except VenusCommandFailedError as exc:
            raise LiquidClassPushError(f"VENUS could not import liquid class(es) {', '.join(names)}: {exc}") from exc
        failed = _failed_imports(response)
        if failed:
            raise LiquidClassPushError(f"VENUS could not import liquid class(es): {'; '.join(failed)}")


def _failed_imports(response: CommandResponse) -> list[str]:
    params = response.return_parameters if isinstance(response.return_parameters, dict) else {}
    failed = params.get("failedImports") or []
    if not isinstance(failed, list):
        failed = [failed]
    described = []
    for item in failed:
        if isinstance(item, dict):
            name = item.get("name") or item.get("id") or item.get("liquidClass") or ""
            reason = item.get("message") or item.get("error") or item.get("reason") or ""
            described.append(f"{name}: {reason}" if name and reason else str(name or reason or item))
        else:
            described.append(str(item))
    return described

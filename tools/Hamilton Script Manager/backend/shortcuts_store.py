"""JSON-file-backed store for script shortcuts and the nested folders that
organize them.

Each shortcut's "script" is a byte-for-byte copy of the source .py file taken
at create/resync time (``data/scripts/<shortcut_id>/<original_filename>.py``
-- kept under its own id-named folder so two shortcuts pointing at
same-named files on disk don't collide) -- the copy, never the original, is
what the viewer displays and the script runner executes, so a shortcut stays
a stable, read-only snapshot even if the original file is later edited
elsewhere. No database dependency: shortcuts.json is small, single-writer
(one backend process, one connected UI), and rewritten whole on every
mutation under a lock, mirroring how these apps already treat saved deck
layouts as plain JSON on disk rather than reaching for a DB.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from backend.config import BackendConfig


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ShortcutsStoreError(Exception):
    """Raised for user-facing validation failures (missing source file, unknown id, ...)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Folder:
    id: str
    name: str
    parent_id: str | None
    order: int


@dataclass
class Shortcut:
    id: str
    name: str
    folder_id: str | None
    order: int
    source_path: str
    copy_filename: str
    created_at: str
    updated_at: str
    source_hash: str = ""


class ShortcutsStore:
    def __init__(self, config: BackendConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        config.scripts_dir.mkdir(parents=True, exist_ok=True)
        config.shortcuts_file.parent.mkdir(parents=True, exist_ok=True)
        if not config.shortcuts_file.is_file():
            self._write({"folders": [], "shortcuts": []})
        else:
            self._migrate_legacy_copies()

    def _migrate_legacy_copies(self) -> None:
        """Upgrade shortcuts created before copies were stored under their
        original filename (data/scripts/<id>/<name>.py instead of the old flat
        data/scripts/<id>.py), moving any existing copy into place so prior
        shortcuts keep working rather than losing their snapshot."""
        with self._lock:
            data = self._read()
            changed = False
            for s in data["shortcuts"]:
                if "copy_filename" not in s:
                    copy_filename = Path(s["source_path"]).name
                    s["copy_filename"] = copy_filename
                    legacy_path = self._config.scripts_dir / f"{s['id']}.py"
                    if legacy_path.is_file():
                        new_dir = self._config.scripts_dir / s["id"]
                        new_dir.mkdir(parents=True, exist_ok=True)
                        legacy_path.replace(new_dir / copy_filename)
                    changed = True
                if "source_hash" not in s:
                    # Backfill from the existing snapshot copy (not the live source) so
                    # upgrading doesn't retroactively flag every shortcut as out of sync --
                    # only edits made *after* this upgrade should surface as drift.
                    copy_path = self._config.scripts_dir / s["id"] / s["copy_filename"]
                    s["source_hash"] = _hash_file(copy_path) if copy_path.is_file() else ""
                    changed = True
            if changed:
                self._write(data)

    # -- persistence ----------------------------------------------------

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self._config.shortcuts_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"folders": [], "shortcuts": []}

    def _write(self, data: dict[str, Any]) -> None:
        tmp = self._config.shortcuts_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._config.shortcuts_file)

    # -- queries ----------------------------------------------------------

    def list_tree(self) -> dict[str, Any]:
        with self._lock:
            data = self._read()
        shortcuts = [self._with_sync_status(dict(s)) for s in data["shortcuts"]]
        return {"folders": data["folders"], "shortcuts": shortcuts}

    @staticmethod
    def _with_sync_status(s: dict[str, Any]) -> dict[str, Any]:
        """Annotate a shortcut dict with drift-vs-source info for the tree UI --
        computed on read rather than stored, so it always reflects the source
        file's current state instead of only whatever it was at the last sync."""
        src = Path(s["source_path"])
        if not src.is_file():
            s["source_missing"] = True
            s["is_stale"] = False
            return s
        s["source_missing"] = False
        try:
            s["is_stale"] = _hash_file(src) != s.get("source_hash", "")
        except OSError:
            s["is_stale"] = False
        return s

    def get_shortcut(self, shortcut_id: str) -> Shortcut:
        with self._lock:
            data = self._read()
        for s in data["shortcuts"]:
            if s["id"] == shortcut_id:
                return Shortcut(**s)
        raise ShortcutsStoreError(f"Unknown shortcut: {shortcut_id}")

    def get_script_copy_path(self, shortcut_id: str) -> Path:
        shortcut = self.get_shortcut(shortcut_id)
        return self._config.scripts_dir / shortcut_id / shortcut.copy_filename

    def read_script(self, shortcut_id: str) -> str:
        path = self.get_script_copy_path(shortcut_id)
        return path.read_text(encoding="utf-8", errors="replace")

    def check_sync_status(self, shortcut_id: str) -> dict[str, bool]:
        """Freshly re-hashes the source file for one shortcut, right now -- unlike
        list_tree()'s badge (a snapshot from whenever the tree was last sent),
        this is what GetScript uses so a selection always reflects the source
        file's current state, not however stale the last shortcuts_tree happens
        to be."""
        shortcut = self.get_shortcut(shortcut_id)
        annotated = self._with_sync_status(asdict(shortcut))
        return {"is_stale": annotated["is_stale"], "source_missing": annotated["source_missing"]}

    # -- folders ----------------------------------------------------------

    def create_folder(self, name: str, parent_id: str | None) -> Folder:
        name = name.strip()
        if not name:
            raise ShortcutsStoreError("Folder name cannot be empty.")
        with self._lock:
            data = self._read()
            if parent_id is not None and not any(f["id"] == parent_id for f in data["folders"]):
                raise ShortcutsStoreError(f"Unknown parent folder: {parent_id}")
            siblings = [f for f in data["folders"] if f["parent_id"] == parent_id]
            folder = Folder(id=_new_id(), name=name, parent_id=parent_id, order=len(siblings))
            data["folders"].append(asdict(folder))
            self._write(data)
            return folder

    def rename_folder(self, folder_id: str, name: str) -> None:
        name = name.strip()
        if not name:
            raise ShortcutsStoreError("Folder name cannot be empty.")
        with self._lock:
            data = self._read()
            for f in data["folders"]:
                if f["id"] == folder_id:
                    f["name"] = name
                    self._write(data)
                    return
            raise ShortcutsStoreError(f"Unknown folder: {folder_id}")

    def delete_folder(self, folder_id: str) -> None:
        with self._lock:
            data = self._read()
            if not any(f["id"] == folder_id for f in data["folders"]):
                raise ShortcutsStoreError(f"Unknown folder: {folder_id}")

            # Recursively collect this folder and all descendant folders.
            to_delete = {folder_id}
            changed = True
            while changed:
                changed = False
                for f in data["folders"]:
                    if f["parent_id"] in to_delete and f["id"] not in to_delete:
                        to_delete.add(f["id"])
                        changed = True

            for s in data["shortcuts"]:
                if s["folder_id"] in to_delete:
                    self._delete_script_copy(s["id"])
            data["shortcuts"] = [s for s in data["shortcuts"] if s["folder_id"] not in to_delete]
            data["folders"] = [f for f in data["folders"] if f["id"] not in to_delete]
            self._write(data)

    # -- shortcuts ----------------------------------------------------------

    def create_shortcut(self, name: str, source_path: str, folder_id: str | None) -> Shortcut:
        name = name.strip()
        if not name:
            raise ShortcutsStoreError("Shortcut name cannot be empty.")
        src = Path(source_path)
        if not src.is_file() or src.suffix.lower() != ".py":
            raise ShortcutsStoreError(f"Not a Python file: {source_path}")

        with self._lock:
            data = self._read()
            if folder_id is not None and not any(f["id"] == folder_id for f in data["folders"]):
                raise ShortcutsStoreError(f"Unknown folder: {folder_id}")
            siblings = [s for s in data["shortcuts"] if s["folder_id"] == folder_id]
            shortcut_id = _new_id()
            copy_filename = src.name
            copy_dir = self._config.scripts_dir / shortcut_id
            copy_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, copy_dir / copy_filename)
            now = _now()
            shortcut = Shortcut(
                id=shortcut_id,
                name=name,
                folder_id=folder_id,
                order=len(siblings),
                source_path=str(src),
                copy_filename=copy_filename,
                created_at=now,
                updated_at=now,
                source_hash=_hash_file(src),
            )
            data["shortcuts"].append(asdict(shortcut))
            self._write(data)
            return shortcut

    def update_shortcut(self, shortcut_id: str, name: str | None = None) -> None:
        with self._lock:
            data = self._read()
            for s in data["shortcuts"]:
                if s["id"] == shortcut_id:
                    if name is not None:
                        name = name.strip()
                        if not name:
                            raise ShortcutsStoreError("Shortcut name cannot be empty.")
                        s["name"] = name
                    s["updated_at"] = _now()
                    self._write(data)
                    return
            raise ShortcutsStoreError(f"Unknown shortcut: {shortcut_id}")

    def resync_shortcut(self, shortcut_id: str) -> None:
        """Re-copy the shortcut's read-only snapshot from its original source_path,
        for when the operator wants to pick up upstream edits to that file."""
        with self._lock:
            data = self._read()
            for s in data["shortcuts"]:
                if s["id"] == shortcut_id:
                    src = Path(s["source_path"])
                    if not src.is_file():
                        raise ShortcutsStoreError(f"Source file no longer exists: {src}")
                    copy_dir = self._config.scripts_dir / shortcut_id
                    copy_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, copy_dir / s["copy_filename"])
                    s["source_hash"] = _hash_file(src)
                    s["updated_at"] = _now()
                    self._write(data)
                    return
            raise ShortcutsStoreError(f"Unknown shortcut: {shortcut_id}")

    def delete_shortcut(self, shortcut_id: str) -> None:
        with self._lock:
            data = self._read()
            if not any(s["id"] == shortcut_id for s in data["shortcuts"]):
                raise ShortcutsStoreError(f"Unknown shortcut: {shortcut_id}")
            data["shortcuts"] = [s for s in data["shortcuts"] if s["id"] != shortcut_id]
            self._write(data)
        self._delete_script_copy(shortcut_id)

    def _delete_script_copy(self, shortcut_id: str) -> None:
        shutil.rmtree(self._config.scripts_dir / shortcut_id, ignore_errors=True)

    # -- move / reorder ----------------------------------------------------------

    def move_item(
        self,
        item_id: str,
        item_type: Literal["folder", "shortcut"],
        new_parent_id: str | None,
        new_index: int,
    ) -> None:
        with self._lock:
            data = self._read()
            key = "folders" if item_type == "folder" else "shortcuts"
            parent_key = "parent_id" if item_type == "folder" else "folder_id"
            items = data[key]

            item = next((i for i in items if i["id"] == item_id), None)
            if item is None:
                raise ShortcutsStoreError(f"Unknown {item_type}: {item_id}")

            if new_parent_id is not None and not any(f["id"] == new_parent_id for f in data["folders"]):
                raise ShortcutsStoreError(f"Unknown folder: {new_parent_id}")
            if item_type == "folder" and (
                new_parent_id == item_id or self._is_descendant(data["folders"], new_parent_id, item_id)
            ):
                raise ShortcutsStoreError("Cannot move a folder into itself or one of its own subfolders.")

            old_parent_id = item[parent_key]
            item[parent_key] = new_parent_id

            # Recompute contiguous order for the old sibling group (item removed).
            self._reindex(items, parent_key, old_parent_id, exclude_id=item_id)

            # Insert into the new sibling group at new_index, then reindex.
            new_siblings = [i for i in items if i[parent_key] == new_parent_id and i["id"] != item_id]
            new_index = max(0, min(new_index, len(new_siblings)))
            new_siblings.insert(new_index, item)
            for idx, sibling in enumerate(new_siblings):
                sibling["order"] = idx

            self._write(data)

    @staticmethod
    def _reindex(items: list[dict[str, Any]], parent_key: str, parent_id: str | None, exclude_id: str) -> None:
        siblings = [i for i in items if i[parent_key] == parent_id and i["id"] != exclude_id]
        for idx, sibling in enumerate(siblings):
            sibling["order"] = idx

    @staticmethod
    def _is_descendant(folders: list[dict[str, Any]], candidate_id: str | None, ancestor_id: str) -> bool:
        """True if *candidate_id* is *ancestor_id* itself or nested somewhere under it."""
        current = candidate_id
        seen: set[str] = set()
        while current is not None:
            if current == ancestor_id:
                return True
            if current in seen:
                return False
            seen.add(current)
            match = next((f for f in folders if f["id"] == current), None)
            current = match["parent_id"] if match is not None else None
        return False

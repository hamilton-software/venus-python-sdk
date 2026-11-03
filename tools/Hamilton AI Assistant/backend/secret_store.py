"""Secrets -- the Anthropic API key and the spoke / hub bearer tokens -- encrypted with Windows
DPAPI for the current Windows user.

Only the same Windows account on the same PC can decrypt the files; they are never written in
plain text and never sent to the page (the page only sees whether one is set, and its last
four characters).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_CRYPTPROTECT_UI_FORBIDDEN = 0x1
API_KEY_ENTROPY = b"Hamilton AI Assistant API key"
TOKEN_ENTROPY = b"Hamilton AI Assistant connection token"


def _blob(data: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _call(function, data: bytes, entropy_bytes: bytes) -> bytes:
    data_in, entropy, data_out = _blob(data), _blob(entropy_bytes), _DataBlob()
    if not function(ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
                    _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(data_out.pbData)


def protect(data: bytes, entropy: bytes = API_KEY_ENTROPY) -> bytes:
    return _call(ctypes.windll.crypt32.CryptProtectData, data, entropy)


def unprotect(data: bytes, entropy: bytes = API_KEY_ENTROPY) -> bytes:
    return _call(ctypes.windll.crypt32.CryptUnprotectData, data, entropy)


class SecretStore:
    def __init__(self, path: Path, entropy: bytes = TOKEN_ENTROPY, label: str = "token") -> None:
        self._path = path
        self._entropy = entropy
        self._label = label

    def get(self) -> str | None:
        try:
            return unprotect(self._path.read_bytes(), self._entropy).decode("utf-8") or None
        except (OSError, UnicodeDecodeError):
            return None

    def set(self, secret: str) -> None:
        secret = secret.strip()
        if not secret:
            raise ValueError(f"The {self._label} is empty.")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(protect(secret.encode("utf-8"), self._entropy))

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)

    def hint(self) -> str | None:
        """'…abcd' for the page, or None when no key is set."""
        key = self.get()
        return f"…{key[-4:]}" if key else None


class ApiKeyStore(SecretStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path, API_KEY_ENTROPY, "API key")

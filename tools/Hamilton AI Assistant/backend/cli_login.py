"""Sign-ins that a command-line tool performs: `claude auth login --console`, `aws sso login`,
`az login`, `gcloud auth application-default login`.

The tool does the sign-in itself (it opens the browser and keeps the credentials where it keeps
them), so the app never sees a token. This runs it, reads its output for the link and the code it
tells the user about, and reports when it exits. State has the same shape as the device-code
sign-in's (oidc.LoginManager), so the page shows both the same way.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

URL = re.compile(r"https?://[^\s\"'<>]+")
# "enter the code: ABCD-EFGH" (aws, az, gcloud)
CODE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b|\bcode[: ]+([A-Z0-9]{8,10})\b")
KEEP_LINES = 8
TIMEOUT_S = 600  # the browser step is the user's; give up after ten minutes


def run_quietly(argv: Sequence[str], env: dict[str, str] | None = None, timeout: float = 20) -> subprocess.CompletedProcess | None:
    """A short read-only command (a status check); None if it can't be run or times out."""
    try:
        return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, env=env,  # noqa: S603
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None


class CliLogin:
    """One command-line sign-in at a time."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._state: dict[str, Any] = {"state": "idle"}

    def state(self) -> dict[str, Any]:
        return dict(self._state)

    async def start(self, argv: Sequence[str], env: dict[str, str], on_done: Callable[[], None] | None = None) -> dict[str, Any]:
        self.cancel()
        try:
            self._process = await asyncio.create_subprocess_exec(
                *argv, env=env, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            raise RuntimeError(f"Could not start {argv[0]}: {exc.strerror or exc}. Is it installed?") from exc
        self._state = {"state": "waiting"}
        self._task = asyncio.create_task(self._watch(self._process, on_done))
        return self.state()

    async def _watch(self, process: asyncio.subprocess.Process, on_done: Callable[[], None] | None) -> None:
        lines: list[str] = []
        try:
            assert process.stdout is not None
            async with asyncio.timeout(TIMEOUT_S):
                while raw := await process.stdout.readline():
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    lines = [*lines, line][-KEEP_LINES:]
                    self._note(line)
                code = await process.wait()
            if code == 0:
                if on_done:
                    on_done()
                self._state = {"state": "done", "message": "Signed in."}
            else:
                self._state = {"state": "error", "message": " ".join(lines[-3:]) or f"The sign-in ended with code {code}."}
        except TimeoutError:
            await self._reap(process)
            self._state = {"state": "error", "message": "The sign-in was not finished in time. Try again."}
        except asyncio.CancelledError:
            await self._reap(process)
            self._state = {"state": "cancelled", "message": "Sign-in cancelled."}
            raise

    def _note(self, line: str) -> None:
        state = dict(self._state)
        if (url := URL.search(line)) and "verification_uri" not in state:
            state["verification_uri"] = url.group(0).rstrip(".,)")
        if (code := CODE.search(line)) and "user_code" not in state:
            state["user_code"] = code.group(1) or code.group(2)
        self._state = state

    @staticmethod
    async def _reap(process: asyncio.subprocess.Process) -> None:
        """End the tool and wait for it, so its pipes are closed."""
        with contextlib.suppress(ProcessLookupError, OSError):
            process.kill()
        with contextlib.suppress(Exception):
            await process.wait()
        transport = getattr(process, "_transport", None)  # close the pipes now, not when it is collected
        if transport is not None:
            with contextlib.suppress(Exception):
                transport.close()

    def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        if self._state.get("state") == "waiting":
            self._state = {"state": "cancelled", "message": "Sign-in cancelled."}

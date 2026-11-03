"""Shows the operator prompts a running flow is blocked on.

A hardware error that automatic recovery cannot fix makes the spoke's session wait for a person
(`pending_operator_prompts` in get_spoke_state) before the command returns. Studio's run thread is
inside that command, so this watcher polls the spoke while a run is active, publishes each prompt
to the page ("operator_prompt" / "operator_prompt_resolved"), and sends the person's answer back.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from backend.mcp_bridge import BridgeError

POLL_INTERVAL_S = 1.0


class PromptWatcher:
    def __init__(self, bridge: Any, publish: Callable[[dict[str, Any]], None], is_active: Callable[[], bool]) -> None:
        self._bridge = bridge
        self._publish = publish
        self._is_active = is_active
        self._shown: dict[str, dict[str, Any]] = {}  # error_uuid -> the prompt the page has been given
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="studio-prompt-watch", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def pending(self) -> list[dict[str, Any]]:
        """The prompts shown and not yet answered (sent to a page that connects mid-prompt)."""
        return list(self._shown.values())

    def poll(self) -> None:
        """One look at the spoke: publish prompts that appeared, and retract ones that went away."""
        try:
            state = self._bridge.spoke_state()
        except BridgeError:
            return  # the spoke is busy or gone; the next poll tries again
        prompts = {p["error_uuid"]: p for p in state.get("pending_operator_prompts") or [] if p.get("error_uuid")}
        for uuid, prompt in prompts.items():
            if uuid not in self._shown or self._shown[uuid] != prompt:  # new, or re-raised after an access action
                self._shown[uuid] = prompt
                self._publish(prompt)
        for uuid in [u for u in self._shown if u not in prompts]:
            del self._shown[uuid]
            self._publish({"type": "operator_prompt_resolved", "error_uuid": uuid})

    def _loop(self) -> None:
        while not self._stop.wait(POLL_INTERVAL_S):
            if self._is_active() or self._shown:
                self.poll()

    def answer(self, error_uuid: str, action: str | None, channel_actions: dict[str, int] | None) -> None:
        """Send the person's choice to the spoke; the next poll retracts the prompt once it is taken."""
        self._bridge.resolve_operator_prompt(error_uuid, action, channel_actions)
        self.poll()

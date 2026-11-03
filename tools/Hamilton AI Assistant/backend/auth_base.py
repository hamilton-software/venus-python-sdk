"""What every sign-in method shares: the engine's needs, the method protocol, and the constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

ANTHROPIC_VERSION = "2023-06-01"
FIRST_PARTY_URL = "https://api.anthropic.com"

# The engine starts from this PC's own environment, and ranks some of these variables above any
# sign-in the app sets up (the provider switches first, then the bearer token, then the API key).
# They are blanked, so a Claude Code setup on the same PC can't change where the assistant signs in.
INHERITED_CREDENTIALS = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
)


class AuthError(RuntimeError):
    """The active method can't give the engine credentials (not signed in, expired, ...)."""


@dataclass(frozen=True)
class EngineAuth:
    """What the agent engine needs: environment variables, and settings (a JSON object the SDK
    passes as --settings, e.g. apiKeyHelper)."""

    env: dict[str, str] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)


class AuthMethod(Protocol):
    id: str
    label: str

    def status(self) -> dict[str, Any]:
        """{"ready": bool, "who": str | None}."""

    def engine_auth(self, app_settings: dict[str, Any]) -> EngineAuth:
        """What the engine needs; raises AuthError when not ready."""

    def http_headers(self) -> dict[str, str] | None:
        """Headers for a call to the endpoint (the test, the model list); None when not ready."""

    def rejection(self) -> str:
        """What a 401 / 403 is about, for the message ("this API key")."""

    async def prepare(self) -> None:
        """Get ready for an HTTP call: refresh an expiring token."""

    def sign_out(self) -> None:
        """Forget the credentials."""

    # Methods with a sign-in step in the browser also have: async begin_login() -> state,
    # login_state() -> state, cancel_login(). The state is {"state": "idle" | "waiting" | "done" |
    # "error" | "cancelled", "message", and while waiting "user_code" / "verification_uri" (/ _complete)}.

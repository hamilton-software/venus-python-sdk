"""Backend-level settings for the AI Assistant app."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The Hamilton skills the agent gets. Their source of truth is the SDK's .claude\skills.
HAMILTON_SKILLS = (
    "hamilton-labware-compatibility",
    "hamilton-liquid-class-optimization",
    "hamilton-liquid-handling-rules",
    "hamilton-tip-counter-setup",
    "hamilton-script-authoring",
    "hamilton-gripper-transport",
    "hamilton-channel-random-access",
    "hamilton-deck-geometry",
    "hamilton-tilt-module",
    "hamilton-load-tray-autoload",
    "hamilton-deck-tracking",
)


def _user_data_dir() -> Path:
    # Per Windows user: the API key, conversations and the agent engine's own config are
    # personal, unlike the sibling apps' settings that live inside the app folder.
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Hamilton" / "AI Assistant"


@dataclass(frozen=True)
class BackendConfig:
    host: str = "127.0.0.1"
    port: int = 8739
    static_dir: Path = Path(__file__).parent / "static"
    data_dir: Path = field(default_factory=_user_data_dir)
    # The SDK install (or repo) root: two levels above backend\ in an installed layout
    # (root\ai_assistant_app\backend), three in the dev layout (repo\tools\ai_assistant_app\backend).
    sdk_root: Path = Path(__file__).resolve().parents[
        3 if Path(__file__).resolve().parents[2].name == "tools" else 2
    ]
    # The venv's Scripts folder, where hamilton-venus-mcp.exe lives next to this python.exe.
    scripts_dir: Path = Path(sys.executable).resolve().parent

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def api_key_file(self) -> Path:
        return self.data_dir / "api_key.bin"

    @property
    def oidc_token_file(self) -> Path:
        """The company sign-in's access / refresh tokens (DPAPI)."""
        return self.data_dir / "sso_tokens.bin"

    @property
    def spoke_token_file(self) -> Path:
        return self.data_dir / "spoke_token.bin"

    @property
    def hub_token_file(self) -> Path:
        return self.data_dir / "hub_token.bin"

    @property
    def engine_home(self) -> Path:
        """CLAUDE_CONFIG_DIR for the agent engine, so it never reads the PC user's own
        Claude settings, skills, plugins or login."""
        return self.data_dir / "engine"

    @property
    def workspace_dir(self) -> Path:
        """The engine's working folder; holds only .claude\\skills (the Hamilton skills)."""
        return self.data_dir / "workspace"

    @property
    def conversations_dir(self) -> Path:
        """One audit file per conversation (JSON lines)."""
        return self.data_dir / "conversations"

    @property
    def mcp_server_exe(self) -> Path:
        return self.scripts_dir / "hamilton-venus-mcp.exe"

    def skill_sources(self) -> list[Path]:
        """Where the Hamilton skills may be, in order: the installed app's own skills\\ folder
        (next to backend\\, put there by the installer), the SDK's own .claude\\skills (repo or
        install), then the copy bundled for the Claude Code plugin."""
        candidates = [
            Path(__file__).resolve().parents[1] / "skills",
            self.sdk_root / ".claude" / "skills",
            self.sdk_root.parent / ".claude" / "skills",
            self.sdk_root / "ai_harness" / "claude_code" / "hamilton-venus" / "skills",
            self.sdk_root / "tools" / "ai_harness" / "claude_code" / "hamilton-venus" / "skills",
            self.sdk_root.parent / "ai_harness" / "claude_code" / "hamilton-venus" / "skills",
        ]
        return [c for c in candidates if c.is_dir()]


def load_backend_config() -> BackendConfig:
    port = int(os.environ.get("HAMILTON_AI_ASSISTANT_PORT", "8739"))
    host = os.environ.get("HAMILTON_AI_ASSISTANT_HOST", "127.0.0.1")
    data_dir = os.environ.get("HAMILTON_AI_ASSISTANT_DATA_DIR")
    if data_dir:
        return BackendConfig(host=host, port=port, data_dir=Path(data_dir))
    return BackendConfig(host=host, port=port)

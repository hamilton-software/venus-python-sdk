"""Sign-in methods that a command-line tool performs: the agent engine's own Anthropic Console / SSO
login, and a cloud provider's (AWS, Google Cloud, Azure) -- see cli_login.py.

The app keeps no token for either. The engine reads its own saved login (Console), or the cloud
provider's credentials (Bedrock / Vertex / Foundry), when it starts.

Not here, on purpose: the engine can also sign in with a Claude.ai subscription (`--claudeai`).
Anthropic's terms don't let apps built on its Agent SDK offer that, so it is never started, and a
saved Claude.ai login is not accepted as a sign-in (the engine is also told forceLoginMethod=console).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from backend import cli_login
from backend.auth_base import FIRST_PARTY_URL, INHERITED_CREDENTIALS, AuthError, EngineAuth

CONSOLE = "anthropic_console"
CLOUD = "cloud"
CLOUD_PROVIDERS = ("bedrock", "vertex", "foundry")
STATUS_CACHE_S = 20.0

Runner = Callable[..., Any]


def _claude_exe() -> Path | None:
    """The engine bundled with the Agent SDK."""
    try:
        import claude_agent_sdk
    except ImportError:
        return None
    exe = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude.exe"
    return exe if exe.is_file() else None


class _Cached:
    """A status check that runs a command; cached for a few seconds so the Settings page and the
    agent can ask as often as they like."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._value: tuple[float, dict[str, Any]] | None = None

    def get(self, compute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        if self._value is None or self._clock() - self._value[0] > STATUS_CACHE_S:
            self._value = (self._clock(), compute())
        return self._value[1]

    def forget(self) -> None:
        self._value = None


class ConsoleMethod:
    """The engine's own Anthropic Console (API billing) or SSO sign-in, saved in the app's private
    engine folder. Never a Claude.ai subscription."""

    id = CONSOLE
    label = "Anthropic Console / SSO"

    def __init__(
        self,
        get_settings: Callable[[], dict[str, Any]],
        engine_home: Path,
        *,
        claude_exe: Path | None = None,
        run: Runner = cli_login.run_quietly,
        login: cli_login.CliLogin | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._get_settings = get_settings
        self._home = engine_home
        self._exe = claude_exe
        self._run = run
        self._login = login or cli_login.CliLogin()
        self._cache = _Cached(clock)

    def _exe_path(self) -> Path:
        exe = self._exe or _claude_exe()
        if exe is None:
            raise AuthError("The agent engine is not installed.")
        return exe

    def _env(self) -> dict[str, str]:
        env = {**os.environ, **dict.fromkeys(INHERITED_CREDENTIALS, ""), "CLAUDE_CONFIG_DIR": str(self._home)}
        return env

    def _check(self) -> dict[str, Any]:
        try:
            exe = self._exe_path()
        except AuthError as exc:
            return {"ready": False, "who": None, "problem": str(exc)}
        done = self._run([str(exe), "auth", "status", "--json"], env=self._env())
        try:
            data = json.loads(done.stdout) if done is not None and done.returncode == 0 else {}
        except ValueError:
            data = {}
        if not data.get("loggedIn"):
            return {"ready": False, "who": None}
        method = str(data.get("authMethod") or "").lower()
        if "claude.ai" in method or "claudeai" in method or "subscription" in method:
            return {"ready": False, "who": None,
                    "problem": "That is a Claude.ai subscription sign-in, which this app doesn't use. Sign in with your Console or SSO account."}
        who = data.get("email") or data.get("orgName") or data.get("organization") or None
        return {"ready": True, "who": str(who) if who else "Anthropic Console"}

    def status(self) -> dict[str, Any]:
        return self._cache.get(self._check)

    def engine_auth(self, app_settings: dict[str, Any]) -> EngineAuth:
        if not self.status()["ready"]:
            raise AuthError("Not signed in. Sign in under Settings.")
        return EngineAuth(env={"ANTHROPIC_BASE_URL": FIRST_PARTY_URL}, settings={"forceLoginMethod": "console"})

    def http_headers(self) -> dict[str, str] | None:
        return None  # the engine holds the login; there is nothing for the app to send itself

    def rejection(self) -> str:
        return "this sign-in"

    async def prepare(self) -> None:
        return None

    def sign_out(self) -> None:
        try:
            self._run([str(self._exe_path()), "auth", "logout"], env=self._env())
        except AuthError:
            pass
        self._cache.forget()

    async def begin_login(self) -> dict[str, Any]:
        config = self._get_settings()
        argv = [str(self._exe_path()), "auth", "login", "--console"]  # never --claudeai
        if config.get("console_sso"):
            argv.append("--sso")
        if config.get("console_email"):
            argv += ["--email", str(config["console_email"])]
        self._home.mkdir(parents=True, exist_ok=True)
        return await self._login.start(argv, self._env(), on_done=self._cache.forget)

    def login_state(self) -> dict[str, Any]:
        return self._login.state()

    def cancel_login(self) -> None:
        self._login.cancel()


class CloudMethod:
    """Amazon Bedrock, Google Cloud (Vertex AI) or Microsoft Foundry with the company's own cloud
    sign-in (aws sso login, gcloud, az login). The engine reads the cloud credentials itself."""

    id = CLOUD
    label = "Cloud provider (Bedrock / Vertex / Foundry)"

    def __init__(
        self,
        get_settings: Callable[[], dict[str, Any]],
        *,
        run: Runner = cli_login.run_quietly,
        which: Callable[[str], str | None] = shutil.which,
        login: cli_login.CliLogin | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._get_settings = get_settings
        self._run = run
        self._which = which
        self._login = login or cli_login.CliLogin()
        self._cache = _Cached(clock)

    def _provider(self) -> str:
        provider = str(self._get_settings().get("cloud_provider") or "bedrock")
        return provider if provider in CLOUD_PROVIDERS else "bedrock"

    def _tool(self, name: str) -> str:
        path = self._which(name)
        if path is None:
            raise AuthError(f"The {name} command-line tool is not installed on this PC.")
        return path

    def _identity_command(self) -> list[str]:
        config, provider = self._get_settings(), self._provider()
        if provider == "bedrock":
            argv = [self._tool("aws"), "sts", "get-caller-identity", "--output", "json"]
            return argv + (["--profile", config["cloud_profile"]] if config.get("cloud_profile") else [])
        if provider == "vertex":
            return [self._tool("gcloud"), "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"]
        return [self._tool("az"), "account", "show", "--query", "user.name", "--output", "tsv"]

    def _login_command(self) -> list[str]:
        config, provider = self._get_settings(), self._provider()
        if provider == "bedrock":
            if not config.get("cloud_profile"):
                raise AuthError("Enter the AWS profile (an SSO profile from `aws configure sso`) first.")
            return [self._tool("aws"), "sso", "login", "--profile", str(config["cloud_profile"])]
        if provider == "vertex":
            return [self._tool("gcloud"), "auth", "application-default", "login"]
        return [self._tool("az"), "login"]

    def _check(self) -> dict[str, Any]:
        try:
            argv = self._identity_command()
        except AuthError as exc:
            return {"ready": False, "who": None, "problem": str(exc)}
        done = self._run(argv, env=None)
        if done is None or done.returncode != 0 or not done.stdout.strip():
            return {"ready": False, "who": None}
        out = done.stdout.strip()
        if self._provider() == "bedrock":
            try:
                out = str(json.loads(out).get("Arn") or out)
            except ValueError:
                pass
        return {"ready": True, "who": out.splitlines()[0]}

    def status(self) -> dict[str, Any]:
        return self._cache.get(self._check)

    def engine_auth(self, app_settings: dict[str, Any]) -> EngineAuth:
        config, provider = app_settings, self._provider()
        if not self.status()["ready"]:
            raise AuthError("Not signed in to the cloud provider. Sign in under Settings.")
        env: dict[str, str] = {}
        settings: dict[str, Any] = {}
        if provider == "bedrock":
            env["CLAUDE_CODE_USE_BEDROCK"] = "1"
            if config.get("cloud_region"):
                env["AWS_REGION"] = config["cloud_region"]
            if config.get("cloud_profile"):
                env["AWS_PROFILE"] = config["cloud_profile"]
                # The engine runs this itself when the SSO session has expired.
                settings["awsAuthRefresh"] = f'"{self._tool("aws")}" sso login --profile {config["cloud_profile"]}'
        elif provider == "vertex":
            env["CLAUDE_CODE_USE_VERTEX"] = "1"
            if config.get("cloud_region"):
                env["CLOUD_ML_REGION"] = config["cloud_region"]
            if config.get("cloud_project"):
                env["ANTHROPIC_VERTEX_PROJECT_ID"] = config["cloud_project"]
        else:
            env["CLAUDE_CODE_USE_FOUNDRY"] = "1"
            if config.get("cloud_resource"):
                env["ANTHROPIC_FOUNDRY_RESOURCE"] = config["cloud_resource"]
        return EngineAuth(env=env, settings=settings)

    def http_headers(self) -> dict[str, str] | None:
        return None  # the provider's credentials aren't a header the app can send

    def rejection(self) -> str:
        return "this cloud sign-in"

    async def prepare(self) -> None:
        return None

    def sign_out(self) -> None:
        self._cache.forget()  # the cloud tools' own sign-in is theirs to end (aws sso logout, az logout)

    async def begin_login(self) -> dict[str, Any]:
        argv: Sequence[str] = self._login_command()
        return await self._login.start(argv, {**os.environ}, on_done=self._cache.forget)

    def login_state(self) -> dict[str, Any]:
        return self._login.state()

    def cancel_login(self) -> None:
        self._login.cancel()

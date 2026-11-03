"""Sign-in methods: how the assistant gets the credentials its LLM endpoint needs.

Each method says whether it is ready ("signed in"), what the agent engine needs to use it (its
environment and settings) and what an HTTP call to the endpoint -- the connection test and the
model list -- has to send. The agent, the Settings page and the model list use the active method
and know nothing about the others; a new way of signing in is a new class here.

Anthropic's terms (code.claude.com legal-and-compliance) shape what may be added: products on
the Agent SDK use API keys, a cloud provider's credentials or a Console sign-in, and must not offer
a Claude.ai (Pro / Max) login or collect Claude.ai credentials. So there is no such method.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend import credential_helper, oidc
from backend.auth_base import (
    ANTHROPIC_VERSION,
    FIRST_PARTY_URL,
    INHERITED_CREDENTIALS,
    AuthError,
    AuthMethod,
    EngineAuth,
)
from backend.auth_cli_methods import CLOUD, CONSOLE, CloudMethod, ConsoleMethod
from backend.secret_store import ApiKeyStore

__all__ = ["ANTHROPIC_VERSION", "FIRST_PARTY_URL", "INHERITED_CREDENTIALS", "AuthError", "AuthMethod", "EngineAuth"]

# The method used when the settings don't name one: what the app has always done.
DEFAULT_METHOD = "api_key"
GATEWAY_SSO = "gateway_sso"
METHOD_IDS = (DEFAULT_METHOD, GATEWAY_SSO, CONSOLE, CLOUD)
# How long the engine may reuse the token its helper printed before asking again (milliseconds);
# shorter than oidc.EXPIRY_MARGIN_S, which is what makes that safe.
HELPER_TTL_MS = "120000"


class ApiKeyMethod:
    """A pasted API key (Anthropic's, or a gateway's such as Abacus's), kept with DPAPI."""

    id = "api_key"
    label = "API key"

    def __init__(self, api_keys: ApiKeyStore) -> None:
        self._keys = api_keys

    def status(self) -> dict[str, Any]:
        hint = self._keys.hint()
        return {"ready": hint is not None, "who": f"key ending {hint}" if hint else None}

    def engine_auth(self, app_settings: dict[str, Any]) -> EngineAuth:
        key = self._keys.get()
        if key is None:
            raise AuthError("No API key is set. Add one under Settings.")
        # A company gateway (e.g. Abacus) instead of api.anthropic.com.
        return EngineAuth(env={"ANTHROPIC_API_KEY": key,
                               "ANTHROPIC_BASE_URL": app_settings.get("base_url") or FIRST_PARTY_URL})

    def http_headers(self) -> dict[str, str] | None:
        key = self._keys.get()
        return {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION} if key else None

    def rejection(self) -> str:
        return "this API key"

    async def prepare(self) -> None:
        return None

    def sign_out(self) -> None:
        self._keys.clear()


@dataclass(frozen=True)
class HelperAddress:
    """Where the engine's credential helper asks for the token, and the secret it must show."""

    url: str
    secret: str


class GatewaySsoMethod:
    """A company gateway (or identity provider) with SSO, by the OAuth device-code flow (oidc.py).

    The tokens stay in the app; the engine gets a token through its apiKeyHelper, so the app can
    refresh it behind the engine's back.
    """

    id = GATEWAY_SSO
    label = "Company sign-in (SSO)"

    def __init__(
        self,
        get_settings: Callable[[], dict[str, Any]],
        tokens: oidc.TokenStore,
        helper: HelperAddress,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._get_settings = get_settings
        self._tokens = tokens
        self._helper = helper
        self._clock = clock
        self._login = oidc.LoginManager()

    def _config(self) -> dict[str, Any]:
        return self._get_settings()

    def status(self) -> dict[str, Any]:
        data = self._tokens.load()
        if data is None:
            return {"ready": False, "who": None}
        usable = float(data.get("expires_at") or 0) > self._clock() or bool(data.get("refresh_token"))
        return {"ready": usable, "who": data.get("who")}

    async def current_token(self) -> str:
        """A token good for a while, refreshed if it is about to end."""
        token = self._tokens.fresh_access_token()
        if token:
            return token
        data = self._tokens.load()
        if data is None:
            raise AuthError("Not signed in. Sign in under Settings.")
        if not data.get("refresh_token"):
            raise AuthError("The sign-in has expired. Sign in again under Settings.")
        config = self._config()
        try:
            endpoints = await oidc.resolve_endpoints(config)
            new = await oidc.refresh_tokens(endpoints, config.get("oidc_client_id") or "", str(data["refresh_token"]))
        except oidc.OidcError as exc:
            raise AuthError(str(exc)) from exc
        self._tokens.save(new, previous=data)
        return str(new["access_token"])

    async def prepare(self) -> None:
        if self._tokens.load() is not None:
            try:
                await self.current_token()
            except AuthError:
                pass  # the call that follows reports it

    def engine_auth(self, app_settings: dict[str, Any]) -> EngineAuth:
        if not self.status()["ready"]:
            raise AuthError("Not signed in. Sign in under Settings.")
        env = {
            credential_helper.URL_ENV: self._helper.url,
            credential_helper.SECRET_ENV: self._helper.secret,
            "CLAUDE_CODE_API_KEY_HELPER_TTL_MS": HELPER_TTL_MS,
            "ANTHROPIC_BASE_URL": app_settings.get("base_url") or FIRST_PARTY_URL,
        }
        return EngineAuth(env=env, settings={"apiKeyHelper": self.helper_command()})

    @staticmethod
    def helper_command() -> str:
        script = Path(credential_helper.__file__).resolve()
        return f'"{sys.executable}" "{script}"'

    def http_headers(self) -> dict[str, str] | None:
        token = self._tokens.fresh_access_token()
        if token is None:
            return None
        if self._config().get("oidc_header") == "x-api-key":
            return {"x-api-key": token, "anthropic-version": ANTHROPIC_VERSION}
        return {"Authorization": f"Bearer {token}", "anthropic-version": ANTHROPIC_VERSION}

    def rejection(self) -> str:
        return "this sign-in"

    def sign_out(self) -> None:
        self._tokens.clear()

    async def begin_login(self) -> dict[str, Any]:
        """Start the device-code sign-in; the tokens are saved when the user finishes in the browser."""
        config = self._config()
        client_id = config.get("oidc_client_id") or ""
        if not client_id:
            raise oidc.OidcError("Enter the client ID under Settings > Sign-in.")
        endpoints = await oidc.resolve_endpoints(config)
        return await self._login.start(endpoints, client_id, config.get("oidc_scopes") or "",
                                       lambda tokens: self._tokens.save(tokens))

    def login_state(self) -> dict[str, Any]:
        return self._login.state()

    def cancel_login(self) -> None:
        self._login.cancel()


class AuthMethods:
    """The methods this app can sign in with, and the one the settings name."""

    def __init__(
        self,
        api_keys: ApiKeyStore,
        *,
        get_settings: Callable[[], dict[str, Any]] | None = None,
        oidc_tokens: oidc.TokenStore | None = None,
        helper: HelperAddress | None = None,
        engine_home: Path | None = None,
    ) -> None:
        self._methods: dict[str, AuthMethod] = {ApiKeyMethod.id: ApiKeyMethod(api_keys)}
        if get_settings is not None and oidc_tokens is not None and helper is not None:
            self._methods[GATEWAY_SSO] = GatewaySsoMethod(get_settings, oidc_tokens, helper)
        if get_settings is not None and engine_home is not None:
            self._methods[CONSOLE] = ConsoleMethod(get_settings, engine_home)
            self._methods[CLOUD] = CloudMethod(get_settings)

    def get(self, method_id: str) -> AuthMethod | None:
        return self._methods.get(method_id)

    def active(self, app_settings: dict[str, Any]) -> AuthMethod:
        return self._methods.get(str(app_settings.get("auth_method") or DEFAULT_METHOD), self._methods[DEFAULT_METHOD])

    def choices(self) -> list[dict[str, str]]:
        return [{"id": m.id, "label": m.label} for m in self._methods.values()]

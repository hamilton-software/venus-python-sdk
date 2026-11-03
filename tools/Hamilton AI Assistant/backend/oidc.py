"""OAuth 2.0 device-code sign-in (RFC 8628) for a company gateway.

The same pattern Abacus's own VS Code extension uses: the app asks the issuer for a device code,
the user opens a verification page in the browser (the code is filled in) and signs in with the
company's SSO, and the app polls the token endpoint until the sign-in completes. The tokens are
kept with DPAPI (TokenStore) and refreshed here, so the agent engine -- which gets a token from
the app through its apiKeyHelper (credential_helper.py) -- keeps working past one token's life.

This is for a gateway or identity provider the customer runs (or Abacus, once its endpoints are
known). It is not a way into Claude.ai accounts, and nothing here touches Anthropic's own sign-in.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.secret_store import SecretStore

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
TIMEOUT_S = 20.0
# A token this close to its end is refreshed first. It should be longer than the time the engine may
# reuse the token its helper printed (auth_methods.HELPER_TTL_MS), or the engine could still be
# sending a token that has just expired. For a token that lives only a few minutes the margin is
# a quarter of its life instead, so it is never "stale" from the moment it is issued.
EXPIRY_MARGIN_S = 180
SHORT_LIFE_FRACTION = 0.25
MIN_INTERVAL_S = 1.0


class OidcError(RuntimeError):
    """The sign-in failed or can't be done; the message is for the user."""


@dataclass(frozen=True)
class Endpoints:
    device: str
    token: str


@dataclass(frozen=True)
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    interval: int


def _error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return str(body.get("error_description") or body.get("error") or resp.text)[:200]
    except (ValueError, AttributeError):
        return resp.text[:200]


async def resolve_endpoints(config: dict[str, Any]) -> Endpoints:
    """The device-authorization and token endpoints: the two set explicitly, else the issuer's
    OpenID discovery document."""
    device, token = config.get("oidc_device_endpoint") or "", config.get("oidc_token_endpoint") or ""
    if device and token:
        return Endpoints(device, token)
    issuer = config.get("oidc_issuer") or ""
    if not issuer:
        raise OidcError("Enter the issuer (or the device and token endpoints) under Settings > Sign-in.")
    url = issuer if issuer.endswith("openid-configuration") else issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            doc = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcError(f"Could not read {url} ({exc.__class__.__name__}). Check the issuer, or enter the endpoints.") from exc
    device = device or str(doc.get("device_authorization_endpoint") or "")
    token = token or str(doc.get("token_endpoint") or "")
    if not device or not token:
        raise OidcError(f"{url} does not offer device sign-in. Enter the device and token endpoints instead.")
    return Endpoints(device, token)


async def request_device_code(endpoints: Endpoints, client_id: str, scopes: str) -> DeviceCode:
    data = {"client_id": client_id}
    if scopes:
        data["scope"] = scopes
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.post(endpoints.device, data=data)
    except httpx.HTTPError as exc:
        raise OidcError(f"Could not reach {endpoints.device} ({exc.__class__.__name__}).") from exc
    if resp.status_code != 200:
        raise OidcError(f"The sign-in service refused the request: {_error(resp)}")
    body = resp.json()
    try:
        return DeviceCode(
            device_code=str(body["device_code"]),
            user_code=str(body["user_code"]),
            verification_uri=str(body.get("verification_uri") or body["verification_url"]),
            verification_uri_complete=body.get("verification_uri_complete") or None,
            expires_in=int(body.get("expires_in") or 600),
            interval=max(int(body.get("interval") or 5), 1),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OidcError("The sign-in service's answer was not a device code.") from exc


async def poll_for_tokens(
    endpoints: Endpoints,
    client_id: str,
    code: DeviceCode,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Wait for the user to finish in the browser; returns the token response."""
    deadline = clock() + code.expires_in
    interval = max(float(code.interval), MIN_INTERVAL_S)
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        while clock() < deadline:
            await sleep(interval)
            try:
                resp = await client.post(endpoints.token, data={
                    "grant_type": DEVICE_GRANT, "device_code": code.device_code, "client_id": client_id})
            except httpx.HTTPError as exc:
                raise OidcError(f"Lost contact with {endpoints.token} ({exc.__class__.__name__}).") from exc
            if resp.status_code == 200:
                return resp.json()
            try:
                error = resp.json().get("error")
            except (ValueError, AttributeError):
                error = None
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            if error == "access_denied":
                raise OidcError("The sign-in was declined.")
            if error == "expired_token":
                break
            raise OidcError(f"The sign-in failed: {_error(resp)}")
    raise OidcError("The sign-in code expired before the sign-in was finished. Try again.")


async def refresh_tokens(endpoints: Endpoints, client_id: str, refresh_token: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.post(endpoints.token, data={
                "grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id})
    except httpx.HTTPError as exc:
        raise OidcError(f"Could not reach {endpoints.token} ({exc.__class__.__name__}).") from exc
    if resp.status_code != 200:
        raise OidcError(f"The sign-in has expired; sign in again ({_error(resp)}).")
    return resp.json()


def who_from(tokens: dict[str, Any]) -> str | None:
    """A name for 'signed in as', read (not verified) from the id token's claims -- display only."""
    for key in ("id_token", "access_token"):
        parts = str(tokens.get(key) or "").split(".")
        if len(parts) != 3:
            continue
        try:
            claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        except (ValueError, json.JSONDecodeError):
            continue
        for claim in ("email", "preferred_username", "upn", "name"):
            if isinstance(claims, dict) and claims.get(claim):
                return str(claims[claim])
    return None


class TokenStore:
    """The access / refresh tokens, DPAPI-encrypted as one JSON document."""

    def __init__(self, store: SecretStore, clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._clock = clock

    def load(self) -> dict[str, Any] | None:
        raw = self._store.get()
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            return None
        return data if isinstance(data, dict) and data.get("access_token") else None

    def save(self, tokens: dict[str, Any], *, who: str | None = None, previous: dict[str, Any] | None = None) -> None:
        old = previous or {}
        self._store.set(json.dumps({
            "access_token": tokens["access_token"],
            # A refresh that returns no new refresh token keeps the old one.
            "refresh_token": tokens.get("refresh_token") or old.get("refresh_token"),
            "expires_at": self._clock() + float(tokens.get("expires_in") or 3600),
            "lifetime": float(tokens.get("expires_in") or 3600),
            "who": who or who_from(tokens) or old.get("who"),
        }))

    def clear(self) -> None:
        self._store.clear()

    def fresh_access_token(self) -> str | None:
        """The stored access token if it is still good for a while, else None."""
        data = self.load()
        if not data:
            return None
        lifetime = float(data.get("lifetime") or 3600)
        margin = min(EXPIRY_MARGIN_S, lifetime * SHORT_LIFE_FRACTION)
        if float(data.get("expires_at") or 0) - margin > self._clock():
            return str(data["access_token"])
        return None


class LoginManager:
    """One sign-in at a time: the page starts it, shows the code, and polls state()."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._state: dict[str, Any] = {"state": "idle"}

    def state(self) -> dict[str, Any]:
        return dict(self._state)

    async def start(
        self,
        endpoints: Endpoints,
        client_id: str,
        scopes: str,
        on_tokens: Callable[[dict[str, Any]], None],
        *,
        poll: Callable[..., Awaitable[dict[str, Any]]] = poll_for_tokens,
    ) -> dict[str, Any]:
        self.cancel()
        code = await request_device_code(endpoints, client_id, scopes)
        self._state = {
            "state": "waiting", "user_code": code.user_code, "verification_uri": code.verification_uri,
            "verification_uri_complete": code.verification_uri_complete, "expires_in": code.expires_in,
        }
        self._task = asyncio.create_task(self._wait(endpoints, client_id, code, on_tokens, poll))
        return self.state()

    async def _wait(self, endpoints, client_id, code, on_tokens, poll) -> None:
        shown = {k: v for k, v in self._state.items() if k != "state"}
        try:
            tokens = await poll(endpoints, client_id, code)
            on_tokens(tokens)
            self._state = {"state": "done", "message": "Signed in."}
        except OidcError as exc:
            self._state = {"state": "error", "message": str(exc), **shown}
        except asyncio.CancelledError:
            self._state = {"state": "cancelled", "message": "Sign-in cancelled."}
            raise
        except Exception as exc:  # noqa: BLE001 - whatever went wrong, the page gets a message, not a hung spinner
            self._state = {"state": "error", "message": f"The sign-in failed ({exc.__class__.__name__}).", **shown}

    def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        if self._state.get("state") == "waiting":
            self._state = {"state": "cancelled", "message": "Sign-in cancelled."}


def validate_url(value: str, what: str) -> str:
    """'' or an https URL (http only for this PC, so a local test issuer works)."""
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme not in ("http", "https") or not parsed.hostname or (parsed.scheme == "http" and not local):
        raise ValueError(f"The {what} must be an https:// address.")
    return value.rstrip("/")

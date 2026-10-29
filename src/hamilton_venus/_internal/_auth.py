"""Internal helpers for secure VENUS endpoint authentication."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx

from hamilton_venus.config import AuthConfig
from hamilton_venus.exceptions import VenusAuthenticationError

_logger = logging.getLogger(__name__)
_TOKEN_GRANT_TYPE = "password"


class _AuthHeadersProvider(Protocol):
    """Internal protocol for components that can supply bearer auth headers."""

    async def get_auth_headers(self) -> dict[str, str]: ...

    async def force_refresh(self) -> dict[str, str]: ...

    async def aclose(self) -> None: ...


async def _merge_auth_headers(
    headers: dict[str, str] | None,
    auth_provider: _AuthHeadersProvider | None,
    *,
    force_auth_refresh: bool = False,
) -> dict[str, str] | None:
    merged_headers = dict(headers or {})
    if auth_provider is not None:
        auth_headers = (
            await auth_provider.force_refresh() if force_auth_refresh else await auth_provider.get_auth_headers()
        )
        merged_headers.update(auth_headers)
    return merged_headers or None


@dataclass
class _CachedAccessToken:
    access_token: str
    token_type: str
    expires_at: float


class _AccessTokenProvider:
    """Acquire and cache access tokens for secure VENUS endpoints."""

    def __init__(
        self,
        auth: AuthConfig,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], float] | None = None,
        verify: bool | str = True,
    ) -> None:
        self._auth = auth
        self._timeout = timeout
        self._transport = transport
        self._now = now or time.monotonic
        self._verify = verify
        self._client: httpx.AsyncClient | None = None
        self._cached_token: _CachedAccessToken | None = None
        self._lock = asyncio.Lock()

    async def get_auth_headers(self) -> dict[str, str]:
        """Return a valid Authorization header for the configured auth flow."""
        token = await self._get_valid_token()
        headers = {"Authorization": f"{token.token_type} {token.access_token}"}
        _logger.debug("Using cached access token (expires_at=%.1f)", token.expires_at)
        return headers

    async def force_refresh(self) -> dict[str, str]:
        """Refresh the cached access token immediately and return auth headers."""
        _logger.debug("Force-refreshing access token")
        async with self._lock:
            self._cached_token = await self._fetch_token()
            return {"Authorization": f"{self._cached_token.token_type} {self._cached_token.access_token}"}

    async def aclose(self) -> None:
        """Close the underlying HTTP client if one was created."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _get_valid_token(self) -> _CachedAccessToken:
        cached_token = self._cached_token
        if cached_token is not None and not self._is_expiring(cached_token):
            return cached_token

        async with self._lock:
            cached_token = self._cached_token
            if cached_token is not None and not self._is_expiring(cached_token):
                return cached_token
            self._cached_token = await self._fetch_token()
            return self._cached_token

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                verify=self._verify,
            )
        return self._client

    def _is_expiring(self, token: _CachedAccessToken) -> bool:
        return (token.expires_at - self._now()) <= self._auth.refresh_skew_seconds

    async def _fetch_token(self) -> _CachedAccessToken:
        client = self._get_client()
        _logger.debug("Requesting access token from %s", self._auth.token_url)
        try:
            response = await client.post(
                self._auth.token_url,
                data={
                    "grant_type": _TOKEN_GRANT_TYPE,
                    "username": self._auth.username,
                    "password": self._auth.password,
                    "client_id": self._auth.client_id,
                    "client_secret": self._auth.client_secret,
                    "scope": self._auth.scope,
                },
            )
        except httpx.ConnectError as exc:
            raise VenusAuthenticationError(
                f"Cannot connect to identity provider at {self._auth.token_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise VenusAuthenticationError(
                f"Identity provider at {self._auth.token_url} did not respond within timeout: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise VenusAuthenticationError(f"Token request failed: {exc}") from exc

        if not response.is_success:
            _logger.debug("Token request failed with HTTP %d: %s", response.status_code, response.text)
            raise VenusAuthenticationError(f"Token request failed (HTTP {response.status_code})")

        try:
            payload = response.json()
        except ValueError as exc:
            raise VenusAuthenticationError("Token endpoint returned invalid JSON") from exc

        _logger.debug(
            "Token response keys: %s, token_type=%r, expires_in=%r",
            list(payload.keys()),
            payload.get("token_type"),
            payload.get("expires_in"),
        )

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise VenusAuthenticationError("Token response did not include a valid access_token")

        raw_token_type = payload.get("token_type", "Bearer")
        if not isinstance(raw_token_type, str) or not raw_token_type:
            raise VenusAuthenticationError("Token response did not include a valid token_type")

        token_type = "Bearer" if raw_token_type.lower() == "bearer" else raw_token_type
        if raw_token_type != token_type:
            _logger.debug("Normalized token_type %r -> %r", raw_token_type, token_type)

        expires_in = payload.get("expires_in")
        try:
            expires_in_seconds = int(expires_in)
        except (TypeError, ValueError) as exc:
            raise VenusAuthenticationError("Token response did not include a valid expires_in value") from exc
        if expires_in_seconds <= 0:
            raise VenusAuthenticationError("Token response expires_in value must be greater than 0")

        _logger.debug(
            "Acquired access token: type=%s, expires_in=%ds, token=%.8s...",
            token_type,
            expires_in_seconds,
            access_token,
        )

        return _CachedAccessToken(
            access_token=access_token,
            token_type=token_type,
            expires_at=self._now() + expires_in_seconds,
        )


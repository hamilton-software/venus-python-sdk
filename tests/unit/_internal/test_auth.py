"""Unit tests for hamilton_venus._auth."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import httpx
import pytest

from hamilton_venus._internal._auth import _AccessTokenProvider
from hamilton_venus.config import AuthConfig
from hamilton_venus.exceptions import VenusAuthenticationError


class TestAccessTokenProvider:
    @pytest.mark.asyncio
    async def test_requests_and_caches_access_token(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            form_data = parse_qs(request.content.decode())
            assert request.method == "POST"
            assert str(request.url) == "https://identity.example/api/vector/v1/authorization/token"
            assert form_data["grant_type"] == ["password"]
            assert form_data["username"] == ["venus-user"]
            assert form_data["password"] == ["venus-pass"]
            assert form_data["client_id"] == ["Venus"]
            assert form_data["client_secret"] == ["venus_secret"]
            assert form_data["scope"] == ["openid"]
            return httpx.Response(
                200,
                json={"access_token": "token-1", "token_type": "Bearer", "expires_in": 300},
            )

        provider = _AccessTokenProvider(
            AuthConfig(
                token_url="https://identity.example/api/vector/v1/authorization/token",
                username="venus-user",
                password="venus-pass",
            ),
            transport=httpx.MockTransport(handler),
        )

        headers_1 = await provider.get_auth_headers()
        headers_2 = await provider.get_auth_headers()
        await provider.aclose()

        assert headers_1 == {"Authorization": "Bearer token-1"}
        assert headers_2 == {"Authorization": "Bearer token-1"}
        assert len(requests) == 1

    @pytest.mark.asyncio
    async def test_refreshes_cached_token_when_expiring(self):
        call_count = 0
        current_time = 0.0

        def now() -> float:
            return current_time

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"token-{call_count}",
                    "token_type": "Bearer",
                    "expires_in": 120,
                },
            )

        provider = _AccessTokenProvider(
            AuthConfig(
                token_url="https://identity.example/api/vector/v1/authorization/token",
                username="venus-user",
                password="venus-pass",
                refresh_skew_seconds=60,
            ),
            transport=httpx.MockTransport(handler),
            now=now,
        )

        headers_1 = await provider.get_auth_headers()
        current_time = 70.0
        headers_2 = await provider.get_auth_headers()
        await provider.aclose()

        assert headers_1 == {"Authorization": "Bearer token-1"}
        assert headers_2 == {"Authorization": "Bearer token-2"}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_force_refresh_replaces_cached_token(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"token-{call_count}",
                    "token_type": "Bearer",
                    "expires_in": 300,
                },
            )

        provider = _AccessTokenProvider(
            AuthConfig(
                token_url="https://identity.example/api/vector/v1/authorization/token",
                username="venus-user",
                password="venus-pass",
            ),
            transport=httpx.MockTransport(handler),
        )

        headers_1 = await provider.get_auth_headers()
        headers_2 = await provider.force_refresh()
        await provider.aclose()

        assert headers_1 == {"Authorization": "Bearer token-1"}
        assert headers_2 == {"Authorization": "Bearer token-2"}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_non_success_response_raises_authentication_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "invalid_grant"})

        provider = _AccessTokenProvider(
            AuthConfig(
                token_url="https://identity.example/api/vector/v1/authorization/token",
                username="venus-user",
                password="venus-pass",
            ),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(VenusAuthenticationError, match="HTTP 401"):
            await provider.get_auth_headers()
        await provider.aclose()

    @pytest.mark.asyncio
    async def test_invalid_payload_raises_authentication_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"token_type": "Bearer", "expires_in": 300})

        provider = _AccessTokenProvider(
            AuthConfig(
                token_url="https://identity.example/api/vector/v1/authorization/token",
                username="venus-user",
                password="venus-pass",
            ),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(VenusAuthenticationError, match="access_token"):
            await provider.get_auth_headers()
        await provider.aclose()

    @pytest.mark.asyncio
    async def test_connect_error_raises_authentication_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        provider = _AccessTokenProvider(
            AuthConfig(
                token_url="https://identity.example/api/vector/v1/authorization/token",
                username="venus-user",
                password="venus-pass",
            ),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(VenusAuthenticationError, match="Cannot connect to identity provider"):
            await provider.get_auth_headers()
        await provider.aclose()

    @pytest.mark.asyncio
    async def test_timeout_raises_authentication_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("Request timed out")

        provider = _AccessTokenProvider(
            AuthConfig(
                token_url="https://identity.example/api/vector/v1/authorization/token",
                username="venus-user",
                password="venus-pass",
            ),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(VenusAuthenticationError, match="did not respond within timeout"):
            await provider.get_auth_headers()
        await provider.aclose()

    @pytest.mark.asyncio
    async def test_get_client_passes_verify_to_httpx_async_client(self):
        provider = _AccessTokenProvider(
            AuthConfig(
                token_url="https://identity.example/api/vector/v1/authorization/token",
                username="venus-user",
                password="venus-pass",
            ),
            verify="C:\\certs\\venus-ca.pem",
        )

        mock_client_factory = MagicMock()
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client_factory.return_value = mock_client

        with patch("hamilton_venus._internal._auth.httpx.AsyncClient", mock_client_factory):
            returned_client = provider._get_client()

        assert returned_client is mock_client
        assert mock_client_factory.call_args.kwargs["verify"] == "C:\\certs\\venus-ca.pem"

    @pytest.mark.asyncio
    async def test_normalizes_lowercase_bearer_token_type(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"access_token": "token-lc", "token_type": "bearer", "expires_in": 300},
            )

        provider = _AccessTokenProvider(
            AuthConfig(
                token_url="https://identity.example/api/vector/v1/authorization/token",
                username="venus-user",
                password="venus-pass",
            ),
            transport=httpx.MockTransport(handler),
        )

        headers = await provider.get_auth_headers()
        await provider.aclose()

        assert headers == {"Authorization": "Bearer token-lc"}

    @pytest.mark.asyncio
    async def test_preserves_non_bearer_token_type(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"access_token": "token-mac", "token_type": "MAC", "expires_in": 300},
            )

        provider = _AccessTokenProvider(
            AuthConfig(
                token_url="https://identity.example/api/vector/v1/authorization/token",
                username="venus-user",
                password="venus-pass",
            ),
            transport=httpx.MockTransport(handler),
        )

        headers = await provider.get_auth_headers()
        await provider.aclose()

        assert headers == {"Authorization": "MAC token-mac"}

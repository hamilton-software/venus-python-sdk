"""Shared test utilities and fixtures for Hamilton VENUS SDK tests."""

from __future__ import annotations

import json
from typing import Any

import httpx


def mock_response(status_code: int = 200, json_data: Any = None, text: str = "") -> httpx.Response:
    """Create a mock httpx.Response for testing.

    Parameters
    ----------
    status_code:
        HTTP status code. Defaults to 200.
    json_data:
        JSON data to encode in response body. If provided, takes precedence over text.
    text:
        Text to encode in response body (used when json_data is None).

    Returns
    -------
    httpx.Response
        Mock response object with the specified parameters.
    """
    content = json.dumps(json_data).encode() if json_data is not None else text.encode()
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": "application/json"} if json_data is not None else {},
        request=httpx.Request("GET", "http://testserver"),
    )

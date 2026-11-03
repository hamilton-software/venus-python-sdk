"""The models the configured endpoint offers, for the Model picker in Settings.

Anthropic and Anthropic-compatible gateways (Abacus, ...) list them at GET /v1/models:
{"data": [{"id", "display_name", ...}], "has_more", "last_id"}. A gateway may offer many
non-Claude models too; Claude models come first, because the assistant is built and tested
with them. When the endpoint has no list (or can't be reached), the suggested names are used.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from backend.settings_store import SUGGESTED_MODELS

ANTHROPIC_URL = "https://api.anthropic.com"
CACHE_S = 300.0
MAX_PAGES = 10
TIMEOUT_S = 20.0

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def suggested(message: str) -> dict[str, Any]:
    return {
        "source": "suggested",
        "message": message,
        "models": [{"id": m, "name": m, "claude": True} for m in SUGGESTED_MODELS],
    }


def _sorted(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Claude models first, then the rest, each in the endpoint's own order (newest first for
    Anthropic). Duplicate ids are dropped."""
    seen: set[str] = set()
    models = []
    for entry in entries:
        model_id = str(entry.get("id") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        name = str(entry.get("display_name") or model_id)
        models.append({"id": model_id, "name": name, "claude": "claude" in model_id.lower()})
    return [m for m in models if m["claude"]] + [m for m in models if not m["claude"]]


async def list_models(base_url: str, headers: dict[str, str] | None, *, refresh: bool = False) -> dict[str, Any]:
    """{"source": "endpoint" | "suggested", "message", "models": [{"id", "name", "claude"}]}.
    *headers*: what the active sign-in method sends (None when not signed in yet)."""
    if not headers:
        return suggested("Sign in (or save an API key) to list the models your endpoint offers.")
    base = (base_url or ANTHROPIC_URL).rstrip("/")
    secret = next((v for k, v in headers.items() if k.lower() in ("x-api-key", "authorization")), "")
    key = f"{base}|{secret[-6:]}"
    cached = _cache.get(key)
    if cached and not refresh and time.monotonic() - cached[0] < CACHE_S:
        return cached[1]
    entries: list[dict[str, Any]] = []
    params: dict[str, Any] = {"limit": 1000}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            for _ in range(MAX_PAGES):
                resp = await client.get(f"{base}/v1/models", headers=headers, params=params)
                if resp.status_code != 200:
                    return suggested(f"{base} did not list its models (HTTP {resp.status_code}); type the model name.")
                body = resp.json()
                page = body.get("data") if isinstance(body, dict) else None
                if not isinstance(page, list):
                    return suggested(f"{base} did not list its models; type the model name.")
                entries.extend(e for e in page if isinstance(e, dict))
                if not body.get("has_more") or not body.get("last_id"):
                    break
                params = {"limit": 1000, "after_id": body["last_id"]}
    except (httpx.HTTPError, ValueError) as exc:
        return suggested(f"Could not reach {base} to list its models ({exc.__class__.__name__}); type the model name.")
    models = _sorted(entries)
    if not models:
        return suggested(f"{base} listed no models; type the model name.")
    result = {"source": "endpoint", "message": f"{len(models)} models from {base}.", "models": models}
    _cache[key] = (time.monotonic(), result)
    return result

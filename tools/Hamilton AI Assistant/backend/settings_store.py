"""JSON-file-backed store for the assistant's preferences.

Same pattern as the Log Viewer's settings_store.py: one flat dict, rewritten whole under a
lock on every change. The API key and the spoke / hub tokens are not kept here -- see
secret_store.py.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any
from urllib.parse import urlparse

from backend.auth_cli_methods import CLOUD_PROVIDERS
from backend.auth_methods import DEFAULT_METHOD, METHOD_IDS
from backend.config import BackendConfig
from backend.oidc import validate_url

# Suggested in Settings. Any model name the endpoint accepts can be typed instead: a company
# gateway (e.g. Abacus) may use its own names for the same Claude models.
SUGGESTED_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")

DEFAULT_SETTINGS: dict[str, Any] = {
    "model": SUGGESTED_MODELS[0],
    # Anthropic Messages API endpoint; "" means Anthropic itself (api.anthropic.com). Any
    # Anthropic-compatible endpoint works: a company gateway such as Abacus
    # (https://<company>.abacus.ai), AWS Bedrock / Google Vertex gateways, LiteLLM, ...
    "base_url": "",
    # How the assistant signs in to that endpoint (auth_methods.py): "api_key", ...
    "auth_method": DEFAULT_METHOD,
    # Company sign-in (SSO) by the device-code flow: the issuer (its OpenID discovery document
    # gives the endpoints) or the two endpoints themselves, the client ID the issuer gave this
    # app, the scopes, and which header the gateway reads the token from ("bearer": Authorization,
    # or "x-api-key").
    "oidc_issuer": "",
    "oidc_device_endpoint": "",
    "oidc_token_endpoint": "",
    "oidc_client_id": "",
    "oidc_scopes": "",
    "oidc_header": "bearer",
    # Anthropic Console / SSO sign-in (the engine's own): an email to pre-fill, and whether to force SSO.
    "console_email": "",
    "console_sso": False,
    # Cloud provider: "bedrock" | "vertex" | "foundry", its region, the AWS SSO profile, the
    # Google Cloud project and the Azure Foundry resource name.
    "cloud_provider": "bedrock",
    "cloud_region": "",
    "cloud_profile": "",
    "cloud_project": "",
    "cloud_resource": "",
    # Which hamilton-venus MCP server the agent uses: "local" starts the spoke on this PC
    # (stdio); "spoke" is a network spoke (mcp-guide Mode B), "hub" a hub (Mode C) -- each at
    # its http(s)://<pc>:8000/mcp URL with a bearer token.
    "connection": "local",
    "spoke_url": "",
    "hub_url": "",
    # Hub mode: which spoke's deck the viewer shows; "" follows the spoke the assistant is
    # working on.
    "hub_spoke": "",
    # Network spoke / hub only: the VENUS PC the deck viewer and status read (Vector API, port
    # 42400) when the spoke address's host can't reach it (VPN, ...); "" works it out from the
    # connection: the network spoke's PC, or the hub spoke's PC. This PC is always localhost.
    "deck_host": "",
}

CONNECTIONS = ("local", "spoke", "hub")

_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]*$")


def normalize_base_url(value: str) -> str:
    """'' for Anthropic, otherwise an http(s) origin without a trailing slash or /v1 (the
    engine appends /v1/messages itself)."""
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("The base URL must start with https:// (for example https://yourcompany.abacus.ai).")
    value = value.rstrip("/")
    if value.endswith("/v1"):
        value = value[: -len("/v1")]
    return value


def normalize_mcp_url(value: str) -> str:
    """'' or an http(s) MCP endpoint; a bare host or host:port gets the spokes' default port
    8000 and path /mcp."""
    value = value.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Enter the server's address, for example http://instrument-pc:8000/mcp.")
    netloc = parsed.netloc if parsed.port else f"{parsed.netloc}:8000"
    path = parsed.path.rstrip("/") or "/mcp"
    return f"{parsed.scheme}://{netloc}{path}"


def normalize_host(value: str) -> str:
    """'' or a bare host name / address for the deck viewer (no scheme, port or path)."""
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"http://{value}")
    if not parsed.hostname:
        raise ValueError("Enter the VENUS PC's name or address, for example instrument-pc.")
    return parsed.hostname


def normalize_model(value: str) -> str:
    value = value.strip()
    if not _MODEL_NAME.match(value):
        raise ValueError("Enter a model name, for example claude-sonnet-5-5.")
    return value


class SettingsStore:
    def __init__(self, config: BackendConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        config.settings_file.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self._config.settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {**DEFAULT_SETTINGS, **(data if isinstance(data, dict) else {})}

    def get(self) -> dict[str, Any]:
        with self._lock:
            return self._read()

    def update(self, **changes: Any) -> dict[str, Any]:
        if "model" in changes:
            changes["model"] = normalize_model(str(changes["model"]))
        if "base_url" in changes:
            changes["base_url"] = normalize_base_url(str(changes["base_url"]))
        if "auth_method" in changes and changes["auth_method"] not in METHOD_IDS:
            raise ValueError(f"auth_method must be one of {', '.join(METHOD_IDS)}.")
        for key, what in (("oidc_issuer", "issuer"), ("oidc_device_endpoint", "device endpoint"),
                          ("oidc_token_endpoint", "token endpoint")):
            if key in changes:
                changes[key] = validate_url(str(changes[key]), what)
        for key in ("oidc_client_id", "oidc_scopes"):
            if key in changes:
                changes[key] = " ".join(str(changes[key]).split())
        for key in ("console_email", "cloud_region", "cloud_profile", "cloud_project", "cloud_resource"):
            if key in changes:
                changes[key] = str(changes[key]).strip()
        if "console_sso" in changes:
            changes["console_sso"] = bool(changes["console_sso"])
        if "cloud_provider" in changes and changes["cloud_provider"] not in CLOUD_PROVIDERS:
            raise ValueError(f"cloud_provider must be one of {', '.join(CLOUD_PROVIDERS)}.")
        if "oidc_header" in changes and changes["oidc_header"] not in ("bearer", "x-api-key"):
            raise ValueError("oidc_header must be bearer or x-api-key.")
        if "connection" in changes and changes["connection"] not in CONNECTIONS:
            raise ValueError(f"connection must be one of {', '.join(CONNECTIONS)}.")
        for key in ("spoke_url", "hub_url"):
            if key in changes:
                changes[key] = normalize_mcp_url(str(changes[key]))
        if "deck_host" in changes:
            changes["deck_host"] = normalize_host(str(changes["deck_host"]))
        if "hub_spoke" in changes:
            changes["hub_spoke"] = str(changes["hub_spoke"]).strip()
        with self._lock:
            settings = self._read()
            settings.update({k: v for k, v in changes.items() if k in DEFAULT_SETTINGS})
            self._config.settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
            return settings

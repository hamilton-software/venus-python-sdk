"""SDK configuration — loaded from a TOML file or set programmatically."""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from hamilton_venus.error_handling.presets import BUILTIN_ERROR_PROFILE_NAMES

_logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:42400"
_DEFAULT_PARENT_WINDOW_HANDLE = 0
_DEFAULT_HTTP_TIMEOUT = 30.0
_DEFAULT_STARTUP_TIMEOUT = 300.0
_DEFAULT_DISCONNECT_TIMEOUT = 30.0
_DEFAULT_COMMAND_TIMEOUT = 300.0
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BACKOFF = 0.5
_DEFAULT_AUTH_CLIENT_ID = "Venus"
_DEFAULT_AUTH_CLIENT_SECRET = "venus_secret"
_DEFAULT_AUTH_SCOPE = "openid"
_DEFAULT_AUTH_REFRESH_SKEW_SECONDS = 60
_DEFAULT_AUTH_TOKEN_URL = "https://localhost:42431/api/vector/v1/authorization/token"
_DEFAULT_TLS_CA_BUNDLE_PATH = ""
_DEFAULT_STAR_AUTO_CONNECT = True
_DEFAULT_STAR_SHUTDOWN_TIMEOUT = 30.0
_DEFAULT_STAR_VENUS_TRACE_LOGGING = False

_VALID_SCHEMES = frozenset({"http", "https"})
_TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSY_ENV_VALUES = frozenset({"0", "false", "no", "off", ""})
_LOGGING_LEVEL_NAMES = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _validate_http_url(url: str, *, field_name: str) -> str:
    normalized = url.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in _VALID_SCHEMES:
        raise ValueError(
            f"Invalid {field_name} scheme {parsed.scheme!r} in {normalized!r}. "
            f"Expected one of: {', '.join(sorted(_VALID_SCHEMES))}"
        )
    if not parsed.hostname:
        raise ValueError(f"Invalid {field_name} {normalized!r}: missing hostname.")
    return normalized


def _get_env_string(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return value.strip()


def _parse_int_setting_value(value: Any, *, source: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Invalid integer value for {source}: {value!r}. Expected an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "":
            raise ValueError(f"Invalid integer value for {source}: {value!r}. Expected an integer.")
        try:
            return int(normalized)
        except ValueError as exc:
            raise ValueError(f"Invalid integer value for {source}: {value!r}. Expected an integer.") from exc
    raise ValueError(f"Invalid integer value for {source}: {value!r}. Expected an integer.")


def _parse_float_setting_value(value: Any, *, source: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"Invalid float value for {source}: {value!r}. Expected a number.")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "":
            raise ValueError(f"Invalid float value for {source}: {value!r}. Expected a number.")
        try:
            return float(normalized)
        except ValueError as exc:
            raise ValueError(f"Invalid float value for {source}: {value!r}. Expected a number.") from exc
    raise ValueError(f"Invalid float value for {source}: {value!r}. Expected a number.")


def _parse_optional_float_setting_value(value: Any, *, source: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "none", "null"}:
            return None
    return _parse_float_setting_value(value, source=source)


def _get_env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return _parse_int_setting_value(value, source=f"environment variable {name!r}")


def _get_env_float(name: str) -> float | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return _parse_float_setting_value(value, source=f"environment variable {name!r}")


def _get_env_optional_float(name: str) -> float | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return _parse_optional_float_setting_value(value, source=f"environment variable {name!r}")


def _resolve_string_setting(
    section: dict[str, Any], key: str, *, env_name: str | None = None, default: str = ""
) -> str:
    if env_name is not None:
        env_value = _get_env_string(env_name)
        if env_value is not None:
            return env_value
    return str(section.get(key, default))


def _resolve_secret_setting(section: dict[str, Any], key: str, *, env_name: str, default: str = "") -> str:
    return os.environ.get(env_name, str(section.get(key, default)))


def _parse_string_list_or_csv_setting_value(value: Any, *, source: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        parsed: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(
                    f"Invalid value for {source}: {value!r}. Expected list[str] or comma-separated string."
                )
            normalized = item.strip()
            if normalized:
                parsed.append(normalized)
        return parsed
    raise ValueError(
        f"Invalid value for {source}: {value!r}. Expected list[str] or comma-separated string."
    )


def _parse_logging_level_setting_value(value: Any, *, source: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(
            f"Invalid logging level for {source}: {value!r}. "
            "Expected one of DEBUG, INFO, WARNING, ERROR, CRITICAL, or a non-negative integer."
        )
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "":
            return None
        normalized_upper = normalized.upper()
        if normalized_upper in _LOGGING_LEVEL_NAMES:
            return _LOGGING_LEVEL_NAMES[normalized_upper]
        try:
            return int(normalized)
        except ValueError as exc:
            raise ValueError(
                f"Invalid logging level for {source}: {value!r}. "
                "Expected one of DEBUG, INFO, WARNING, ERROR, CRITICAL, or a non-negative integer."
            ) from exc
    raise ValueError(
        f"Invalid logging level for {source}: {value!r}. "
        "Expected one of DEBUG, INFO, WARNING, ERROR, CRITICAL, or a non-negative integer."
    )


def _resolve_int_setting(section: dict[str, Any], key: str, *, env_name: str | None = None, default: int = 0) -> int:
    if env_name is not None:
        env_value = _get_env_int(env_name)
        if env_value is not None:
            return env_value
    raw_value = section.get(key, default)
    return _parse_int_setting_value(raw_value, source=f"key {key!r}")


def _resolve_float_setting(
    section: dict[str, Any], key: str, *, env_name: str | None = None, default: float = 0.0
) -> float:
    if env_name is not None:
        env_value = _get_env_float(env_name)
        if env_value is not None:
            return env_value
    raw_value = section.get(key, default)
    return _parse_float_setting_value(raw_value, source=f"key {key!r}")


def _resolve_optional_float_setting(
    section: dict[str, Any], key: str, *, env_name: str | None = None, default: float | None = None
) -> float | None:
    if env_name is not None:
        env_value = _get_env_optional_float(env_name)
        if env_value is not None or os.environ.get(env_name) is not None:
            return env_value
    raw_value = section.get(key, default)
    return _parse_optional_float_setting_value(raw_value, source=f"key {key!r}")


def _resolve_bool_setting(
    section: dict[str, Any], key: str, *, env_name: str | None = None, default: bool = False
) -> bool:
    """Resolve a boolean setting from environment variable or TOML config.

    Environment variables accept: 1, true, yes, on (truthy) or 0, false, no, off, empty (falsy).
    Invalid environment variable values raise ValueError with helpful guidance.
    TOML values must be actual booleans.
    """
    if env_name is not None:
        env_value = _get_env_string(env_name)
        if env_value is not None:
            env_lower = env_value.lower()
            if env_lower in _TRUTHY_ENV_VALUES:
                return True
            if env_lower in _FALSY_ENV_VALUES:
                return False
            # Invalid environment variable value
            raise ValueError(
                f"Invalid boolean value for environment variable {env_name!r}: {env_value!r}. "
                f"Allowed values: {', '.join(sorted(_TRUTHY_ENV_VALUES))} (true) or "
                f"{', '.join(sorted(_FALSY_ENV_VALUES))} (false)."
            )
    value = section.get(key, default)
    if isinstance(value, bool):
        return value
    if value is not default:
        raise ValueError(f"Invalid boolean value for key {key!r}: {value!r}. Expected a boolean.")
    return bool(default)


@dataclass
class TimeoutConfig:
    """Timeout settings in seconds."""

    http: float = _DEFAULT_HTTP_TIMEOUT
    startup: float = _DEFAULT_STARTUP_TIMEOUT
    disconnect: float = _DEFAULT_DISCONNECT_TIMEOUT
    command: float | None = _DEFAULT_COMMAND_TIMEOUT

    def __post_init__(self) -> None:
        if self.http <= 0:
            raise ValueError("timeouts.http must be greater than 0")
        if self.startup <= 0:
            raise ValueError("timeouts.startup must be greater than 0")
        if self.disconnect <= 0:
            raise ValueError("timeouts.disconnect must be greater than 0")
        if self.command is not None and self.command <= 0:
            raise ValueError("timeouts.command must be greater than 0 when set")


@dataclass
class MethodConfig:
    """Configuration for method loading and execution."""

    parent_window_handle: int = _DEFAULT_PARENT_WINDOW_HANDLE
    method_display_name: str = ""
    # When True, the VENUS method skips its per-command status messages on the
    # "communication" run-message channel ("Command Received", "Pickup tips...",
    # "Command finished ..."). They are only recorded in the run log; skipping them
    # saves several of VENUS's own HTTP round trips on every command.
    disable_status_communication: bool = True
    # When True, the VENUS method stops posting its per-command busy/idle flag on the
    # "idle" run-message channel, and instrument_is_idle() answers from this client's
    # own state (no command in flight) instead of peeking that channel. Saves VENUS
    # its idle posts and queue trims on every command.
    disable_idle_communication: bool = True


@dataclass
class NetworkConfig:
    """Configuration for network requests and retries."""

    max_retries: int = _DEFAULT_MAX_RETRIES
    retry_backoff: float = _DEFAULT_RETRY_BACKOFF

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("network.max_retries must be greater than or equal to 0")
        if self.retry_backoff < 0:
            raise ValueError("network.retry_backoff must be greater than or equal to 0")


@dataclass
class AuthConfig:
    """Configuration for secure VENUS endpoint authentication.

    Authentication mode is always auto-detected from the server.
    Credentials can be provided here or via environment variables.
    """

    token_url: str = _DEFAULT_AUTH_TOKEN_URL
    username: str = ""
    password: str = ""
    client_id: str = _DEFAULT_AUTH_CLIENT_ID
    client_secret: str = _DEFAULT_AUTH_CLIENT_SECRET
    scope: str = _DEFAULT_AUTH_SCOPE
    refresh_skew_seconds: int = _DEFAULT_AUTH_REFRESH_SKEW_SECONDS

    def __post_init__(self) -> None:
        self.token_url = _validate_http_url(self.token_url, field_name="token_url")
        self.username = self.username.strip()
        self.client_id = self.client_id.strip()
        self.client_secret = self.client_secret.strip()
        self.scope = self.scope.strip()

        if self.refresh_skew_seconds < 0:
            raise ValueError("auth.refresh_skew_seconds must be greater than or equal to 0")

    def validate_credentials(self) -> None:
        """Validate that required auth credentials are provided."""
        missing = [
            name
            for name, value in (
                ("username", self.username),
                ("password", self.password),
            )
            if not value
        ]
        if missing:
            raise ValueError("Required authentication credentials are missing: " + ", ".join(missing))


@dataclass
class TlsConfig:
    """Configuration for TLS/SSL connections."""

    ca_bundle_path: str = _DEFAULT_TLS_CA_BUNDLE_PATH

    def __post_init__(self) -> None:
        self.ca_bundle_path = self.ca_bundle_path.strip()
        if self.ca_bundle_path and not Path(self.ca_bundle_path).is_file():
            raise FileNotFoundError(f"TLS CA bundle not found: {self.ca_bundle_path}")

    @property
    def verify(self) -> bool | str:
        return self.ca_bundle_path or True


def _load_auth_config(auth_section: dict[str, Any]) -> AuthConfig:
    return AuthConfig(
        token_url=_resolve_string_setting(
            auth_section,
            "token_url",
            env_name="HAMILTON_VENUS_AUTH_TOKEN_URL",
            default=_DEFAULT_AUTH_TOKEN_URL,
        ),
        username=_resolve_string_setting(auth_section, "username", env_name="HAMILTON_VENUS_AUTH_USERNAME"),
        password=_resolve_secret_setting(auth_section, "password", env_name="HAMILTON_VENUS_AUTH_PASSWORD"),
        client_id=_resolve_string_setting(
            auth_section,
            "client_id",
            env_name="HAMILTON_VENUS_AUTH_CLIENT_ID",
            default=_DEFAULT_AUTH_CLIENT_ID,
        ),
        client_secret=_resolve_secret_setting(
            auth_section,
            "client_secret",
            env_name="HAMILTON_VENUS_AUTH_CLIENT_SECRET",
            default=_DEFAULT_AUTH_CLIENT_SECRET,
        ),
        scope=_resolve_string_setting(
            auth_section,
            "scope",
            env_name="HAMILTON_VENUS_AUTH_SCOPE",
            default=_DEFAULT_AUTH_SCOPE,
        ),
        refresh_skew_seconds=_resolve_int_setting(
            auth_section,
            "refresh_skew_seconds",
            env_name="HAMILTON_VENUS_AUTH_REFRESH_SKEW_SECONDS",
            default=_DEFAULT_AUTH_REFRESH_SKEW_SECONDS,
        ),
    )


def _load_tls_config(tls_section: dict[str, Any]) -> TlsConfig:
    return TlsConfig(
        ca_bundle_path=_resolve_string_setting(
            tls_section,
            "ca_bundle_path",
            env_name="HAMILTON_VENUS_TLS_CA_BUNDLE",
            default=_DEFAULT_TLS_CA_BUNDLE_PATH,
        ),
    )


def _env_bool_default(env_name: str, default: bool) -> Callable[[], bool]:
    """A dataclass ``default_factory`` that reads *env_name* (as
    :func:`_resolve_bool_setting` does) and falls back to *default*."""
    return lambda: _resolve_bool_setting({}, env_name, env_name=env_name, default=default)


@dataclass
class RunLogConfig:
    """Configuration for the structured JSON run log.

    The run log is on by default (``enabled``) and is written to VENUS's
    ``LogFiles`` directory: ``output_dir`` left empty uses the directory the
    registry records (``HKLM\\SOFTWARE\\WOW6432Node\\Phoenix\\Directories\\Logfiles``),
    else ``C:\\Program Files (x86)\\Hamilton\\Logfiles``, else -- when that
    cannot be written -- the working directory.

    ``include_com_trace`` (default on) additionally embeds VENUS's firmware
    communication trace: the bytes appended to the day's ``.trc`` file
    between the client's ``__enter__`` and ``__exit__`` are captured into
    ``com_trace`` log entries. ``com_trace_logfiles_dir`` sets the directory
    that file lives in; left empty, the SDK asks VENUS
    (``GET /api/vector/v3/system/paths``) and falls back to the same
    ``LogFiles`` directory as ``output_dir``. ``com_trace_max_bytes``
    caps the total captured (0 = unlimited); when the trace is larger, the
    newest lines are kept.

    The ``enabled`` and ``include_com_trace`` defaults honour
    ``HAMILTON_VENUS_RUN_LOG_ENABLED`` and ``HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE``,
    also for a ``RunLogConfig`` built in code without a value for them.
    """

    enabled: bool = field(default_factory=_env_bool_default("HAMILTON_VENUS_RUN_LOG_ENABLED", True))
    output_dir: str = ""
    console_capture: bool = True
    include_http: bool = True
    include_signalr: bool = True
    include_cmd_comms: bool = True
    redact_auth: bool = True
    signalr_event_filter: list[str] = field(default_factory=list)
    max_payload_bytes: int = 1_048_576
    include_com_trace: bool = field(
        default_factory=_env_bool_default("HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE", True)
    )
    com_trace_logfiles_dir: str = ""
    com_trace_max_bytes: int = 5_242_880

    def __post_init__(self) -> None:
        if self.max_payload_bytes < 0:
            raise ValueError("run_log.max_payload_bytes must be greater than or equal to 0")
        if self.com_trace_max_bytes < 0:
            raise ValueError("run_log.com_trace_max_bytes must be greater than or equal to 0")


@dataclass
class StarClientConfig:
    """Default settings for StarClient runtime behavior."""

    auto_connect: bool = _DEFAULT_STAR_AUTO_CONNECT
    shutdown_timeout: float = _DEFAULT_STAR_SHUTDOWN_TIMEOUT
    logging_level: int | None = None
    venus_trace_logging: bool = _DEFAULT_STAR_VENUS_TRACE_LOGGING
    error_profile_name: str = "standard"
    error_profile_path: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.shutdown_timeout, bool) or not isinstance(self.shutdown_timeout, int | float):
            raise TypeError("star_client.shutdown_timeout must be a number greater than 0")
        if self.shutdown_timeout <= 0:
            raise ValueError("star_client.shutdown_timeout must be greater than 0")
        if self.logging_level is not None:
            if isinstance(self.logging_level, bool) or not isinstance(self.logging_level, int):
                raise TypeError("star_client.logging_level must be an int greater than or equal to 0, or None")
            if self.logging_level < 0:
                raise ValueError("star_client.logging_level must be greater than or equal to 0")
        self.error_profile_name = self.error_profile_name.strip().lower()
        self.error_profile_path = self.error_profile_path.strip()
        if self.error_profile_path:
            if not Path(self.error_profile_path).is_file():
                raise FileNotFoundError(f"star_client.error_profile_path not found: {self.error_profile_path}")
            return
        if self.error_profile_name not in BUILTIN_ERROR_PROFILE_NAMES:
            supported = ", ".join(sorted(BUILTIN_ERROR_PROFILE_NAMES))
            raise ValueError(
                "Unsupported star_client.error_profile_name "
                f"{self.error_profile_name!r}. Supported values: {supported}."
            )


@dataclass
class VantageClientConfig:
    """Default settings for VantageClient runtime behavior."""

    auto_connect: bool = _DEFAULT_STAR_AUTO_CONNECT
    shutdown_timeout: float = _DEFAULT_STAR_SHUTDOWN_TIMEOUT
    logging_level: int | None = None
    venus_trace_logging: bool = _DEFAULT_STAR_VENUS_TRACE_LOGGING
    error_profile_name: str = "standard"
    error_profile_path: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.shutdown_timeout, bool) or not isinstance(self.shutdown_timeout, int | float):
            raise TypeError("vantage_client.shutdown_timeout must be a number greater than 0")
        if self.shutdown_timeout <= 0:
            raise ValueError("vantage_client.shutdown_timeout must be greater than 0")
        if self.logging_level is not None:
            if isinstance(self.logging_level, bool) or not isinstance(self.logging_level, int):
                raise TypeError("vantage_client.logging_level must be an int greater than or equal to 0, or None")
            if self.logging_level < 0:
                raise ValueError("vantage_client.logging_level must be greater than or equal to 0")
        self.error_profile_name = self.error_profile_name.strip().lower()
        self.error_profile_path = self.error_profile_path.strip()
        if self.error_profile_path:
            if not Path(self.error_profile_path).is_file():
                raise FileNotFoundError(f"vantage_client.error_profile_path not found: {self.error_profile_path}")
            return
        if self.error_profile_name not in BUILTIN_ERROR_PROFILE_NAMES:
            supported = ", ".join(sorted(BUILTIN_ERROR_PROFILE_NAMES))
            raise ValueError(
                "Unsupported vantage_client.error_profile_name "
                f"{self.error_profile_name!r}. Supported values: {supported}."
            )


def _resolve_signalr_event_filter_setting(section: dict[str, Any], key: str) -> list[str]:
    raw_value = section.get(key, [])
    return _parse_string_list_or_csv_setting_value(raw_value, source=f"key {key!r}")


def _load_run_log_config(run_log_section: dict[str, Any]) -> RunLogConfig:
    signalr_filter_env = _get_env_string("HAMILTON_VENUS_RUN_LOG_SIGNALR_EVENT_FILTER")
    if signalr_filter_env is not None:
        signalr_event_filter = _parse_string_list_or_csv_setting_value(
            signalr_filter_env,
            source="environment variable 'HAMILTON_VENUS_RUN_LOG_SIGNALR_EVENT_FILTER'",
        )
    else:
        signalr_event_filter = _resolve_signalr_event_filter_setting(run_log_section, "signalr_event_filter")

    return RunLogConfig(
        enabled=_resolve_bool_setting(
            run_log_section, "enabled", env_name="HAMILTON_VENUS_RUN_LOG_ENABLED", default=True,
        ),
        output_dir=_resolve_string_setting(
            run_log_section, "output_dir", env_name="HAMILTON_VENUS_RUN_LOG_DIR", default="",
        ),
        console_capture=_resolve_bool_setting(
            run_log_section, "console_capture", env_name="HAMILTON_VENUS_RUN_LOG_CONSOLE_CAPTURE", default=True,
        ),
        include_http=_resolve_bool_setting(
            run_log_section, "include_http", env_name="HAMILTON_VENUS_RUN_LOG_INCLUDE_HTTP", default=True,
        ),
        include_signalr=_resolve_bool_setting(
            run_log_section, "include_signalr", env_name="HAMILTON_VENUS_RUN_LOG_INCLUDE_SIGNALR", default=True,
        ),
        include_cmd_comms=_resolve_bool_setting(
            run_log_section,
            "include_cmd_comms",
            env_name="HAMILTON_VENUS_RUN_LOG_INCLUDE_CMD_COMMS",
            default=True,
        ),
        redact_auth=_resolve_bool_setting(
            run_log_section, "redact_auth", env_name="HAMILTON_VENUS_RUN_LOG_REDACT_AUTH", default=True,
        ),
        signalr_event_filter=signalr_event_filter,
        max_payload_bytes=_resolve_int_setting(
            run_log_section,
            "max_payload_bytes",
            env_name="HAMILTON_VENUS_RUN_LOG_MAX_PAYLOAD_BYTES",
            default=1_048_576,
        ),
        include_com_trace=_resolve_bool_setting(
            run_log_section,
            "include_com_trace",
            env_name="HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE",
            default=True,
        ),
        com_trace_logfiles_dir=_resolve_string_setting(
            run_log_section,
            "com_trace_logfiles_dir",
            env_name="HAMILTON_VENUS_RUN_LOG_COM_TRACE_DIR",
            default="",
        ),
        com_trace_max_bytes=_resolve_int_setting(
            run_log_section,
            "com_trace_max_bytes",
            env_name="HAMILTON_VENUS_RUN_LOG_COM_TRACE_MAX_BYTES",
            default=5_242_880,
        ),
    )


def _load_method_config(method_section: dict[str, Any]) -> MethodConfig:
    return MethodConfig(
        parent_window_handle=_resolve_int_setting(
            method_section,
            "parent_window_handle",
            default=_DEFAULT_PARENT_WINDOW_HANDLE,
        ),
        method_display_name=_resolve_string_setting(
            method_section,
            "method_display_name",
            env_name="HAMILTON_VENUS_METHOD_DISPLAY_NAME",
            default="",
        ),
        disable_status_communication=_resolve_bool_setting(
            method_section,
            "disable_status_communication",
            env_name="HAMILTON_VENUS_METHOD_DISABLE_STATUS_COMMUNICATION",
            default=True,
        ),
        disable_idle_communication=_resolve_bool_setting(
            method_section,
            "disable_idle_communication",
            env_name="HAMILTON_VENUS_METHOD_DISABLE_IDLE_COMMUNICATION",
            default=True,
        ),
    )


def _load_network_config(network_section: dict[str, Any]) -> NetworkConfig:
    return NetworkConfig(
        max_retries=_resolve_int_setting(
            network_section,
            "max_retries",
            env_name="HAMILTON_VENUS_NETWORK_MAX_RETRIES",
            default=_DEFAULT_MAX_RETRIES,
        ),
        retry_backoff=_resolve_float_setting(
            network_section,
            "retry_backoff",
            env_name="HAMILTON_VENUS_NETWORK_RETRY_BACKOFF",
            default=_DEFAULT_RETRY_BACKOFF,
        ),
    )


def _load_timeouts_config(timeout_section: dict[str, Any]) -> TimeoutConfig:
    return TimeoutConfig(
        http=_resolve_float_setting(
            timeout_section,
            "http",
            env_name="HAMILTON_VENUS_TIMEOUT_HTTP",
            default=_DEFAULT_HTTP_TIMEOUT,
        ),
        startup=_resolve_float_setting(
            timeout_section,
            "startup",
            env_name="HAMILTON_VENUS_TIMEOUT_STARTUP",
            default=_DEFAULT_STARTUP_TIMEOUT,
        ),
        disconnect=_resolve_float_setting(
            timeout_section,
            "disconnect",
            env_name="HAMILTON_VENUS_TIMEOUT_DISCONNECT",
            default=_DEFAULT_DISCONNECT_TIMEOUT,
        ),
        command=_resolve_optional_float_setting(
            timeout_section,
            "command",
            env_name="HAMILTON_VENUS_TIMEOUT_COMMAND",
            default=_DEFAULT_COMMAND_TIMEOUT,
        ),
    )


def _load_star_client_config(
    star_client_section: dict[str, Any], *, config_dir: Path | None = None
) -> StarClientConfig:
    error_profile_path = _resolve_string_setting(
        star_client_section,
        "error_profile_path",
        env_name="HAMILTON_VENUS_ERROR_PROFILE_PATH",
        default="",
    )
    if (
        error_profile_path
        and config_dir is not None
        and os.environ.get("HAMILTON_VENUS_ERROR_PROFILE_PATH") is None
        and not Path(error_profile_path).is_absolute()
    ):
        error_profile_path = str((config_dir / error_profile_path).resolve())

    return StarClientConfig(
        auto_connect=_resolve_bool_setting(
            star_client_section,
            "auto_connect",
            env_name="HAMILTON_VENUS_AUTO_CONNECT",
            default=_DEFAULT_STAR_AUTO_CONNECT,
        ),
        shutdown_timeout=_resolve_float_setting(
            star_client_section,
            "shutdown_timeout",
            env_name="HAMILTON_VENUS_SHUTDOWN_TIMEOUT",
            default=_DEFAULT_STAR_SHUTDOWN_TIMEOUT,
        ),
        logging_level=_resolve_logging_level_setting(
            star_client_section,
            "logging_level",
            env_name="HAMILTON_VENUS_LOGGING_LEVEL",
        ),
        venus_trace_logging=_resolve_bool_setting(
            star_client_section,
            "venus_trace_logging",
            env_name="HAMILTON_VENUS_TRACE_LOGGING",
            default=_DEFAULT_STAR_VENUS_TRACE_LOGGING,
        ),
        error_profile_name=_resolve_error_profile_name_setting(
            star_client_section,
            "error_profile_name",
            env_name="HAMILTON_VENUS_ERROR_PROFILE",
            default="standard",
        ),
        error_profile_path=error_profile_path,
    )


def _load_vantage_client_config(
    vantage_client_section: dict[str, Any], *, config_dir: Path | None = None
) -> VantageClientConfig:
    error_profile_path = _resolve_string_setting(
        vantage_client_section,
        "error_profile_path",
        env_name="HAMILTON_VENUS_VANTAGE_ERROR_PROFILE_PATH",
        default="",
    )
    if (
        error_profile_path
        and config_dir is not None
        and os.environ.get("HAMILTON_VENUS_VANTAGE_ERROR_PROFILE_PATH") is None
        and not Path(error_profile_path).is_absolute()
    ):
        error_profile_path = str((config_dir / error_profile_path).resolve())

    return VantageClientConfig(
        auto_connect=_resolve_bool_setting(
            vantage_client_section,
            "auto_connect",
            env_name="HAMILTON_VENUS_VANTAGE_AUTO_CONNECT",
            default=_DEFAULT_STAR_AUTO_CONNECT,
        ),
        shutdown_timeout=_resolve_float_setting(
            vantage_client_section,
            "shutdown_timeout",
            env_name="HAMILTON_VENUS_VANTAGE_SHUTDOWN_TIMEOUT",
            default=_DEFAULT_STAR_SHUTDOWN_TIMEOUT,
        ),
        logging_level=_resolve_logging_level_setting(
            vantage_client_section,
            "logging_level",
            env_name="HAMILTON_VENUS_VANTAGE_LOGGING_LEVEL",
        ),
        venus_trace_logging=_resolve_bool_setting(
            vantage_client_section,
            "venus_trace_logging",
            env_name="HAMILTON_VENUS_VANTAGE_TRACE_LOGGING",
            default=_DEFAULT_STAR_VENUS_TRACE_LOGGING,
        ),
        error_profile_name=_resolve_error_profile_name_setting(
            vantage_client_section,
            "error_profile_name",
            env_name="HAMILTON_VENUS_VANTAGE_ERROR_PROFILE",
            default="standard",
        ),
        error_profile_path=error_profile_path,
    )


@dataclass
class SdkConfig:
    """Top-level SDK configuration."""

    base_url: str = _DEFAULT_BASE_URL
    method: MethodConfig = field(default_factory=MethodConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    tls: TlsConfig = field(default_factory=TlsConfig)
    run_log: RunLogConfig = field(default_factory=RunLogConfig)
    star_client: StarClientConfig = field(default_factory=StarClientConfig)
    vantage_client: VantageClientConfig = field(default_factory=VantageClientConfig)

    def __post_init__(self) -> None:
        self.base_url = _validate_http_url(self.base_url, field_name="base_url")


def _find_config_file() -> Path | None:
    """Locate the configuration file.

    When ``HAMILTON_VENUS_CONFIG`` is set the returned path is **always** used,
    even if the file does not exist yet — :func:`load_config` will raise a
    clear :class:`FileNotFoundError` in that case.
    """
    env_path = os.environ.get("HAMILTON_VENUS_CONFIG")
    if env_path:
        return Path(env_path)

    local = Path.cwd() / "hamilton_venus.toml"
    if local.is_file():
        return local

    return None


def _resolve_error_profile_name_setting(
    section: dict[str, Any], key: str, *, env_name: str | None = None, default: str = "standard"
) -> str:
    return _resolve_string_setting(section, key, env_name=env_name, default=default).strip().lower()


def _resolve_logging_level_setting(
    section: dict[str, Any], key: str, *, env_name: str | None = None
) -> int | None:
    if env_name is not None:
        env_value = _get_env_string(env_name)
        if env_value is not None:
            return _parse_logging_level_setting_value(
                env_value,
                source=f"environment variable {env_name!r}",
            )

    return _parse_logging_level_setting_value(section.get(key), source=f"key {key!r}")


def load_config(path: str | Path | None = None) -> SdkConfig:
    """Load :class:`SdkConfig` from a TOML file and return it."""
    resolved: Path | None = Path(path) if path is not None else _find_config_file()
    raw: dict[str, Any] = {}

    if resolved is None:
        _logger.debug("load_config: no config file found, using defaults")
    else:
        if not resolved.is_file():
            raise FileNotFoundError(f"VENUS SDK config file not found: {resolved}")

        _logger.debug("load_config: loading from %s", resolved)
        with resolved.open("rb") as fh:
            raw = tomllib.load(fh)

    venus_section: dict[str, Any] = raw.get("venus", {})
    method_section: dict[str, Any] = venus_section.get("method", {})
    network_section: dict[str, Any] = venus_section.get("network", {})
    timeout_section: dict[str, Any] = venus_section.get("timeouts", {})
    auth_section: dict[str, Any] = venus_section.get("auth", {})
    tls_section: dict[str, Any] = venus_section.get("tls", {})
    run_log_section: dict[str, Any] = venus_section.get("run_log", {})
    star_client_section: dict[str, Any] = venus_section.get("star_client", {})
    vantage_client_section: dict[str, Any] = venus_section.get("vantage_client", {})

    timeouts = _load_timeouts_config(timeout_section)

    method = _load_method_config(method_section)

    network = _load_network_config(network_section)

    auth = _load_auth_config(auth_section)
    tls = _load_tls_config(tls_section)
    run_log = _load_run_log_config(run_log_section)
    star_client = _load_star_client_config(
        star_client_section,
        config_dir=resolved.parent if resolved is not None else None,
    )
    vantage_client = _load_vantage_client_config(
        vantage_client_section,
        config_dir=resolved.parent if resolved is not None else None,
    )

    config = SdkConfig(
        base_url=_resolve_string_setting(
            venus_section,
            "base_url",
            env_name="HAMILTON_VENUS_BASE_URL",
            default=_DEFAULT_BASE_URL,
        ).rstrip("/"),
        method=method,
        network=network,
        timeouts=timeouts,
        auth=auth,
        tls=tls,
        run_log=run_log,
        star_client=star_client,
        vantage_client=vantage_client,
    )
    _logger.debug(
        "load_config: base_url=%r, "
        "method=(display_name=%r), network.max_retries=%d, "
        "timeouts=(http=%.1fs, startup=%.1fs, disconnect=%.1fs, command=%r), "
        "auth=(token_url=%r, username_set=%s), tls=(ca_bundle_configured=%s)",
        config.base_url,
        config.method.method_display_name,
        config.network.max_retries,
        config.timeouts.http,
        config.timeouts.startup,
        config.timeouts.disconnect,
        config.timeouts.command,
        config.auth.token_url,
        bool(config.auth.username),
        bool(config.tls.ca_bundle_path),
    )
    return config

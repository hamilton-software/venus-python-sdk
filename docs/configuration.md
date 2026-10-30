# Configuration

The SDK resolves configuration from three sources, in priority order:

1. **Environment variables** (highest priority)
2. **TOML config file**
3. **Built-in defaults** (lowest priority)

Programmatic `SdkConfig` objects bypass the TOML/env resolution entirely (except the `HAMILTON_VENUS_RUN_LOG_ENABLED` and `HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE` defaults of `RunLogConfig`). When you create `StarClient()` or `VantageClient()` without a config, the SDK calls `load_config()` to resolve the sources above.

## TOML File

The SDK looks for a TOML configuration file in this order:

1. The path in the `HAMILTON_VENUS_CONFIG` environment variable.
2. A file named `hamilton_venus.toml` in the current working directory.

### Full TOML Reference

```toml
[venus]
base_url = "http://localhost:42400"

[venus.method]
method_display_name = "MyPythonScript"
parent_window_handle = 0
disable_status_communication = true   # false: VENUS posts per-command status messages (run log only)
disable_idle_communication = true     # false: VENUS posts its idle flag per command; instrument_is_idle() reads it

[venus.network]
max_retries = 3
retry_backoff = 0.5

[venus.timeouts]
http = 30.0
startup = 300.0
disconnect = 30.0
command = 300.0              # set to "none" (or "null") for infinite command timeout

[venus.auth]
token_url = "https://localhost:42431/api/vector/v1/authorization/token"
username = ""
password = ""
client_id = "Venus"
client_secret = "venus_secret"
scope = "openid"
refresh_skew_seconds = 60

[venus.tls]
ca_bundle_path = ""

[venus.run_log]
enabled = true
output_dir = ""            # empty = VENUS's LogFiles directory (from the registry)
console_capture = true
include_http = true
include_signalr = true
include_cmd_comms = true
redact_auth = true
signalr_event_filter = []
max_payload_bytes = 1048576
include_com_trace = true      # embed VENUS's firmware .trc for this run's window
com_trace_logfiles_dir = ""   # empty = ask VENUS (system/paths), then the registry's LogFiles directory
com_trace_max_bytes = 5242880 # cap on embedded trace; 0 = unlimited (keeps newest)

[venus.star_client]
auto_connect = true
shutdown_timeout = 30.0
logging_level = ""         # empty = disabled; also accepts DEBUG/INFO/WARNING/ERROR/CRITICAL or integer
venus_trace_logging = false
error_profile_name = "standard"   # built-in profile name; ignored when error_profile_path is set
error_profile_path = ""           # absolute path, or relative to this TOML file's folder, to a custom profile JSON file

[venus.vantage_client]       # same keys as [venus.star_client], used by VantageClient
auto_connect = true
shutdown_timeout = 30.0
logging_level = ""
venus_trace_logging = false
error_profile_name = "standard"
error_profile_path = ""
```

## Environment Variables

The following settings can be overridden with environment variables. Environment variables take precedence over TOML values.

### Connection

| Variable | Default | Description |
|----------|---------|-------------|
| `HAMILTON_VENUS_CONFIG` | *(none)* | Path to the TOML config file |
| `HAMILTON_VENUS_BASE_URL` | *(none)* | Override `[venus].base_url`. |

### Method

| Variable | Default | Description |
|----------|---------|-------------|
| `HAMILTON_VENUS_METHOD_DISPLAY_NAME` | *(none)* | Override `[venus.method].method_display_name`. |
| `HAMILTON_VENUS_METHOD_DISABLE_STATUS_COMMUNICATION` | *(none)* | Override `[venus.method].disable_status_communication`: `1`, `true`, `yes`, `on` / `0`, `false`, `no`, `off`. |
| `HAMILTON_VENUS_METHOD_DISABLE_IDLE_COMMUNICATION` | *(none)* | Override `[venus.method].disable_idle_communication`: `1`, `true`, `yes`, `on` / `0`, `false`, `no`, `off`. |

### Network

| Variable | Default | Description |
|----------|---------|-------------|
| `HAMILTON_VENUS_NETWORK_MAX_RETRIES` | *(none)* | Override `[venus.network].max_retries`. Must be `>= 0`. |
| `HAMILTON_VENUS_NETWORK_RETRY_BACKOFF` | *(none)* | Override `[venus.network].retry_backoff`. Must be `>= 0`. |

### Timeouts

| Variable | Default | Description |
|----------|---------|-------------|
| `HAMILTON_VENUS_TIMEOUT_HTTP` | *(none)* | Override `[venus.timeouts].http` in seconds. Must be `> 0`. |
| `HAMILTON_VENUS_TIMEOUT_STARTUP` | *(none)* | Override `[venus.timeouts].startup` in seconds. Must be `> 0`. |
| `HAMILTON_VENUS_TIMEOUT_DISCONNECT` | *(none)* | Override `[venus.timeouts].disconnect` in seconds. Must be `> 0`. |
| `HAMILTON_VENUS_TIMEOUT_COMMAND` | *(none)* | Override `[venus.timeouts].command` in seconds. Must be `> 0`, or set to `none`/`null` for infinite timeout. |

### StarClient Defaults

| Variable | Default | Description |
|----------|---------|-------------|
| `HAMILTON_VENUS_AUTO_CONNECT` | *(none)* | Override `[venus.star_client].auto_connect`. |
| `HAMILTON_VENUS_SHUTDOWN_TIMEOUT` | *(none)* | Override `[venus.star_client].shutdown_timeout` in seconds. Must be `> 0`. |
| `HAMILTON_VENUS_LOGGING_LEVEL` | *(none)* | Override `[venus.star_client].logging_level`. Accepts `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, or non-negative integer. |
| `HAMILTON_VENUS_TRACE_LOGGING` | *(none)* | Override `[venus.star_client].venus_trace_logging`. |
| `HAMILTON_VENUS_ERROR_PROFILE` | *(none)* | Override `[venus.star_client].error_profile_name`. Built-in values: `standard`. Ignored when `HAMILTON_VENUS_ERROR_PROFILE_PATH` is set. |
| `HAMILTON_VENUS_ERROR_PROFILE_PATH` | *(none)* | Path to a custom error profile JSON file. When set, takes precedence over `error_profile_name`. |

### VantageClient Defaults

Same as the StarClient variables above, but with a `VANTAGE_` prefix, and they override `[venus.vantage_client]`: `HAMILTON_VENUS_VANTAGE_AUTO_CONNECT`, `HAMILTON_VENUS_VANTAGE_SHUTDOWN_TIMEOUT`, `HAMILTON_VENUS_VANTAGE_LOGGING_LEVEL`, `HAMILTON_VENUS_VANTAGE_TRACE_LOGGING`, `HAMILTON_VENUS_VANTAGE_ERROR_PROFILE`, `HAMILTON_VENUS_VANTAGE_ERROR_PROFILE_PATH`.

### Run Log

| Variable | Default | Description |
|----------|---------|-------------|
| `HAMILTON_VENUS_RUN_LOG_ENABLED` | *(none)* | On by default. Disable: `0`, `false`, `no`, or `off`. Enable: `1`, `true`, `yes`, or `on`. Also applies to a `RunLogConfig` built in code. |
| `HAMILTON_VENUS_RUN_LOG_DIR` | *(none)* | Override output directory for run log files (default: VENUS's LogFiles directory). |
| `HAMILTON_VENUS_RUN_LOG_CONSOLE_CAPTURE` | *(none)* | Enable: `1`, `true`, `yes`, or `on`. Disable: `0`, `false`, `no`, `off`, or an empty value. |
| `HAMILTON_VENUS_RUN_LOG_INCLUDE_HTTP` | *(none)* | Enable: `1`, `true`, `yes`, or `on`. Disable: `0`, `false`, `no`, `off`, or an empty value. |
| `HAMILTON_VENUS_RUN_LOG_INCLUDE_SIGNALR` | *(none)* | Enable: `1`, `true`, `yes`, or `on`. Disable: `0`, `false`, `no`, `off`, or an empty value. |
| `HAMILTON_VENUS_RUN_LOG_INCLUDE_CMD_COMMS` | *(none)* | Enable: `1`, `true`, `yes`, or `on`. Disable: `0`, `false`, `no`, `off`, or an empty value. |
| `HAMILTON_VENUS_RUN_LOG_REDACT_AUTH` | *(none)* | Enable: `1`, `true`, `yes`, or `on`. Disable: `0`, `false`, `no`, `off`, or an empty value. |
| `HAMILTON_VENUS_RUN_LOG_SIGNALR_EVENT_FILTER` | *(none)* | Comma-separated list of SignalR event types to include (for example: `runtime_status,progress`). |
| `HAMILTON_VENUS_RUN_LOG_MAX_PAYLOAD_BYTES` | *(none)* | Override max serialized payload size per log entry in bytes. Must be `>= 0`. |
| `HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE` | *(none)* | Embed VENUS's firmware COM trace (`.trc`). Enable: `1`, `true`, `yes`, or `on`. Disable: `0`, `false`, `no`, `off`, or an empty value. Also applies to a `RunLogConfig` built in code. |
| `HAMILTON_VENUS_RUN_LOG_COM_TRACE_DIR` | *(none)* | Override the VENUS `Logfiles` directory the `.trc` is read from. Unset, the SDK asks VENUS via `GET /api/vector/v3/system/paths`. |
| `HAMILTON_VENUS_RUN_LOG_COM_TRACE_MAX_BYTES` | *(none)* | Cap on the embedded trace size in bytes. `0` = unlimited (keeps the newest lines). Must be `>= 0`. |

## Programmatic Configuration

Bypass TOML/env resolution by constructing `SdkConfig` directly:

```python
from hamilton_venus import MethodConfig, SdkConfig, StarClient

config = SdkConfig(
    method=MethodConfig(method_display_name="MyScript"),
)

with StarClient(config, auto_connect=False) as star:
    star.instrument_connect(initialize=False)
    star.instrument_init()
    print(star.instrument_is_connected())
```

Connection behavior is controlled on `StarClient` (or `[venus.star_client]`), not by the top-level `SdkConfig` fields. With the default `auto_connect=True`, the client connects to the instrument on entry but does not initialize it:

```python
with StarClient(config) as star:
    star.instrument_init()
    print(star.instrument_is_connected())
```

Use `auto_connect=False` to manage the connection manually.

`StarClient` logging resolution is explicit:

- `use_config_logging_level=True` (default): `logging_level=None` inherits `config.star_client.logging_level`.
- `use_config_logging_level=False`: `logging_level` is used exactly as passed (`None` disables SDK logger handler attachment).

### Config Dataclasses

#### `SdkConfig`

Top-level configuration container.

| Field | Type | Default |
|-------|------|---------|
| `base_url` | `str` | `"http://localhost:42400"` |
| `method` | `MethodConfig` | *(default instance)* |
| `timeouts` | `TimeoutConfig` | *(default instance)* |
| `network` | `NetworkConfig` | *(default instance)* |
| `auth` | `AuthConfig` | *(default instance)* |
| `tls` | `TlsConfig` | *(default instance)* |
| `run_log` | `RunLogConfig` | *(default instance)* |
| `star_client` | `StarClientConfig` | *(default instance)* |
| `vantage_client` | `VantageClientConfig` | *(default instance; same fields as `StarClientConfig`)* |

#### `MethodConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `parent_window_handle` | `int` | `0` | |
| `method_display_name` | `str` | `""` | |
| `disable_status_communication` | `bool` | `True` | Sent to the method as `disableStatusCommunication` (1/0) before it starts. `True` skips VENUS's per-command status messages on the `communication` channel ("Command Received", "Pickup tips...", "Command finished ..."), which saves several VENUS HTTP round trips per command; those messages only feed the run log's `command_communication` entries. |
| `disable_idle_communication` | `bool` | `True` | Sent to the method as `disableIdleCommunication` (1/0) before it starts. `True` stops VENUS posting its busy/idle flag to the `idle` channel on every command, and `instrument_is_idle()` answers from the client itself (idle when none of its commands is in flight) instead of reading that channel. `False` restores the channel for both. |

#### `TimeoutConfig`

All values in seconds. Only `command` supports `None`/`none`/`null` (infinite timeout); `http`, `startup`, and `disconnect` must always be positive numbers.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `http` | `float` | `30.0` | General HTTP request timeout |
| `startup` | `float` | `300.0` | Startup/handshake timeout |
| `disconnect` | `float` | `30.0` | Disconnection timeout |
| `command` | `float \| None` | `300.0` | Individual command timeout (`None` disables timeout / infinite wait) |

#### `NetworkConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_retries` | `int` | `3` | Maximum retry attempts for failed requests |
| `retry_backoff` | `float` | `0.5` | Backoff multiplier between retries (seconds) |

#### `AuthConfig`

See [Authentication](authentication.md) for full details.

#### `TlsConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ca_bundle_path` | `str` | `""` | Path to a PEM CA bundle. If empty, system defaults are used. |

#### `StarClientConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `auto_connect` | `bool` | `True` | Whether `StarClient` connects to the instrument (without initializing it) when it starts, e.g. on entering a `with` block. |
| `shutdown_timeout` | `float` | `30.0` | Timeout in seconds for graceful shutdown. Must be `> 0`. |
| `logging_level` | `int \| None` | `None` | SDK logger handler level. `None` disables attachment. |
| `venus_trace_logging` | `bool` | `False` | Enable low-level VENUS transport trace logging. |
| `error_profile_name` | `str` | `"standard"` | Built-in error profile name. Ignored when `error_profile_path` is set. |
| `error_profile_path` | `str` | `""` | Path to a custom error profile JSON file (relative paths in TOML resolve against the TOML file's folder). When set, this path is loaded and takes precedence over `error_profile_name`. |

## Validation

The SDK validates configuration at construction time:

- `base_url` and `token_url` must use `http` or `https` schemes and have a valid hostname.
- `auth.refresh_skew_seconds` must be >= 0.
- `timeouts.http`, `timeouts.startup`, and `timeouts.disconnect` must always be numeric values > 0 (they do not support `None`).
- `timeouts.command` must be > 0 when set; `None` is allowed and means infinite command timeout.
- network settings (`network.max_retries`, `network.retry_backoff`) must be >= 0.
- `run_log.max_payload_bytes` must be >= 0.
- `run_log.com_trace_max_bytes` must be >= 0.
- `tls.ca_bundle_path`, if set, must point to an existing file.

Invalid configuration raises `ValueError` or `FileNotFoundError` immediately rather than failing at connect time.

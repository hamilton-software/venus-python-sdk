# Authentication

The Hamilton VENUS Python SDK supports both unauthenticated and authenticated connections to the VENUS WebAPI. Authentication mode is auto-detected at connect time — you do not need to manually toggle it on or off.

## How Auth-Mode Detection Works

When `StarClient` (or `VantageClient`) connects, the SDK queries the VENUS endpoint:

```
GET /api/vector/v3/system/authentication-mode
```

- If VENUS reports `None`, the SDK continues without authenticated transport.
- If VENUS reports any other mode, the SDK enables authenticated REST transport and requires `username` and `password` credentials.

SignalR connections are never authenticated; authentication is only applied to REST requests.

## Unauthenticated (Default)

No additional configuration is needed for unauthenticated VENUS environments:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    print(star.instrument_is_connected())
```

## Authenticated (OAuth)

For secure VENUS environments, provide credentials through environment variables, TOML configuration, or programmatic configuration. If VENUS requires authentication and no credentials are set, connecting raises `VenusAuthenticationError`.

### Environment Variables

Set credentials as environment variables to keep secrets out of source code:

```powershell
$env:HAMILTON_VENUS_AUTH_USERNAME = "your-venus-user"
$env:HAMILTON_VENUS_AUTH_PASSWORD = "your-password"
```

Optional auth environment variables with their defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `HAMILTON_VENUS_AUTH_TOKEN_URL` | `https://localhost:42431/api/vector/v1/authorization/token` | OAuth token endpoint |
| `HAMILTON_VENUS_AUTH_CLIENT_ID` | `Venus` | OAuth client ID |
| `HAMILTON_VENUS_AUTH_CLIENT_SECRET` | `venus_secret` | OAuth client secret |
| `HAMILTON_VENUS_AUTH_SCOPE` | `openid` | OAuth scope |
| `HAMILTON_VENUS_AUTH_REFRESH_SKEW_SECONDS` | `60` | Seconds before expiry to refresh the token |

### TOML Configuration

Place non-secret auth settings in your `hamilton_venus.toml` file:

```toml
[venus]
base_url = "https://instrument-pc:42400"

[venus.auth]
client_id = "Venus"
scope = "openid"
refresh_skew_seconds = 60
```

Secrets (`username`, `password`, `client_secret`) should still be provided via environment variables. If they are present in the TOML file, the environment variable takes precedence.

### Programmatic Configuration

Pass an `AuthConfig` directly when constructing `SdkConfig`:

```python
from hamilton_venus import AuthConfig, MethodConfig, SdkConfig, StarClient

config = SdkConfig(
    method=MethodConfig(method_display_name="MyMethod"),
    auth=AuthConfig(
        username="your-venus-user",
        password="your-password",
    ),
)

with StarClient(config) as star:
    print(star.instrument_is_connected())
```

### `AuthConfig` Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `token_url` | `str` | `https://localhost:42431/api/vector/v1/authorization/token` | OAuth token endpoint URL |
| `username` | `str` | `""` | VENUS account username |
| `password` | `str` | `""` | VENUS account password |
| `client_id` | `str` | `"Venus"` | OAuth client identifier |
| `client_secret` | `str` | `"venus_secret"` | OAuth client secret |
| `scope` | `str` | `"openid"` | OAuth scope string |
| `refresh_skew_seconds` | `int` | `60` | How many seconds before token expiry to proactively refresh |

## TLS / Custom CA Bundles

When the identity provider uses a certificate signed by an internal CA, configure the SDK to trust it:

**TOML:**

```toml
[venus.tls]
ca_bundle_path = "C:\\certs\\your-org-ca-bundle.pem"
```

**Environment variable:**

```powershell
$env:HAMILTON_VENUS_TLS_CA_BUNDLE = "C:\certs\your-org-ca-bundle.pem"
```

The path must point to a PEM file containing the CA certificate chain used to validate the identity provider's TLS certificate.

## Token Lifecycle

The SDK manages the OAuth token lifecycle automatically:

1. On first authenticated request, the SDK acquires an access token using the `password` grant type.
2. The token is cached in memory.
3. Before each request, the SDK checks if the cached token is still valid (accounting for `refresh_skew_seconds`).
4. If the token is expired or about to expire, a new token is acquired transparently.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `VenusAuthenticationError` during connect | Bad credentials or unreachable token endpoint | Verify `HAMILTON_VENUS_AUTH_TOKEN_URL`, `username`, and `password` |
| REST calls fail after auth-mode detection | Token endpoint unreachable or wrong credentials | Confirm the token endpoint is reachable from the SDK machine |
| Requests fail close to token expiry | High latency or clock drift | Increase `HAMILTON_VENUS_AUTH_REFRESH_SKEW_SECONDS` |
| TLS certificate verification fails | Missing or wrong CA bundle | Set `venus.tls.ca_bundle_path` or `HAMILTON_VENUS_TLS_CA_BUNDLE` and verify the file exists |

"""VenusClient — async HTTP client for the VENUS WebAPI."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import httpx

from hamilton_venus._internal._auth import _AuthHeadersProvider, _merge_auth_headers
from hamilton_venus._internal._run_log import RunLog
from hamilton_venus._internal._run_message_command_dispatcher import _RunMessageCommandDispatcher
from hamilton_venus.config import RunLogConfig
from hamilton_venus.exceptions import MethodError, VenusApiContractError, VenusConnectionError, VenusTimeoutError
from hamilton_venus.models import (
    CmdResult,
    CommandResponse,
    ErrorData,
    ErrorDataResponseModel,
    ErrorHandlingResponse,
    ErrorRecovery,
    ExecutorEvent,
    LoadMethodRequest,
    RunMessageQueuedEvent,
    RunState,
)

_API_PREFIX = "/api/vector/v3/execution"
_SYSTEM_PREFIX = "/api/vector/v3/system"
_ERROR_HANDLER_PREFIX = "/api/vector/v3/error-handler"
_INSTRUMENT_ERRORS_PREFIX = "/api/vector/v3/instrument-errors"
_INSTRUMENT_ERRORS_V2_UNHANDLED_PATH = "/api/vector/v2/instrument-errors/unhandled"
_SYSTEM_V2_PREFIX = "/api/vector/v2/system"
_logger = logging.getLogger(__name__)
_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_DEFAULT_COMMAND_TIMEOUT = 300.0
_AUTHENTICATION_MODE_KEYS = ("authenticationMode", "mode", "value")


def _parse_authentication_mode_payload(payload: Any) -> str:
    if isinstance(payload, str):
        mode = payload.strip()
        if mode:
            return mode
    if isinstance(payload, dict):
        for key in _AUTHENTICATION_MODE_KEYS:
            value = payload.get(key)
            if value is not None:
                mode = str(value).strip()
                if mode:
                    return mode
    raise VenusApiContractError("GetAuthenticationMode returned an unexpected response payload")


class VenusClient:
    """Async low-level client that communicates with the VENUS WebAPI.

    All public methods are coroutines and must be awaited. Use as an async
    context manager to ensure the underlying HTTP connection is closed cleanly::

        async with VenusClient(base_url="http://localhost:42400") as venus:
            state = await venus.get_run_state()

    Parameters
    ----------
    base_url:
        Base URL of the VENUS WebAPI (e.g. ``"http://localhost:42400"``).
        Must **not** have a trailing slash.
    timeout:
        Default timeout (seconds) applied to every HTTP request.
    headers:
        Optional extra HTTP headers sent with every request.
    max_retries:
        Number of retries for transient errors (connection failures, timeouts,
        and HTTP 502/503/504). Set to ``0`` to disable retries.
    retry_backoff:
        Base delay in seconds between retries. Each subsequent retry doubles
        the delay (exponential backoff).
    auth_provider:
        Optional access-token provider used to attach bearer authentication to
        requests against secure VENUS endpoints.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
        max_retries: int = 3,
        retry_backoff: float = 0.5,
        command_timeout: float | None = _DEFAULT_COMMAND_TIMEOUT,
        max_connections: int = 10,
        max_keepalive_connections: int = 5,
        auth_provider: _AuthHeadersProvider | None = None,
        verify: bool | str = True,
    ) -> None:
        if not base_url or not base_url.strip("/"):
            raise ValueError("base_url must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0")
        if max_retries < 0:
            raise ValueError("max_retries must be greater than or equal to 0")
        if retry_backoff < 0:
            raise ValueError("retry_backoff must be greater than or equal to 0")
        if command_timeout is not None and command_timeout <= 0:
            raise ValueError("command_timeout must be greater than 0")

        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = headers or {}
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._command_timeout = command_timeout
        self._max_connections = max_connections
        self._max_keepalive_connections = max_keepalive_connections
        self._auth_provider = auth_provider
        self._verify = verify
        self._client: httpx.AsyncClient | None = None
        self._run_log: RunLog | None = None
        self._run_log_config: RunLogConfig = RunLogConfig()
        self._command_dispatcher = _RunMessageCommandDispatcher(self._request)
        self._command_dispatcher.set_run_log_config(self._run_log_config)

    def set_command_guard(self, guard: Callable[[str, str], None] | None) -> None:
        """Install a ``guard(category, action_name)`` that may veto commands before they are sent."""
        self._command_dispatcher.set_command_guard(guard)

    def set_before_command(self, hook: Callable[[str, str, dict[str, Any]], Awaitable[None]] | None) -> None:
        """Install an async ``hook(category, action_name, parameters)`` awaited before every command is sent."""
        self._command_dispatcher.set_before_command(hook)

    def set_run_log(self, run_log: RunLog | None) -> None:
        self._run_log = run_log

    def set_run_log_config(self, run_log_config: RunLogConfig) -> None:
        self._run_log_config = run_log_config

    # -- lifecycle ------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the underlying HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers=self._headers,
                limits=httpx.Limits(
                    max_connections=self._max_connections,
                    max_keepalive_connections=self._max_keepalive_connections,
                ),
                verify=self._verify,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool.

        Safe to call multiple times or when the client is already closed.
        No exceptions are raised if the connection is already closed.
        """
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        if self._auth_provider is not None:
            await self._auth_provider.aclose()

    async def __aenter__(self) -> VenusClient:
        """Enter the async context manager and return this client instance."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Exit the async context manager and close the underlying HTTP client."""
        await self.aclose()

    def override_command_timeout(self, timeout: float | None) -> AbstractContextManager[None]:
        """Temporarily override the default command timeout for a block of commands."""

        @contextmanager
        def _timeout_context() -> Iterator[None]:
            old_timeout = self._command_timeout
            self._command_timeout = timeout
            try:
                yield
            finally:
                self._command_timeout = old_timeout

        return _timeout_context()

    # -- private helpers ------------------------------------------------------

    async def _build_request_headers(self, *, force_auth_refresh: bool = False) -> dict[str, str] | None:
        return await _merge_auth_headers(
            self._headers,
            self._auth_provider,
            force_auth_refresh=force_auth_refresh,
        )

    async def _send_http_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        force_auth_refresh: bool = False,
    ) -> httpx.Response:
        headers = await self._build_request_headers(force_auth_refresh=force_auth_refresh)
        if _logger.isEnabledFor(logging.DEBUG):
            auth_value = (headers or {}).get("Authorization", "")
            if auth_value:
                scheme = auth_value.split(" ", 1)[0] if " " in auth_value else auth_value
                _logger.debug("%s %s with Authorization: %s <redacted>", method, path, scheme)
            else:
                _logger.debug("%s %s without Authorization header", method, path)
        return await client.request(
            method,
            path,
            json=json,
            params=params,
            headers=headers,
        )

    async def _send_request_with_auth_refresh(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        auth_refresh_attempted: bool,
    ) -> tuple[httpx.Response, bool]:
        response = await self._send_http_request(client, method, path, json=json, params=params)
        if response.status_code != 401 or self._auth_provider is None or auth_refresh_attempted:
            return response, auth_refresh_attempted

        _logger.info("HTTP 401 on %s %s; refreshing access token and retrying once", method, path)
        response = await self._send_http_request(
            client,
            method,
            path,
            json=json,
            params=params,
            force_auth_refresh=True,
        )
        return response, True

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        error_prefix: str = "Request",
    ) -> httpx.Response:
        """Send an HTTP request with automatic retry logic for transient errors."""
        if self._run_log is not None and self._run_log_config.include_http:
            self._run_log.record("WebAPI", "Out", "http_request", {
                "method": method, "path": path, "body": json,
            })
        client = self._get_client()
        last_exc: Exception | None = None
        auth_refresh_attempted = False
        for attempt in range(1 + self._max_retries):
            if attempt > 0:
                delay = self._retry_backoff * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
            try:
                response, auth_refresh_attempted = await self._send_request_with_auth_refresh(
                    client,
                    method,
                    path,
                    json=json,
                    params=params,
                    auth_refresh_attempted=auth_refresh_attempted,
                )
                if response.is_success:
                    self._log_http_response(method, path, response)
                    return response
                if response.status_code not in _RETRYABLE_STATUS_CODES or attempt == self._max_retries:
                    _logger.debug(
                        "%s %s failed (HTTP %d): %s",
                        method,
                        path,
                        response.status_code,
                        response.text,
                    )
                    raise MethodError(
                        f"{error_prefix} failed (HTTP {response.status_code})",
                        cmd_result_message=response.text,
                    )
                _logger.warning(
                    "Retryable HTTP %d on %s %s (attempt %d/%d)",
                    response.status_code,
                    method,
                    path,
                    attempt + 1,
                    1 + self._max_retries,
                )
            except httpx.ConnectError as exc:
                last_exc = exc
                self._log_http_error(method, path, exc, attempt)
                if attempt == self._max_retries:
                    raise VenusConnectionError(f"Cannot connect to VENUS WebAPI at {self._base_url}: {exc}") from exc
                _logger.warning(
                    "Connection error on %s %s (attempt %d/%d): %s",
                    method,
                    path,
                    attempt + 1,
                    1 + self._max_retries,
                    exc,
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                self._log_http_error(method, path, exc, attempt)
                if attempt == self._max_retries:
                    raise VenusTimeoutError(f"Request to {self._base_url}{path} timed out: {exc}") from exc
                _logger.warning(
                    "Timeout on %s %s (attempt %d/%d): %s",
                    method,
                    path,
                    attempt + 1,
                    1 + self._max_retries,
                    exc,
                )

        raise VenusConnectionError(f"All {1 + self._max_retries} attempts failed for {method} {path}: {last_exc}")

    def _log_http_response(self, method: str, path: str, response: httpx.Response) -> None:
        """Record an HTTP response in the run log if enabled."""
        if self._run_log is not None and self._run_log_config.include_http:
            try:
                body = response.json()
            except Exception:
                body = None
            self._run_log.record("WebAPI", "In", "http_response", {
                "method": method, "path": path,
                "status_code": response.status_code, "body": body,
            })

    def _log_http_error(self, method: str, path: str, error: Exception, attempt: int) -> None:
        """Record an HTTP error in the run log if enabled."""
        if self._run_log is not None and self._run_log_config.include_http:
            self._run_log.record("WebAPI", "In", "http_error", {
                "method": method, "path": path,
                "error": f"{type(error).__name__}: {error}", "attempt": attempt + 1,
            })

    async def _cmd(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        error_prefix: str = "Request",
    ) -> CmdResult:
        """Send an HTTP request and parse the response as a CmdResult."""
        response = await self._request(method, path, json=json, error_prefix=error_prefix)
        return CmdResult.model_validate(response.json())

    # -- execution endpoints --------------------------------------------------

    async def load_method(
        self,
        file_path: str,
        simulate: bool = False,
        parent_window_handle: int = 0,
    ) -> CmdResult:
        """Load a VENUS method file.

        Calls ``PUT /api/vector/v3/execution/load``.

        Parameters
        ----------
        file_path:
            Fully-qualified path to the ``.hsl`` method file on the instrument PC.
        simulate:
            When *True*, the instrument runs in simulation mode. Default is *False*.
        parent_window_handle:
            Parent window handle passed to the VENUS runtime. Use ``0``
            (the default) for headless / SDK-driven execution.

        Returns
        -------
        CmdResult
            Parsed response indicating success or failure.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        payload = LoadMethodRequest(
            file_path=file_path,
            simulation=simulate,
            parent_window_handle=parent_window_handle,
        )
        _logger.debug("load_method: file_path=%r, simulate=%r", file_path, simulate)
        result = await self._cmd(
            "PUT",
            f"{_API_PREFIX}/load",
            json=payload.model_dump(by_alias=True),
            error_prefix="LoadMethod",
        )
        _logger.debug("load_method: completed, result=%r", result.result)
        return result

    async def start_method(self) -> CmdResult:
        """Start the currently loaded method.

        Calls ``POST /api/vector/v3/execution/start``.

        Returns
        -------
        CmdResult
            Parsed response indicating success or failure.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        _logger.debug("start_method: starting loaded method")
        result = await self._cmd("POST", f"{_API_PREFIX}/start", error_prefix="StartMethod")
        _logger.debug("start_method: completed, result=%r", result.result)
        return result

    async def pause_method(self) -> CmdResult:
        """Pause the running method.

        Calls ``POST /api/vector/v3/execution/pause``.

        Returns
        -------
        CmdResult
            Parsed response indicating success or failure.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        _logger.debug("pause_method: pausing running method")
        result = await self._cmd("POST", f"{_API_PREFIX}/pause", error_prefix="PauseMethod")
        _logger.debug("pause_method: completed, result=%r", result.result)
        return result

    async def resume_method(self) -> CmdResult:
        """Resume a paused method.

        Calls ``POST /api/vector/v3/execution/resume``.

        Returns
        -------
        CmdResult
            Parsed response indicating success or failure.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        _logger.debug("resume_method: resuming paused method")
        result = await self._cmd("POST", f"{_API_PREFIX}/resume", error_prefix="ResumeMethod")
        _logger.debug("resume_method: completed, result=%r", result.result)
        return result

    async def abort_method(self) -> CmdResult:
        """Abort the running method.

        Calls ``POST /api/vector/v3/execution/abort``.

        Returns
        -------
        CmdResult
            Parsed response indicating success or failure.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        _logger.debug("abort_method: aborting running method")
        result = await self._cmd("POST", f"{_API_PREFIX}/abort", error_prefix="AbortMethod")
        _logger.debug("abort_method: completed, result=%r", result.result)
        return result

    async def unload_method(self) -> CmdResult:
        """Unload the currently loaded method and recycle the run executor.

        Calls ``POST /api/vector/v3/execution/unload-method``.

        Returns
        -------
        CmdResult
            Parsed response indicating success or failure.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        _logger.debug("unload_method: unloading method")
        result = await self._cmd("POST", f"{_API_PREFIX}/unload-method", error_prefix="UnloadMethod")
        _logger.debug("unload_method: completed, result=%r", result.result)
        return result

    async def get_run_state(self) -> RunState:
        """Return the current :class:`~hamilton_venus.models.RunState`.

        Calls ``GET /api/vector/v3/execution/run-state``.

        Returns
        -------
        RunState
            The current run state of the executor.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        response = await self._request("GET", f"{_API_PREFIX}/run-state", error_prefix="GetRunState")
        return RunState.from_api_value(response.json())

    async def get_loaded_method(self) -> str:
        """Return the path of the currently loaded method (empty string if none).

        Calls ``GET /api/vector/v3/execution/loaded-method``.

        Returns
        -------
        str
            Fully-qualified path of the loaded ``.hsl`` file, or ``""``
            if no method is loaded.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        response = await self._request("GET", f"{_API_PREFIX}/loaded-method", error_prefix="GetLoadedMethod")
        return str(response.json())

    async def get_current_run_data(self) -> dict[str, Any]:
        """Return runtime information for the currently-running method.

        Calls ``GET /api/vector/v3/execution/current-run-data``. The payload
        includes ``methodName`` and ``runGuid`` (the identifier VENUS run
        control uses to track the run), among other fields. These let SDK
        artifacts (e.g. the run log) be correlated with VENUS run control,
        run history, and the trace/database files VENUS writes.

        Returns
        -------
        dict[str, Any]
            The parsed run-data object, or an empty dict if the server does
            not report one (e.g. no run is active).

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        response = await self._request(
            "GET", f"{_API_PREFIX}/current-run-data", error_prefix="GetCurrentRunData"
        )
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    async def get_run_guid(self) -> str:
        """Return the VENUS run control GUID for the currently-running method.

        Convenience wrapper around :meth:`get_current_run_data` that extracts
        the ``runGuid`` field.

        Returns
        -------
        str
            The run GUID, or ``""`` if the server does not report one.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        data = await self.get_current_run_data()
        return str(data.get("runGuid") or "")

    async def set_method_variables(
        self,
        variable_names: list[str],
        variable_values: list[Any],
    ) -> CmdResult:
        """Set method variables before starting execution.

        Calls ``PUT /api/vector/v3/execution/input``.

        Must be called after :meth:`load_method` and before :meth:`start_method`
        (i.e. while the executor is in the ``Initialized`` state).

        Parameters
        ----------
        variable_names:
            Names of the HSL global variables to set.
        variable_values:
            Values corresponding to each variable name, in the same order.

        Returns
        -------
        CmdResult
            Parsed response indicating success or failure.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        payload = {"variableNames": variable_names, "variableValues": variable_values}
        _logger.debug("set_method_variables: names=%r values=%r", variable_names, variable_values)
        _logger.debug("set_method_variables: full payload sent to PUT %s/input: %r", _API_PREFIX, payload)
        result = await self._cmd(
            "PUT",
            f"{_API_PREFIX}/input",
            json=payload,
            error_prefix="SetMethodVariables",
        )
        _logger.debug("set_method_variables: completed, result=%r message=%r", result.result, result.message)
        return result

    async def get_simulation(self) -> bool:
        """Return the current system-level simulation configuration.

        Calls ``GET /api/vector/v2/system/configuration/simulation``.

        Returns
        -------
        bool
            ``True`` if simulation mode is currently enabled, ``False`` otherwise.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusApiContractError
            If the server returns an unexpected response payload.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        response = await self._request(
            "GET",
            f"{_SYSTEM_V2_PREFIX}/configuration/simulation",
            error_prefix="GetSimulation",
        )
        payload = response.json()
        if isinstance(payload, bool):
            return payload
        if isinstance(payload, dict):
            for key in ("simulation", "isSimulation", "simulate"):
                if key in payload:
                    return bool(payload[key])
        raise VenusApiContractError(
            "GetSimulation",
            f"Unexpected simulation payload: {payload!r}",
        )

    async def set_simulation(self, simulate: bool) -> None:
        """Set the system-level simulation configuration.

        Calls ``PUT /api/vector/v2/system/configuration/simulation?simulationMode=<bool>``.

        Parameters
        ----------
        simulate:
            When *True*, enables simulation mode. When *False*, disables it.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        _logger.debug("set_simulation: simulate=%r", simulate)
        await self._request(
            "PUT",
            f"{_SYSTEM_V2_PREFIX}/configuration/simulation",
            params={"simulationMode": str(simulate).lower()},
            error_prefix="SetSimulation",
        )
        _logger.debug("set_simulation: completed")

    async def get_authentication_mode(self) -> str:
        """Return the current VENUS authentication mode.

        Calls ``GET /api/vector/v3/system/authentication-mode``.

        Returns
        -------
        str
            Authentication mode reported by VENUS, for example ``"None"``.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusApiContractError
            If the server returns an unexpected response payload.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        response = await self._request(
            "GET",
            f"{_SYSTEM_PREFIX}/authentication-mode",
            error_prefix="GetAuthenticationMode",
        )
        return _parse_authentication_mode_payload(response.json())

    async def get_system_paths(self) -> dict[str, str]:
        """Return VENUS's configured directory paths.

        Calls ``GET /api/vector/v3/system/paths``. The response maps names
        (``Bin``, ``LogFiles``, ``Methods``, ``Library``, ``Labware``,
        ``Config``, ``Graphic``, ``System``) to absolute directory paths.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusApiContractError
            If the server returns an unexpected response payload.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        response = await self._request(
            "GET",
            f"{_SYSTEM_PREFIX}/paths",
            error_prefix="GetSystemPaths",
        )
        payload = response.json()
        if isinstance(payload, dict):
            paths = payload.get("paths", payload)
            if isinstance(paths, dict):
                return {str(k): str(v) for k, v in paths.items()}
        raise VenusApiContractError(
            "GetSystemPaths returned an unexpected response payload"
        )

    async def get_instrument_data(self) -> list[dict[str, Any]]:
        """Return the registered instruments.

        Calls ``GET /api/vector/v3/instrumentdata``. Each entry has ``id``,
        ``name``, ``defaultName`` (e.g. ``"Microlab STARlet"``), ``platform``
        (e.g. ``"ML_STAR"``), ``description`` and ``image``.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusApiContractError
            If the server returns an unexpected response payload.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        response = await self._request(
            "GET",
            "/api/vector/v3/instrumentdata",
            error_prefix="GetInstrumentData",
        )
        payload = response.json()
        if isinstance(payload, dict):
            payload = payload.get("instruments", payload.get("data", payload))
        if isinstance(payload, list):
            return [dict(entry) for entry in payload if isinstance(entry, dict)]
        raise VenusApiContractError(
            "GetInstrumentData returned an unexpected response payload"
        )

    # -- run history and log files --------------------------------------------

    async def get_run_history(
        self,
        *,
        limit: int = 50,
        offset: int = 1,
        newest_first: bool = True,
        start: str | None = None,
        end: str | None = None,
        run_state: str | None = None,
    ) -> dict[str, Any]:
        """Return a page of VENUS's run history.

        Calls ``GET /api/vector/v3/files/run-history-data``. ``offset`` is one-based.
        ``start``/``end`` are ISO date-times bounding the runs' start time. The result's
        ``subList`` holds one entry per run (``runGuid``, ``methodName``,
        ``methodDisplayName``, ``startTime``, ``endTime``, ``runState``, ``duration``,
        ``computerName``); ``spanCount`` is the number of runs matching the filter.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusApiContractError
            If the server returns an unexpected response payload.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        params: dict[str, Any] = {
            "sortProperty": "StartTime",
            "sortOrder": 1 if newest_first else 2,
            "startOffset": offset,
            "recordLimit": limit,
        }
        if start:
            params["startDateRange"] = start
        if end:
            params["endDateRange"] = end
        if run_state:
            params["runState"] = run_state
        response = await self._request(
            "GET", "/api/vector/v3/files/run-history-data", params=params, error_prefix="GetRunHistory"
        )
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("subList", []), list):
            return payload
        raise VenusApiContractError("GetRunHistory returned an unexpected response payload")

    async def get_run_details(self, run_guid: str) -> dict[str, Any]:
        """Return VENUS's details of one run.

        Calls ``GET /api/vector/v3/files/detailed-run-data/{runtimeGuid}``. Besides the
        :meth:`get_run_history` fields it has ``userName`` and ``instruments`` (each with
        ``instrumentName``, ``instrumentSerialNumber``, ``instrumentSimulation`` and
        ``softwareVersion``).

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusApiContractError
            If the server returns an unexpected response payload.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        response = await self._request(
            "GET", f"/api/vector/v3/files/detailed-run-data/{run_guid}", error_prefix="GetRunDetails"
        )
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        raise VenusApiContractError("GetRunDetails returned an unexpected response payload")

    async def get_trace(self, method_display_name: str, run_guid: str) -> list[str]:
        """Return the VENUS trace of one run, one string per line.

        Calls ``GET /api/vector/v3/files/trace``. ``method_display_name`` is the run's
        ``methodDisplayName`` from :meth:`get_run_history` (the method file name without
        folder or extension).

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusApiContractError
            If the server returns an unexpected response payload.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        response = await self._request(
            "GET",
            "/api/vector/v3/files/trace",
            params={"methodName": method_display_name, "runGuid": run_guid},
            error_prefix="GetTrace",
        )
        payload = response.json()
        if isinstance(payload, list):
            return [str(line) for line in payload]
        raise VenusApiContractError("GetTrace returned an unexpected response payload")

    async def get_file_asset(self, path: str, asset_type: str = "json") -> bytes:
        """Return a file from the VENUS PC through the asset endpoint.

        Calls ``GET /api/vector/v3/files/asset``. VENUS serves files under its own
        folders (e.g. an ``_SdkRunLog.json`` in ``LogFiles``, with ``asset_type="json"``),
        so this also works against a VENUS PC other than this one.

        Raises
        ------
        MethodError
            If the file does not exist or the server returns another non-success status.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        # VENUS matches asset paths lower-cased (as its InstrumentViewer sends them).
        response = await self._request(
            "GET",
            "/api/vector/v3/files/asset",
            params={"assetPath": path.lower(), "assetType": asset_type},
            error_prefix="GetFileAsset",
        )
        return response.content

    async def get_file_asset_head(self, path: str, max_bytes: int = 4096, asset_type: str = "json") -> bytes | None:
        """Return the first ``max_bytes`` of a file from the VENUS PC, or ``None`` if VENUS
        does not have it.

        Like :meth:`get_file_asset`, but stops reading once ``max_bytes`` have arrived --
        VENUS ignores HTTP ranges and always sends the whole file -- e.g. to read the
        ``reason`` near the top of a multi-megabyte ``_SdkRunLog.json``. Not retried.

        Raises
        ------
        VenusConnectionError
            If the server is unreachable.
        VenusTimeoutError
            If the server does not answer in time.
        """
        client = self._get_client()
        headers = await self._build_request_headers()
        params = {"assetPath": path.lower(), "assetType": asset_type}
        data = bytearray()
        try:
            async with client.stream(
                "GET", "/api/vector/v3/files/asset", params=params, headers=headers
            ) as response:
                if not response.is_success:
                    return None
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) >= max_bytes:
                        break
        except httpx.ConnectError as exc:
            raise VenusConnectionError(f"Cannot connect to VENUS WebAPI at {self._base_url}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise VenusTimeoutError(f"Request to {self._base_url} timed out: {exc}") from exc
        return bytes(data[:max_bytes])

    # -- error handler endpoints ----------------------------------------------

    async def register_error_handler(self, key: str) -> str:
        """Register as the instrument error handler.

        Calls ``POST /api/vector/v3/error-handler``.  Registration must occur
        before a method is loaded.  Only one error handler can be registered at
        a time; attempting to register when one is already active returns HTTP 409.

        Parameters
        ----------
        key:
            A user-defined alphanumeric key used to identify this error handler.
            Must be saved internally — it is required to unregister and to
            submit error recoveries.

        Returns
        -------
        str
            Confirmation message from the server.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code (e.g. 409 conflict).
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        _logger.debug("register_error_handler: key=%r", key)
        response = await self._request(
            "POST",
            _ERROR_HANDLER_PREFIX,
            json=key,
            error_prefix="RegisterErrorHandler",
        )
        result = response.json()
        _logger.debug("register_error_handler: completed, response=%r", result)
        return str(result)

    async def unregister_error_handler(self, key: str) -> str:
        """Unregister as the instrument error handler.

        Calls ``DELETE /api/vector/v3/error-handler``.  Should not be called
        while a method is running.

        Parameters
        ----------
        key:
            The same key that was used to register as the error handler.

        Returns
        -------
        str
            Confirmation message from the server.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        _logger.debug("unregister_error_handler: key=%r", key)
        response = await self._request(
            "DELETE",
            _ERROR_HANDLER_PREFIX,
            json=key,
            error_prefix="UnregisterErrorHandler",
        )
        result = response.json()
        _logger.debug("unregister_error_handler: completed, response=%r", result)
        return str(result)

    async def get_error_handler_registered(self) -> bool:
        """Check whether an error handler is currently registered.

        Calls ``GET /api/vector/v3/error-handler``.

        Returns
        -------
        bool
            *True* if an error handler is registered, *False* otherwise.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the server is unreachable after all retry attempts.
        """
        response = await self._request(
            "GET",
            _ERROR_HANDLER_PREFIX,
            error_prefix="GetErrorHandlerRegistered",
        )
        return bool(response.json())

    async def submit_error_recovery(self, error_uuid: str, recovery: ErrorRecovery) -> ErrorHandlingResponse:
        """Submit an error recovery action to the VENUS WebAPI.

        Calls ``POST /api/vector/v3/instrument-errors/{error_uuid}/recovery``.

        Parameters
        ----------
        error_uuid:
            The UUID of the error event to recover.
        recovery:
            The ErrorRecovery payload specifying the selected recovery action.

        Returns
        -------
        ErrorHandlingResponse
            The server response containing data, message, and success status.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the request fails due to connection issues.
        VenusApiContractError
            If the response is malformed.
        """
        _logger.debug("submit_error_recovery: error_uuid=%r, action_id=%r", error_uuid, recovery.selected_action_id)
        payload = recovery.model_dump(by_alias=True, exclude_none=True)
        _logger.debug("submit_error_recovery: payload=%r", payload)
        response = await self._request(
            "POST",
            f"{_INSTRUMENT_ERRORS_PREFIX}/{error_uuid}/recovery",
            # exclude_none=True drops genuinely-optional fields (e.g. detailed_error_recoveries,
            # inputs) while preserving non-None sentinel defaults such as selected_action_id=-1,
            # error_handling_key="", and selected_action_is_recovery=False.
            json=payload,
            error_prefix="SubmitErrorRecovery",
        )
        _logger.debug(
            "submit_error_recovery: response status=%d body=%r",
            response.status_code,
            response.text,
        )
        _logger.debug("submit_error_recovery: completed for error_uuid=%r", error_uuid)
        try:
            return ErrorHandlingResponse.model_validate(response.json())
        except Exception as exc:
            raise VenusApiContractError(
                f"SubmitErrorRecovery returned a malformed response: {exc}"
            ) from exc

    async def get_unhandled_errors(self) -> list[ErrorData]:
        """Fetch currently unhandled instrument errors from the VENUS WebAPI.

        Calls ``GET /api/vector/v2/instrument-errors/unhandled``.

        Returns
        -------
        list[ErrorData]
            The list of unhandled instrument errors.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the request fails due to connection issues.
        VenusApiContractError
            If the response is malformed.
        """
        response = await self._request(
            "GET",
            _INSTRUMENT_ERRORS_V2_UNHANDLED_PATH,
            error_prefix="GetUnhandledInstrumentErrors",
        )
        if response.status_code == 204:
            return []
        if not response.text or not response.text.strip():
            return []
        try:
            parsed = ErrorDataResponseModel.model_validate(response.json())
        except Exception as exc:
            raise VenusApiContractError(
                f"GetUnhandledInstrumentErrors returned a malformed response: {exc}"
            ) from exc
        return parsed.data

    async def submit_error_action(self, error_uuid: str, recovery: ErrorRecovery) -> ErrorHandlingResponse:
        """Submit an error action to the VENUS WebAPI.

        Calls ``POST /api/vector/v3/instrument-errors/{error_uuid}/action``.
        This does not resolve the error; a new error event fires afterward.

        Parameters
        ----------
        error_uuid:
            The UUID of the error event to handle.
        recovery:
            The ErrorRecovery payload specifying the selected action.
            The action endpoint accepts the same payload shape as the recovery
            endpoint; the parameter is named ``recovery`` for consistency.

        Returns
        -------
        ErrorHandlingResponse
            The server response containing data, message, and success status.

        Raises
        ------
        MethodError
            If the server returns a non-success HTTP status code.
        VenusConnectionError
            If the request fails due to connection issues.
        VenusApiContractError
            If the response is malformed.
        """
        _logger.debug("submit_error_action: error_uuid=%r, action_id=%r", error_uuid, recovery.selected_action_id)
        payload = recovery.model_dump(by_alias=True, exclude_none=True)
        _logger.debug("submit_error_action: payload=%r", payload)
        response = await self._request(
            "POST",
            f"{_INSTRUMENT_ERRORS_PREFIX}/{error_uuid}/action",
            # exclude_none=True drops genuinely-optional fields (e.g. detailed_error_recoveries,
            # inputs) while preserving non-None sentinel defaults such as selected_action_id=-1,
            # error_handling_key="", and selected_action_is_recovery=False.
            json=payload,
            error_prefix="SubmitErrorAction",
        )
        _logger.debug(
            "submit_error_action: response status=%d body=%r",
            response.status_code,
            response.text,
        )
        _logger.debug("submit_error_action: completed for error_uuid=%r", error_uuid)
        try:
            return ErrorHandlingResponse.model_validate(response.json())
        except Exception as exc:
            raise VenusApiContractError(
                f"SubmitErrorAction returned a malformed response: {exc}"
            ) from exc

    async def notify_run_message_queued(self, event: RunMessageQueuedEvent) -> None:
        """Queue a run-message notification received from the SignalR listener.

        This is part of the public async client surface so event-listener code can
        hand off ``OnRunMessageQueued`` events to ``send_command()``.
        """
        await self._command_dispatcher.notify_run_message_queued(event)

    def notify_runtime_status(self, event: ExecutorEvent, message: str = "") -> bool:
        """Forward runtime-status events to the command dispatcher.

        Returns ``True`` if the event caused a pause/resume transition
        (i.e. the method just became paused or just resumed from a pause),
        ``False`` otherwise.
        """
        before = self._command_dispatcher._method_paused
        self._command_dispatcher._notify_runtime_status(event, message)
        after = self._command_dispatcher._method_paused
        return before != after

    def reset_command_state(self) -> None:
        """Reset command-dispatcher state between method sessions."""
        self._command_dispatcher._reset_abort_state()

    async def send_command(
        self,
        category: str,
        action_name: str,
        parameters: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        """Build a command envelope, send it, and return the parsed response.

        Pushes a command message to the "action" channel via
        ``POST /api/vector/v3/run-messages``. Each command is assigned a unique
        ID which is used to correlate requests with responses.

        When SignalR run-message notifications are enabled, waits for
        ``OnRunMessageQueued`` to indicate an ``action-response`` message is
        available. The method peeks at the queue head and pops the message.
        If the response ID doesn't match the original request, the response
        is cached locally for other concurrent callers. If SignalR is
        unavailable, a final peek is attempted on timeout as a safety net.

        Parameters
        ----------
        category:
            Command category (e.g. ``"System"``, ``"Layout"``, ``"Channels"``).
        action_name:
            Dot-separated action name (e.g. ``"instrument.isConnected"``).
        parameters:
            Action-specific parameters. Defaults to an empty dict.
        timeout:
            Command timeout in seconds. When ``None``, uses the client's configured
            ``command_timeout``.

        Returns
        -------
        CommandResponse
            The parsed response envelope.

        Out-of-order responses for other concurrent callers are cached locally
        until the matching command retrieves them.
        """
        return await self._command_dispatcher.send_command(
            category,
            action_name,
            parameters,
            timeout,
            default_timeout=self._command_timeout,
        )

    async def send_signal_command(
        self,
        category: str,
        action_name: str,
        parameters: dict[str, Any] | None = None,
        timeout: float | None = None,
        *,
        signal_channel: str,
    ) -> CommandResponse:
        """Send a command that signals completion on a non-standard channel.

        Some commands (e.g. ``instrument.init``) do not produce an
        ``action-response`` queue message.  Instead, the executor posts a
        notification to a different channel (such as ``idle``).  This method
        delegates to the dispatcher's ``send_signal_command``.

        Parameters
        ----------
        category:
            Command category (e.g. ``"System"``).
        action_name:
            Dot-separated action name (e.g. ``"instrument.init"``).
        parameters:
            Action-specific parameters. Defaults to an empty dict.
        timeout:
            Command timeout in seconds. When ``None``, uses the client's configured
            ``command_timeout``.
        signal_channel:
            The channel to wait for a SignalR notification on (e.g. ``"idle"``).

        Returns
        -------
        CommandResponse
            A synthetic response indicating success.
        """
        return await self._command_dispatcher.send_signal_command(
            category,
            action_name,
            parameters,
            timeout,
            default_timeout=self._command_timeout,
            signal_channel=signal_channel,
        )

    async def peek_channel(self, channel: str) -> dict[str, Any] | None:
        """Peek a persistent status channel without consuming the message.

        Returns the data dict if a message is present, or *None* if the
        channel is empty.  Suitable for read-only status channels like
        ``connected`` and ``idle``.
        """
        return await self._command_dispatcher.peek_channel(channel)

    async def peek_channel_message(self, channel: str) -> tuple[str, dict[str, Any]] | None:
        """Like :meth:`peek_channel`, but return ``(message_id, data)``, or *None* if empty."""
        return await self._command_dispatcher.peek_channel_message(channel)

    async def delete_channel(self, channel: str) -> None:
        """Delete every message queued on a run-messages channel.

        Calls ``DELETE /api/vector/v3/run-messages/{channel}``. Used before a method
        starts, to clear anything an earlier run left behind.
        """
        await self._command_dispatcher.delete_channel(channel)

"""HTTP routes (settings, API key and connection tokens, status, conversations, health,
shutdown, the local spoke's status webhook) and the conversation WebSocket."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import webbrowser
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from hamilton_workflow_framework.routes_http import build_carrier_sites_router
from pydantic import BaseModel

from backend import connection, model_list, status
from backend import conversations as conversation_store
from backend.agent_runner import AgentRunner
from backend import oidc
from backend.auth_methods import GATEWAY_SSO, AuthError, AuthMethods, GatewaySsoMethod, HelperAddress
from backend.credential_helper import SECRET_HEADER
from backend.config import load_backend_config
from backend.secret_store import ApiKeyStore, SecretStore
from backend.settings_store import SUGGESTED_MODELS, SettingsStore

_logger = logging.getLogger(__name__)

config = load_backend_config()
settings_store = SettingsStore(config)
api_keys = ApiKeyStore(config.api_key_file)
tokens = {"spoke": SecretStore(config.spoke_token_file), "hub": SecretStore(config.hub_token_file)}
# The engine's credential helper (credential_helper.py) asks this app for the company sign-in's
# token on this PC, with a secret made for this launch.
helper_secret = secrets.token_urlsafe(32)
auth_methods = AuthMethods(
    api_keys,
    get_settings=settings_store.get,
    oidc_tokens=oidc.TokenStore(SecretStore(config.oidc_token_file, b"Hamilton AI Assistant sign-in tokens", "sign-in")),
    helper=HelperAddress(f"http://127.0.0.1:{config.port}/api/auth/token", helper_secret),
    engine_home=config.engine_home,
)
runner = AgentRunner(config, settings_store, api_keys, tokens, auth=auth_methods)

router = APIRouter()
router.include_router(build_carrier_sites_router())  # deck viewer: carrier site heights


def _settings_view() -> dict[str, Any]:
    return {
        **settings_store.get(),
        "suggested_models": list(SUGGESTED_MODELS),
        "auth_methods": auth_methods.choices(),
        "api_key_hint": api_keys.hint(),
        "spoke_token_hint": tokens["spoke"].hint(),
        "hub_token_hint": tokens["hub"].hint(),
        **runner.auth_status(),
    }


class SettingsUpdate(BaseModel):
    model: str | None = None
    base_url: str | None = None
    auth_method: str | None = None
    oidc_issuer: str | None = None
    oidc_device_endpoint: str | None = None
    oidc_token_endpoint: str | None = None
    oidc_client_id: str | None = None
    oidc_scopes: str | None = None
    oidc_header: str | None = None
    console_email: str | None = None
    console_sso: bool | None = None
    cloud_provider: str | None = None
    cloud_region: str | None = None
    cloud_profile: str | None = None
    cloud_project: str | None = None
    cloud_resource: str | None = None
    connection: str | None = None
    spoke_url: str | None = None
    hub_url: str | None = None
    hub_spoke: str | None = None
    deck_host: str | None = None


class ThemeUpdate(BaseModel):
    theme: str


class ApiKeyUpdate(BaseModel):
    api_key: str


class TokenUpdate(BaseModel):
    token: str


@router.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    return _settings_view()


@router.put("/api/settings")
async def put_settings(update: SettingsUpdate) -> dict[str, Any]:
    try:
        settings_store.update(**update.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _settings_view()


@router.get("/api/settings/models")
async def get_models(refresh: bool = False) -> dict[str, Any]:
    """The models the saved endpoint offers (its /v1/models), Claude models first; the
    suggested names when it has no list."""
    settings = settings_store.get()
    method = auth_methods.active(settings)
    await method.prepare()
    headers = method.http_headers()
    if headers is None and method.status()["ready"]:  # signed in, but the app holds no token to ask with
        return model_list.suggested("Signed in. These are suggestions; enter the model name your provider uses.")
    return await model_list.list_models(settings.get("base_url") or "", headers, refresh=refresh)


@router.put("/api/settings/api-key")
async def put_api_key(update: ApiKeyUpdate) -> dict[str, Any]:
    try:
        api_keys.set(update.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _settings_view()


@router.delete("/api/settings/api-key")
async def delete_api_key() -> dict[str, Any]:
    api_keys.clear()
    return _settings_view()


def _token_store(kind: str) -> SecretStore:
    if kind not in tokens:
        raise HTTPException(status_code=404, detail="Unknown token.")
    return tokens[kind]


@router.put("/api/settings/token/{kind}")
async def put_token(kind: str, update: TokenUpdate) -> dict[str, Any]:
    try:
        _token_store(kind).set(update.token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _settings_view()


@router.delete("/api/settings/token/{kind}")
async def delete_token(kind: str) -> dict[str, Any]:
    _token_store(kind).clear()
    return _settings_view()


# The main window's light / dark choice. The deck view in its own window runs in a separate
# WebView2 profile, so it can't read it from the main window's saved settings; it follows this.
_ui = {"theme": None}


@router.post("/api/ui/theme")
async def set_ui_theme(body: ThemeUpdate) -> dict[str, Any]:
    if body.theme not in ("light", "dark"):
        raise HTTPException(status_code=400, detail="theme must be light or dark")
    _ui["theme"] = body.theme
    return {"theme": body.theme}


@router.get("/api/status")
async def get_status() -> dict[str, Any]:
    """Everything the status panel shows: the connection, the conversation's instrument
    sessions, the spoke's status (pushed by the local spoke, or the hub's view of the watched
    spoke), VENUS's run state on the instrument PC and, through a hub, the fleet."""
    settings = settings_store.get()
    view = runner.session_view()
    hub = await status.hub_status(connection.hub_status_url(settings)) if settings["connection"] == "hub" else None
    focus = view["focus"] or None
    host = connection.deck_host(settings, (hub or {}).get("spokes"), focus)
    spoke_status = view["spoke_status"] if settings["connection"] == "local" else None
    operator_url = view["operator_ui"] or (connection.LOCAL_OPERATOR_URL if settings["connection"] == "local" else None)
    deck_spoke = None
    if hub is not None:
        deck_spoke = connection.deck_spoke(settings, focus)
        watched = next((s for s in hub["spokes"] if s.get("id") == deck_spoke), None)
        if watched is not None and watched.get("status"):
            spoke_status = {"status": watched["status"], "detail": watched.get("state_detail")}
        operator_url = connection.hub_dashboard_url(settings)
    if spoke_status is not None:
        spoke_status = {**spoke_status, "light": status.STATUS_LIGHT.get(str(spoke_status.get("status")))}
    venus = await status.venus_run_state(host)
    return {
        "connection": settings["connection"],
        "connection_label": connection.describe(settings),
        "theme": _ui["theme"],
        "deck_host": host,
        "deck_spoke": deck_spoke,
        "venus": venus,
        "spoke_status": spoke_status,
        "hub": hub,
        "operator_url": operator_url,
        "activity": _activity(view, venus, spoke_status),
        **{k: view[k] for k in ("focus", "sessions", "last_run", "conversation_id", "title")},
    }


def _activity(view: dict[str, Any], venus: dict[str, Any] | None, spoke_status: dict[str, Any] | None) -> str:
    """What is happening on the instrument, in words: the assistant's own step or question
    first, then a person needed / a hold, a script run, then what VENUS's run state means for
    this conversation's session."""
    if view["activity"] and not view["activity"].startswith("The assistant is thinking"):
        return view["activity"]
    state = (spoke_status or {}).get("status")
    detail = (spoke_status or {}).get("detail")
    if state == "error":
        return f"Waiting for a person: {detail}" if detail else "Waiting for a person to handle an error"
    if state == "hold":
        return f"Stopped: {detail}" if detail else "Stopped, waiting to resume"
    run = view["last_run"] or {}
    if run.get("status") in ("running", "starting", "paused"):
        return f"Script {run.get('script') or ''} {run['status']}".replace("  ", " ")
    session = view["sessions"].get(view["focus"] or "") or {}
    if venus is None or venus.get("error"):
        if view["activity"]:
            return view["activity"]
        if session.get("connected"):  # VENUS slow to answer, but this session is up
            return "Session open, waiting for the next command"
        return (venus or {}).get("error") or "Not reported"
    if venus.get("run_state") == "paused":
        return "VENUS is paused"
    if venus.get("busy"):
        if session.get("connected"):
            return view["activity"] or "Session open, waiting for the next command"
        if session.get("simulated") is not None:
            return view["activity"] or "Session started; instrument not connected yet"
        return "Running a method this conversation didn't start"
    return view["activity"] or venus.get("label") or "Idle"


@router.post("/api/spoke-events")
async def spoke_events(request: Request) -> dict[str, str]:
    """The local spoke's command-event webhook (connection.WEBHOOKS_ENV). Only this PC can
    reach it: the backend listens on 127.0.0.1."""
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Send JSON.") from None
    if isinstance(payload, dict):
        runner.on_spoke_event(payload)
    return {"status": "ok"}


@router.get("/api/conversations")
async def get_conversations() -> dict[str, Any]:
    return {
        "conversations": conversation_store.list_conversations(config.conversations_dir),
        "current": runner.conversation_id,
        "folder": str(config.conversations_dir),
    }


@router.post("/api/settings/test-key")
async def test_api_key() -> dict[str, Any]:
    """Sends a one-token message to the configured endpoint and model -- the same API the
    agent uses, so a gateway (e.g. Abacus) is checked end to end."""
    settings = settings_store.get()
    method = auth_methods.active(settings)
    await method.prepare()
    headers = method.http_headers()
    if headers is None:
        state = method.status()
        if state["ready"]:  # Console / cloud: the engine holds the credentials, so check at conversation start
            who = f" as {state['who']}" if state.get("who") else ""
            return {"ok": True, "message": f"Signed in{who}. This sign-in is used when a conversation starts."}
        raise HTTPException(status_code=400, detail=state.get("problem") or "Not signed in.")
    base_url = settings.get("base_url") or "https://api.anthropic.com"
    model = settings.get("model")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base_url}/v1/messages",
                headers={**headers, "content-type": "application/json"},
                json={"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "Hi"}]},
            )
    except httpx.HTTPError as exc:
        return {"ok": False, "message": f"Could not reach {base_url}: {exc}"}
    if resp.status_code == 200:
        return {"ok": True, "message": f"The sign-in works with {model} at {base_url}."}
    try:  # Anthropic's {"error": {"message": ...}}; gateways vary, so fall back to the raw text
        error = resp.json().get("error")
        detail = str(error.get("message") if isinstance(error, dict) else error or resp.text)
    except (ValueError, AttributeError):
        detail = resp.text
    if resp.status_code in (401, 403):
        return {"ok": False, "message": f"{base_url} rejected {method.rejection()}: {detail[:200]}"}
    return {"ok": False, "message": f"{base_url} answered HTTP {resp.status_code}: {detail[:200]}"}


def _login_method():
    """The active sign-in method, if it has a sign-in step (browser)."""
    method = auth_methods.active(settings_store.get())
    if not hasattr(method, "begin_login"):
        raise HTTPException(status_code=404, detail="This sign-in method has no sign-in step.")
    return method


def _sso() -> GatewaySsoMethod:
    method = auth_methods.get(GATEWAY_SSO)
    if not isinstance(method, GatewaySsoMethod):
        raise HTTPException(status_code=404, detail="Company sign-in is not available.")
    return method


async def _open_in_browser(url: str | None) -> None:
    if url:
        await asyncio.get_running_loop().run_in_executor(None, webbrowser.open, url)


@router.post("/api/auth/login")
async def start_login() -> dict[str, Any]:
    """Starts the active method's sign-in: a device code for the company sign-in (the page shows it
    and the browser opens the verification page), or the command-line tool for Console / cloud (which
    opens the browser itself). GET /api/auth/login says when it is done."""
    method = _login_method()
    try:
        state = await method.begin_login()
    except (oidc.OidcError, RuntimeError) as exc:  # includes AuthError
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if state.get("verification_uri_complete"):  # device code: the app opens the page
        await _open_in_browser(state["verification_uri_complete"])
    return state


@router.get("/api/auth/login")
async def get_login() -> dict[str, Any]:
    method = auth_methods.active(settings_store.get())
    return method.login_state() if hasattr(method, "login_state") else {"state": "idle"}


@router.post("/api/auth/login/open")
async def open_login_page() -> dict[str, Any]:
    """Opens the verification page again (the browser may have been closed or not opened)."""
    state = _login_method().login_state()
    url = state.get("verification_uri_complete") or state.get("verification_uri")
    if state.get("state") != "waiting" or not url:
        raise HTTPException(status_code=409, detail="No sign-in is waiting.")
    await _open_in_browser(url)
    return state


@router.delete("/api/auth/login")
async def cancel_login() -> dict[str, Any]:
    method = auth_methods.active(settings_store.get())
    if hasattr(method, "cancel_login"):
        method.cancel_login()
    return method.login_state() if hasattr(method, "login_state") else {"state": "idle"}


@router.post("/api/auth/logout")
async def sign_out() -> dict[str, Any]:
    method = auth_methods.active(settings_store.get())
    if hasattr(method, "cancel_login"):
        method.cancel_login()
    method.sign_out()
    return _settings_view()


@router.get("/api/auth/token")
async def engine_token(request: Request) -> Response:
    """For the engine's credential helper only: the current company sign-in token. Needs this
    launch's secret, so another program on this PC can't read it."""
    if not secrets.compare_digest(request.headers.get(SECRET_HEADER, ""), helper_secret):
        raise HTTPException(status_code=403, detail="Not allowed.")
    try:
        return Response(await _sso().current_token(), media_type="text/plain")
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "instance": os.environ.get("HAMILTON_APP_INSTANCE_TOKEN", "")}


@router.post("/api/shutdown")
async def shutdown() -> dict[str, str]:
    async def _exit_soon() -> None:
        try:
            await asyncio.wait_for(runner.shutdown(), timeout=45)
        except Exception:
            _logger.warning("Agent shutdown did not finish cleanly", exc_info=True)
        os._exit(0)  # noqa: SLF001 - deliberate hard exit once the agent is closed

    asyncio.create_task(_exit_soon())
    return {"status": "shutting_down"}


@router.websocket("/ws")
async def conversation_socket(websocket: WebSocket) -> None:
    """Client sends {"type": "send", "text"}, {"type": "stop"}, {"type": "new"},
    {"type": "resume", "id"}, {"type": "title", "title"}, {"type": "approval", "id", "approved"} or
    {"type": "form", "id", "action", "content"};
    the server sends a "replay" of the conversation so far, then each event as it happens."""
    await websocket.accept()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    send = queue.put_nowait
    await websocket.send_json(runner.subscribe(send))

    async def pump() -> None:
        while True:
            await websocket.send_json(await queue.get())

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            try:
                if kind == "send":
                    await runner.send(str(message.get("text", "")))
                elif kind == "stop":
                    await runner.stop()
                elif kind == "new":
                    await runner.new_conversation()
                elif kind == "resume":
                    await runner.resume(str(message.get("id", "")))
                elif kind == "title":
                    runner.set_title(str(message.get("title", "")))
                elif kind == "approval":
                    runner.answer_card(str(message.get("id")), message.get("approved") is True)
                elif kind == "form":
                    runner.answer_card(str(message.get("id")), {
                        "action": message.get("action"),
                        "content": message.get("content") if isinstance(message.get("content"), dict) else {},
                    })
            except RuntimeError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        runner.unsubscribe(send)
        pump_task.cancel()

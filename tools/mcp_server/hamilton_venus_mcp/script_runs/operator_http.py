"""A small web page (and JSON API) a person uses to answer a run's prompts.

Served from its own thread on its own port (``HAMILTON_MCP_OPERATOR_HOST`` / ``_PORT``, default
``127.0.0.1:8765``), so it works whether the MCP server itself is on stdio or HTTP. Reading the
state needs no token; answering a prompt needs the operator token (see ``operator_gate``).
Everything the page shows is inserted as text, never as HTML, since a prompt's wording
ultimately comes from a script's run.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from hamilton_venus_mcp.script_runs.manager import RunError, RunManager
from hamilton_venus_mcp.script_runs.operator_gate import OperatorAuthError, OperatorGate

_logger = logging.getLogger("hamilton_venus_mcp.operator")

OPERATOR_HOST_ENV = "HAMILTON_MCP_OPERATOR_HOST"
OPERATOR_PORT_ENV = "HAMILTON_MCP_OPERATOR_PORT"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
TOKEN_HEADER = "x-operator-token"

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Operator</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --bg:#f6f7f9; --card:#fff; --ink:#1b1f24; --muted:#5b6570; --line:#d8dde3; --ok:#1a7f37; --run:#0b5cad; --err:#c62828; }
  @media (prefers-color-scheme: dark) { :root { --bg:#14171a; --card:#1d2126; --ink:#e6e9ec; --muted:#9aa4ae; --line:#2f353b; --ok:#4cc38a; --run:#6aa9ff; --err:#ff7a7a; } }
  body { margin:0; font:15px/1.45 system-ui,sans-serif; background:var(--bg); color:var(--ink); }
  main { max-width:820px; margin:0 auto; padding:16px; }
  h1 { font-size:20px; margin:0 0 12px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px; margin:12px 0; }
  .state { font-weight:600; } .state.idle{color:var(--ok)} .state.running{color:var(--run)} .state.error{color:var(--err)}
  .muted { color:var(--muted); font-size:13px; }
  label { display:block; font-size:13px; color:var(--muted); margin:8px 0 2px; }
  input { width:100%; box-sizing:border-box; padding:7px 9px; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--ink); }
  select { padding:7px 9px; margin:4px 8px 4px 0; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--ink); }
  button { padding:8px 14px; margin:6px 6px 0 0; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--ink); cursor:pointer; font-size:14px; }
  button.abort { border-color:var(--err); color:var(--err); }
  button:disabled { opacity:.5; cursor:default; }
  pre { white-space:pre-wrap; word-break:break-word; margin:6px 0; font-size:13px; }
  #msg { min-height:20px; margin-top:8px; }
</style></head>
<body><main>
<h1>Operator</h1>
<p class="muted">Answer instrument errors raised during a script run on this spoke. When a run hits an error VENUS
cannot recover from on its own, the script pauses and the choices appear below (Repeat, Exclude, Abort ...).
Enter the operator token and your name once; both stay in this browser. Nothing here starts or stops runs.</p>
<div class="card"><span class="state" id="state">...</span> <span class="muted" id="detail"></span>
  <div class="muted" id="run"></div></div>
<div class="card">
  <label for="token">Operator token</label><input id="token" type="password" autocomplete="off" placeholder="HAMILTON_MCP_OPERATOR_TOKEN">
  <label for="who">Your name (recorded with each decision)</label><input id="who" type="text" autocomplete="name">
  <div id="msg" class="muted"></div>
</div>
<div id="prompts"></div>
<script>
const $ = id => document.getElementById(id);
$("token").value = sessionStorage.getItem("op_token") || "";
$("who").value = localStorage.getItem("op_name") || "";
$("token").addEventListener("input", e => sessionStorage.setItem("op_token", e.target.value));
$("who").addEventListener("input", e => localStorage.setItem("op_name", e.target.value));
function el(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
async function send(prompt, choice, label) {
  $("msg").textContent = "Sending...";
  try {
    const r = await fetch("/api/operator/resolve", { method: "POST",
      headers: { "content-type": "application/json", "x-operator-token": $("token").value },
      body: JSON.stringify({ run_id: prompt.run_id, prompt_id: prompt.prompt_id, operator: $("who").value || null, ...choice }) });
    const body = await r.json();
    $("msg").textContent = r.ok ? "Sent: " + label : (body.error || "Failed");
  } catch (e) { $("msg").textContent = "Could not reach the server: " + e; }
  refresh();
}
const resolve = (prompt, action) => send(prompt, { action: action }, action);
// One answer per error group: each row's selected action applies to every channel in that group.
function resolveChannels(prompt, selects) {
  const picks = {};
  for (const { row, select } of selects) for (const uuid of row.detail_uuids || []) picks[uuid] = Number(select.value);
  return send(prompt, { channel_actions: picks }, "per-channel choices");
}
let lastPromptSignature = null;
function render(s) {
  const st = $("state"); st.textContent = s.state; st.className = "state " + s.state;
  $("detail").textContent = s.detail ? " - " + s.detail : "";
  $("run").textContent = s.run ? s.run.script + " | " + s.run.status + " | " + s.run.elapsed_s + "s | " + (s.run.simulate ? "Simulated" : "Live") : "";
  // Only rebuild the prompts when they change: this page refreshes every 2 s, and rebuilding a
  // prompt would reset a dropdown the operator is in the middle of choosing.
  const signature = JSON.stringify([!!s.run, (s.pending_prompts || []).map(p => [p.prompt_id, p.title, p.code, p.options, p.channel_errors])]);
  if (signature === lastPromptSignature) return;
  lastPromptSignature = signature;
  const box = $("prompts"); box.replaceChildren();
  if (!(s.pending_prompts || []).length)
    box.append(el("div", s.run ? "No decision needed right now. This page will show the choices here if the run stops on an error." : "No run in progress. Nothing is waiting for a decision.", "card muted"));
  for (const p of s.pending_prompts || []) {
    const card = el("div", undefined, "card");
    card.append(el("strong", p.title || "Needs a decision"));
    if (p.code) card.append(el("div", "Error code: " + p.code, "muted"));
    const selects = [];
    for (const row of p.channel_errors || []) {
      card.append(el("pre", (row.channels && row.channels.length ? "Channel " + row.channels.join(", ") + ": " : "") + row.message));
      if ((row.actions || []).length && (row.detail_uuids || []).length) {
        const select = document.createElement("select");
        for (const a of row.actions) {
          const o = el("option", a.name); o.value = a.id;
          if (a.id === row.default_action_id) o.selected = true;
          select.append(o);
        }
        selects.push({ row, select }); card.append(select);
      }
    }
    if (selects.length) {
      const apply = el("button", "Apply choices");
      apply.onclick = () => resolveChannels(p, selects);
      card.append(apply);
    }
    const buttons = el("div");
    const access = p.access_actions || [];
    for (const opt of p.options || []) {
      if (access.some(a => a.key === opt)) continue;
      const b = el("button", opt[0].toUpperCase() + opt.slice(1), opt === "abort" ? "abort" : "");
      b.onclick = () => resolve(p, opt); buttons.append(b);
    }
    card.append(buttons);
    // Door / load tray: does not answer the error; the prompt comes back once it is done.
    if (access.length) {
      const row = el("div");
      for (const a of access) {
        const b = el("button", a.label);
        b.onclick = () => send(p, { action: a.key }, a.label + " (the error stays open)"); row.append(b);
      }
      card.append(row);
    }
    box.append(card);
  }
}
async function refresh() {
  try { render(await (await fetch("/api/operator/state.json")).json()); } catch (e) { $("state").textContent = "offline"; }
}
refresh(); setInterval(refresh, 2000);
</script></main></body></html>
"""


def create_app(manager: RunManager, gate: OperatorGate) -> Starlette:
    async def page(_request: Request) -> HTMLResponse:
        return HTMLResponse(_PAGE)

    async def state(_request: Request) -> JSONResponse:
        return JSONResponse(manager.state())

    async def resolve(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "Send a JSON body."}, status_code=400)
        if not isinstance(body, dict) or not body.get("prompt_id"):
            return JSONResponse({"error": "prompt_id is required."}, status_code=400)
        try:
            result = gate.resolve(
                request.headers.get(TOKEN_HEADER),
                body.get("run_id"),
                str(body["prompt_id"]),
                action=body.get("action"),
                channel_actions=body.get("channel_actions"),
                operator=(str(body["operator"])[:80] if body.get("operator") else None),
                source="operator_page",
            )
        except OperatorAuthError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)
        except RunError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(result)

    return Starlette(
        routes=[
            Route("/operator", page),
            Route("/api/operator/state.json", state),
            Route("/api/operator/resolve", resolve, methods=["POST"]),
        ]
    )


@dataclass
class OperatorServer:
    host: str
    port: int
    listening: bool
    error: str | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/operator"

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "listening": self.listening, "error": self.error}


def start_operator_server(manager: RunManager, gate: OperatorGate) -> OperatorServer:
    """Serve the operator page on a background thread. Never raises: a port that cannot be bound
    is reported in the returned handle (and in ``get_spoke_state``) instead of stopping the spoke."""
    import uvicorn

    host = os.environ.get(OPERATOR_HOST_ENV, "").strip() or DEFAULT_HOST
    try:
        port = int(os.environ.get(OPERATOR_PORT_ENV, "") or DEFAULT_PORT)
    except ValueError:
        return OperatorServer(host, DEFAULT_PORT, False, f"{OPERATOR_PORT_ENV} is not a number.")
    server = uvicorn.Server(
        uvicorn.Config(create_app(manager, gate), host=host, port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, name="operator-http", daemon=True)
    thread.start()
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if server.started:
            _logger.info("Operator page at http://%s:%s/operator", host, port)
            return OperatorServer(host, port, True)
        if not thread.is_alive():
            break
        time.sleep(0.05)
    return OperatorServer(host, port, False, f"Could not listen on {host}:{port}.")

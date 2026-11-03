"""python follow_run.py <script> [sim] -- start a REAL run (or a simulated one with "sim") and narrate it: stdout, prompts (with options), decisions, errors, finish."""
import json, sys, time, urllib.request
URL = "http://localhost:8000/mcp"
H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
def post(body, sid=None, timeout=120):
    h = dict(H)
    if sid: h["mcp-session-id"] = sid
    r = urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), h), timeout=timeout)
    msg = None
    for line in r.read().decode().splitlines():
        if line.startswith("data:"): msg = json.loads(line[5:])
    return r.headers.get("mcp-session-id"), msg
sid, _ = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "follow", "version": "0"}}})
post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
_n = [1]
def call(tool, args, timeout=120):
    _n[0] += 1
    _, m = post({"jsonrpc": "2.0", "id": _n[0], "method": "tools/call", "params": {"name": "call_tool_on", "arguments": {"spoke_id": "FM STARlet", "tool_name": tool, "arguments": args}}}, sid, timeout)
    txt = "".join(c.get("text", "") for c in (m.get("result") or {}).get("content", []))
    try: return json.loads(txt)
    except Exception: return {"raw": txt}
T0 = time.time()
def log(*a): print(f"[{time.time()-T0:6.1f}s]", *a, flush=True)
SIMULATE = len(sys.argv) > 2 and sys.argv[2].lower() == "sim"  # default: REAL hardware
run = call("run_script", {"script": sys.argv[1], "simulate": SIMULATE, "max_runtime_s": 1200})
rid = run.get("run_id"); log("started", rid, run.get("status"), run.get("message", ""))
if not rid: sys.exit(1)
since = 0
while True:
    page = call("get_run_events", {"run_id": rid, "since_seq": since, "wait_s": 3, "max_items": 1000}, 60)
    for e in page.get("events", []):
        t = e["type"]
        if t == "stdout": log("stdout:", e["text"])
        elif t == "prompt":
            log("PROMPT", e.get("prompt_id"), "|", e.get("title"), "| options:", e.get("options"))
            for row in e.get("channel_errors") or []:
                log("   channels", row.get("channels"), "->", row.get("message"), "| actions:", [a.get("name") for a in row.get("actions", [])])
        elif t in ("prompt_resolved", "prompt_answered", "operator_decision", "operator_error_deferred", "script_exit", "run_finished", "acknowledged", "prompt_reasked", "prompt_timeout"):
            log(t, {k: v for k, v in e.items() if k not in ("seq", "time", "type", "traceback")})
    since = page.get("next_since_seq", since)
    if page.get("finished"): break
    if time.time() - T0 > 1200: log("gave up"); break
g = call("get_run", {"run_id": rid})
log("FINAL", {k: g.get(k) for k in ("status", "exit_code", "elapsed_s", "error_line", "venus_run_guid", "instrument_serial")})
if g.get("error"): log("ERROR:", (g["error"] or {}).get("message"))
for p in g.get("prompt_history") or []: log("HISTORY", {k: p.get(k) for k in ("prompt_id", "title", "status", "resolution", "operator", "source", "resolved_at", "action", "answer")})
st = call("get_spoke_state", {}); log("spoke afterwards:", {k: st.get(k) for k in ("state", "error_kind", "detail")}, "VENUS:", (st.get("venus_run_state") or {}).get("name"))

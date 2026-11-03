"""Drive T2 on real hardware: pause + resume during cycle 2, abort during cycle 3. One persistent hub session."""
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
sid, _ = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t2", "version": "0"}}})
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

run = call("run_script", {"script": "t2_pause_abort.py", "simulate": False, "max_runtime_s": 900})
rid = run.get("run_id"); log("started", rid, run.get("status"), run.get("message", ""))
if not rid: sys.exit(1)
since = 0; paused_done = resumed_done = aborted = False; pause_t = None
last_stdout_t = time.time()
while True:
    page = call("get_run_events", {"run_id": rid, "since_seq": since, "wait_s": 3, "max_items": 1000}, 60)
    for e in page.get("events", []):
        if e["type"] == "stdout":
            last_stdout_t = time.time(); log("stdout:", e["text"])
            if "Cycle 2/6: picked up" in e["text"] and not paused_done:
                r = call("pause_run", {"run_id": rid}); pause_t = time.time(); paused_done = True
                log("PAUSE requested ->", {k: r.get(k) for k in ("status", "paused", "current_line", "message")})
            if "Cycle 3/6: picked up" in e["text"] and resumed_done and not aborted:
                r = call("abort_run", {"run_id": rid}); aborted = True
                log("ABORT requested ->", {k: r.get(k) for k in ("status", "message")})
        elif e["type"] in ("prompt", "script_exit", "run_finished", "operator_error_deferred", "sim_mode"):
            log(e["type"], {k: v for k, v in e.items() if k not in ("seq", "time", "type", "traceback")})
    since = page.get("next_since_seq", since)
    if paused_done and not resumed_done and time.time() - pause_t > 10:
        g = call("get_run", {"run_id": rid}); st = call("get_spoke_state", {})
        quiet = round(time.time() - last_stdout_t, 1)
        log("while paused: run status =", g.get("status"), "paused =", g.get("paused"), "line =", g.get("current_line"), "| spoke state =", st.get("state"), "| VENUS =", (st.get("venus_run_state") or {}).get("name"), "| no script output for", quiet, "s")
        r = call("resume_run", {"run_id": rid}); resumed_done = True
        log("RESUME requested ->", {k: r.get(k) for k in ("status", "paused", "message")})
    if page.get("finished"): break
    if time.time() - T0 > 900: log("gave up"); break
g = call("get_run", {"run_id": rid})
log("FINAL", {k: g.get(k) for k in ("status", "exit_code", "elapsed_s", "stop_requested", "venus_run_guid", "instrument_serial", "error_line")}, "tips:", {k: (v["remaining"], v["capacity"]) for k, v in (g.get("tips") or {}).items()})
if g.get("error"): log("ERROR:", (g["error"] or {}).get("message"))
time.sleep(3)
st = call("get_spoke_state", {})
log("spoke afterwards:", {k: st.get(k) for k in ("state", "error_kind", "detail")}, "VENUS:", (st.get("venus_run_state") or {}).get("name"))

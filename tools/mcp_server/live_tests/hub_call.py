"""Tiny MCP streamable-http client: python hub.py <tool> [json-args] [url]"""
import json, sys, urllib.request
URL = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:8000/mcp"
H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
def post(body, sid=None, timeout=90):
    h = dict(H)
    if sid: h["mcp-session-id"] = sid
    r = urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), h), timeout=timeout)
    txt = r.read().decode()
    msg = None
    for line in txt.splitlines():
        if line.startswith("data:"): msg = json.loads(line[5:])
    return r.headers.get("mcp-session-id"), msg
sid, _ = post({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"claude-live-test","version":"0"}}})
post({"jsonrpc":"2.0","method":"notifications/initialized"}, sid)
tool = sys.argv[1]
if tool == "--list":
    _, m = post({"jsonrpc":"2.0","id":2,"method":"tools/list"}, sid)
    print("\n".join(t["name"] for t in m["result"]["tools"])); sys.exit()
args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
_, m = post({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":tool,"arguments":args}}, sid)
res = m.get("result") or m
for c in res.get("content", []): print(c.get("text", c))
if res.get("isError"): print("[isError]")
if "error" in m: print(json.dumps(m["error"]))

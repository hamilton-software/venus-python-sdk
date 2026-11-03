# Setting up error monitoring for the MCP and Hub

This guide shows how to be told about instrument errors and operator prompts as they happen,
instead of asking for them: a webhook receiver on your side, an optional long-poll monitor, and
the Hub dashboard and API.

It applies to the **spoke** (`hamilton-venus-mcp`) and the **Hub** (`hamilton-venus-mcp-hub`).
Update both: the Hub only shows what a spoke running the new code reports.

**What you will have at the end**

- A receiver that prints (or forwards) every failed command, held step and operator prompt the
  moment it happens.
- Optionally, a script that watches the same events by polling.
- The Hub dashboard and API showing current problems and a history that stays after the
  instrument recovers.

---

## 1. How errors are reported

Every event has a sequence number (`seq`) and goes to every channel at once, so you can use
whichever suits you:

| Channel | Best for | Set up in |
|---|---|---|
| **Webhook**: the spoke POSTs JSON to your URL | Your orchestrator or alerting | Step 1 |
| **Long poll**: your script asks for new events | A script or AI agent that prefers to pull | Step 3 |
| **Hub dashboard and API** | People, and catching up after being offline | Step 4 |

What you receive depends on the session's error profile and `hold_on_error`:

| Error profile / `hold_on_error` | A failing command ends as | You get |
|---|---|---|
| `cancel_all`, `hold_on_error=False` | An error result at once | `error` |
| `cancel_all`, `hold_on_error=True` | A held step; normal commands are blocked until it is resumed or released | `held` (and status `error`) |
| `standard` (the default profile) | The SDK retries, then raises an operator prompt, and **the command waits** | `operator_prompt`, later `operator_prompt_resolved` |

Under the `standard` profile nothing continues until someone answers the prompt, so treat
`operator_prompt` as "needs attention now".

### Event kinds

| `kind` | Sent when |
|---|---|
| `error` | A `call_sdk_command` step failed and nobody is holding it, including an Abort or an SDK exception. |
| `held` | A step failed and `hold_on_error=True` held it, or `stop_commands` held the stream (`reason` says which). |
| `operator_prompt` | A session command is blocked on an instrument-error prompt, until `resolve_operator_prompt` answers it. |
| `operator_prompt_resolved` | That prompt was answered, or abandoned when the session closed. |
| `status` | The spoke's overall status changed: `idle`, `running`, `error`, `hold`, `paused`, `terminated`. |
| `stop_requested`, `resuming`, `resumed`, `released`, `replay_failed` | Hold lifecycle events. |

### What a webhook body looks like

Each POST body is one JSON object: the event, plus `spoke` (the spoke's name), `connection_id`
and `kind`.

An `error` event:

```json
{
  "spoke": "star1",
  "connection_id": "54327aeebf914efd9e627c70c3841247",
  "kind": "error",
  "seq": 5,
  "at": 1793286827.62,
  "state": "running",
  "session_id": "afb25e325bda4490bd0673bc26b9debd",
  "type": "command_error",
  "step": 4,
  "command": "tip_pickup",
  "attempt": "original",
  "recovery": false,
  "error_type": "VenusCommandFailedError",
  "message": "Command failed: returnStatus='Error', returnCode=0, ... Z drive, Step lost on Z drive ...",
  "held": false
}
```

An `operator_prompt` event:

```json
{
  "spoke": "star1", "connection_id": "...", "kind": "operator_prompt",
  "seq": 8, "at": 1793288705.04, "session_id": "...",
  "type": "operator_prompt",
  "error_uuid": "44d3c540-11cc-4a47-b911-05b7826eda62",
  "code": "P1:02/62",
  "title": "1000ul Channel Tip Pick Up (Single Step) - Error",
  "top_level_actions": ["abort", "cancel"],
  "access_actions": [],
  "channel_error_count": 1,
  "timestamp": "2026-10-29T15:45:05.039507+00:00"
}
```

Notes:

- `at` is epoch seconds.
- `message` is cut to 400 characters. The full text is in the caller's result and in
  `get_command_journal`.
- A prompt's per-channel detail (`channel_errors`) is not in the webhook. Read it with
  `get_recent_events`, or from `pending_operator_prompts` in `get_spoke_state`.

---

## Step 1. Set up a webhook

### 1a. Run a receiver your spoke can reach

The spoke POSTs to your URL, so the URL must work **from the spoke's PC**, not just from yours.
Use your orchestrator PC's network address (not `localhost`) and allow the port through its
firewall.

Delivery is best effort: one attempt, a 5 s timeout, and failures are only logged on the spoke.
Reply `200` quickly and do any slow work (email, paging) afterwards.

A minimal receiver (Python standard library only):

```python
# receiver.py -- run: python receiver.py 9100
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def handle(event: dict) -> None:
    kind = event.get("kind")
    spoke = event.get("spoke")
    if kind == "error":
        print(f"[{spoke}] step {event['step']} {event['command']} FAILED: {event['message'][:200]}")
    elif kind == "held":
        print(f"[{spoke}] step {event['step']} {event['command']} HELD ({event.get('reason')}): {event.get('message')}")
    elif kind == "operator_prompt":
        print(f"[{spoke}] NEEDS AN OPERATOR {event['code']}: {event['title']} options={event['top_level_actions']}")
        # answer it with the spoke tool resolve_operator_prompt(error_uuid, action)
    elif kind == "operator_prompt_resolved":
        print(f"[{spoke}] prompt {event['error_uuid']} answered: {event.get('action')}")
    elif kind == "status":
        print(f"[{spoke}] status {event.get('previous')} -> {event.get('status')} {event.get('detail') or ''}")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)  # reply first: the spoke only waits 5 s
        self.end_headers()
        try:
            handle(json.loads(body))
        except Exception as exc:  # never let one bad event stop the receiver
            print("could not handle event:", exc)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9100
    print(f"listening on :{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
```

### 1b. Point the spoke at it (pick one)

**At startup, permanent.** In the spoke's `Start MCP Spoke.bat`, before the line that starts the
spoke, add this (no spaces around `=`; separate several URLs with commas; every event kind is
sent):

```bat
set HAMILTON_MCP_HOLD_WEBHOOKS=http://orchestrator-pc:9100/events
```

**At run time, per URL and filtered by kind.** Call the spoke tool `subscribe_command_events`,
for example with the orchestrator client:

```python
from orchestrator_client.orchestrator_session import subscribe_command_events

SPOKE_URL = "http://instrument-pc:8000/mcp"   # the spoke's own MCP URL; (hub URL, "spoke_id") works too
subscribe_command_events(
    SPOKE_URL, None, "http://orchestrator-pc:9100/events",
    kinds=["error", "held", "operator_prompt", "operator_prompt_resolved"],   # None = everything
)
```

A subscription made this way is **lost when the spoke restarts**, so send it again each time you
start a session, or use the startup setting instead. Subscribing the same URL again replaces its
kinds.

Related spoke tools: `list_command_event_subscriptions` shows what is subscribed, and
`unsubscribe_command_events(url)` removes one.

### 1c. The Hub's own subscription

The Hub subscribes itself to every spoke automatically, so its dashboard updates at once. Your
receiver and the Hub get **identical payloads**; adding yours does not change what the Hub sees.

- If the spokes reach the Hub by a different address than the Hub would guess, set
  `HAMILTON_MCP_HUB_URL` in `Start MCP Hub.bat` (for example `http://hub-pc:8000`).
- Set `HAMILTON_MCP_HUB_EVENT_PUSH=0` to turn the self-subscription off.

---

## Step 2. Check that it works

1. `list_command_event_subscriptions` on the spoke should list your URL.
2. In a **simulated** session, inject a failure and run the command:

   ```text
   set_simulated_error("1mL", "Tip Pick Up", "Z drive: Step lost on Z drive.", channels=[1])
   tip_pickup(channels=[1], tip_pool=...)
   ```

   Your receiver should print the `error` event.
3. For a full end-to-end check, the Hub repository includes
   `hamilton_venus_mcp_hub/verify_error_events.py`. It runs these scenarios against a running spoke
   and Hub, in simulation only: a failure without a hold, a held failure, and an operator prompt.
   It refuses to start if the spoke has a session open, because starting one would replace it.

---

## Step 3. Optional: a monitor that pulls (long poll)

Use this if you would rather not run a receiver, or as a second path in case a webhook is missed.
`wait_for_command_event` returns within about 0.1 s of an event, or after `wait_s` (25 s at most)
with nothing.

```python
# monitor.py
from orchestrator_client.orchestrator_session import wait_for_command_event

URL = "http://instrument-pc:8000/mcp"   # the spoke; or the Hub's URL with SPOKE_ID below
SPOKE_ID = None                          # e.g. "star1" when going through the Hub

seq = 0
while True:
    update = wait_for_command_event(URL, SPOKE_ID, since_seq=seq, wait_s=20)
    if update.get("restarted"):          # the spoke restarted: its numbering began again
        seq = 0
        continue
    seq = update["next_since_seq"]
    for event in update["events"]:
        kind = event["kind"]
        if kind in ("error", "held"):
            print("FAILED", event["step"], event["command"], event["message"])
        elif kind == "operator_prompt":
            print("NEEDS AN OPERATOR", event["code"], event["title"], event["top_level_actions"])
        elif kind == "status":
            print("status ->", event["status"], event.get("detail") or "")
```

`update` also carries `state`, the current `hold` (if any) and `status`. Going through the Hub
works the same way but adds a relay hop, so talk to the spoke directly when you can.

---

## Step 4. Use the Hub

**Overview** shows only what needs attention *now*:

- **On hold**: held commands (`hold_on_error=True`, or a stop).
- **Waiting on an operator**: session operator prompts waiting for an answer.
- The spokes table: **Instrument** (STAR or Vantage), **Status** (`error` while a prompt or hold
  waits) and **Detail** (the prompt title or held step).

**Each instrument's page** (click its name) has **Needs attention** (the same, for that
instrument) and **Instrument errors**: the history, newest first, with time, session, step,
command, kind and message. It stays after the instrument recovers.

**From scripts**, read the same history without opening the dashboard:

```text
GET http://hub-pc:8000/api/spokes/star1/events.json?since=1793286827&kind=error&limit=50
```

- `since` is epoch seconds (leave it out for everything).
- `kind` is `error`, `held` or `operator_prompt`.
- `limit` defaults to 200.
- The result is newest first. To catch up after being offline, pass the newest `at` you already
  have as `since`.

The Hub's MCP tool `get_spoke_errors(spoke_id, since, kind, limit)` returns the same records.
`get_fleet_status` and `/api/status.json` include `recent_errors`, `session_prompts` and
`instrument_type` for every spoke.

The history is held in the Hub's memory: the last 200 per spoke, lost when the Hub restarts. A
prompt record gets `resolved_at` and `resolved_action` once it is answered.

---

## Step 5. Respond to what you are told

- **`error`**: the caller already has the error. Decide whether to retry, skip or stop. If you
  want the stream to stop and wait for recovery instead, start the session with
  `hold_on_error=True` and `error_profile="cancel_all"`.
- **`held`**: recover with `recovery=True` commands, then `resume_commands`,
  `resume_commands_from(step)` or `release_command_hold`.
- **`operator_prompt`**: the command is waiting. Answer with the spoke tool
  `resolve_operator_prompt(error_uuid, action)`, where `action` is one of `top_level_actions`
  (for example `abort` or `cancel`). Cancelling ends that command with an error.
- **Initializing one channel after a Z-drive error without ejecting tips** is not available as a
  command. `instrument_init` initializes the whole instrument, and a raw firmware command needs
  the safety-override token. With `hold_on_error=True` the step is held, so you can recover at
  the instrument and then resume from the held command.

---

## Connecting from another computer

You can run the receiver, the monitor and your orchestrator on a different computer from the
instrument.

- A computer with a STAR installed can drive a networked **Vantage** spoke. This is supported.
- The **spoke** decides from its own VENUS install, whatever the calling computer has installed. A
  Vantage spoke accepts no STAR connection, and a STAR spoke no Vantage one.
- `start_session` asking for the other family is refused with the call to make instead, and
  `run_script` refuses a script that builds the wrong client (validator rule `V028`).
- Leave `instrument_type` out of `start_session` (the orchestrator client does this by default
  now) and the spoke uses the one it is installed for.
- `get_session_status` and `get_spoke_state` report it as `installed_instrument_type`, and the Hub
  shows it next to each spoke.
- A caller cannot override the refusal. The spoke's owner can, to simulate the other family on a
  development PC, by setting `HAMILTON_MCP_ALLOW_INSTRUMENT_MISMATCH=1` where the spoke starts.
- If the spoke cannot tell which family is installed, it refuses nothing.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| No `error` events arrive | Is the spoke on the new code? `get_spoke_state` should contain `recent_errors`. Is your URL in `list_command_event_subscriptions`? Was the spoke restarted since you subscribed (run-time subscriptions are lost)? |
| The receiver gets nothing but the URL looks right | The URL must be reachable from the **spoke's** PC (not `localhost`, unless the receiver is on the same PC). Check the firewall. The spoke logs `Command-event webhook <url> failed` when delivery fails. |
| The Hub shows no history or no instrument type | The spoke is older than the Hub. Update and restart the spoke. |
| The Hub history is empty after a restart | It is held in memory only. Your receiver, or the spoke's `get_command_journal`, is the durable record. |
| `start_session` says it does not accept STAR (or Vantage) connections | The spoke's install is the other family. Leave `instrument_type` out, or use the one named in the message. |
| A command never returns | Under the `standard` profile it may be waiting on an operator prompt. Check `pending_operator_prompts` and answer with `resolve_operator_prompt`. |

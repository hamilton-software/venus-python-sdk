# Hamilton VENUS MCP Guide

This guide covers how AI agents and orchestration software control Hamilton STAR and
Vantage instruments through the Model Context Protocol (MCP). It explains the deployment
modes, what each one can do, its strengths and limits, and how to set it up.

Component READMEs with full tool lists:
[`mcp_server/README.md`](README.md) (spoke),
[`hamilton_venus_mcp_hub/README.md`](../hamilton_venus_mcp_hub/README.md) (hub), and
[`orchestrator_client`](../orchestrator_client/) (client library for orchestrators).

---

## 1. The pieces

```
  AI agent (Claude Code / Desktop / any MCP client)        Orchestrator software ("cards")
            |                    |                                     |
            | stdio or HTTP      | HTTP                                | HTTP (orchestrator_client)
            v                    v                                     v
   +-----------------+     +-----------+   relays tool calls   +-----------------+
   |  Spoke (local)  |     |    Hub    | --------------------> |  Spoke (network) |  one per
   | hamilton-venus- |     | dashboard |  <-- status pushes -- | hamilton-venus-  |  instrument PC
   |      mcp        |     |  fleet    |                       |      mcp         |
   +--------+--------+     +-----------+                       +--------+---------+
            |                                                           |
            v                                                           v
     VENUS + STAR/Vantage (+ HHC, ODTC, tilt, media fill)        VENUS + instrument
```

| Piece | What it is | Runs where |
|---|---|---|
| **Spoke** (`hamilton-venus-mcp`) | The MCP server that actually drives an instrument through the VENUS Python SDK. Every SDK command is available as a tool. | On the instrument PC, which needs VENUS installed. |
| **Hub** (`hamilton-venus-mcp-hub`) | Gives one MCP connection to many spokes. It relays tool calls and serves a fleet dashboard. It has no VENUS dependency. | Any PC with Python 3.12+. |
| **Orchestrator client** (`orchestrator_client`) | A small standard-library Python package for orchestration software. Each "card" or step calls the spoke (or the hub) as a one-shot script. | The orchestrator PC. |

The spoke is the only piece that holds an instrument session. The hub and the
orchestrator client only relay to it.

---

## 2. Choosing a mode

| Mode | Use it when | Who drives it |
|---|---|---|
| **A. Local spoke over stdio** | One person with an AI assistant on the instrument PC. | Claude Code or Claude Desktop starts the spoke itself. |
| **B. Network spoke, direct** | Anything off the instrument PC: an orchestrator, a remote AI, or a single instrument with no hub. **Lowest latency for orchestrators.** | The orchestrator client, or any HTTP MCP client. |
| **C. Hub (fleet)** | Several instruments, a shared dashboard, operators answering errors from one page, or fleet-wide commands. | An AI agent connected to the hub, the dashboard, or an orchestrator in hub mode. |
| **D. Orchestrator cards** | A workflow engine that runs each step as its own script (cards). | `orchestrator_client` against B (recommended) or C. If the orchestrator is on the instrument PC, use `Instrument.local()`: a localhost-only spoke started on demand. |

Each spoke also offers four ways of working, whichever mode it is reached through:

| Way of working | Tools | Summary |
|---|---|---|
| **Interactive session** | `start_session`, `connect_instrument`, `call_sdk_command`, `close_session` | One SDK command per call, with Stop / Resume / Resume From. |
| **Whole-script runs** | `import_script`, `run_script`, `get_run_events`, `pause_run`, ... | A complete validated Python script runs on the spoke. A person answers its errors. |
| **Standalone devices** | `call_sdk_command("hhc_*" / "odtc_*" / "tilt_module_*" / "media_fill_*")` | Benchtop devices driven directly. No session needed. |
| **VENUS-level control** | `get_venus_run_state`, `venus_pause`, `venus_resume`, `venus_abort`, run history and trace | Inspect and control whatever method VENUS is running, whoever started it. |

Sections 4 and 5 describe these.

---

## 3. Deployment modes

### Mode A: local spoke over stdio (AI on the instrument PC)

The MCP client starts the spoke as a child process and talks to it over stdin and stdout.
Nothing listens on the network.

**What you can do**
- Everything a spoke offers: sessions, SDK commands, Stop/Resume, script runs, standalone
  devices and VENUS control.
- Read the SDK's own documentation through `list_sdk_docs` / `read_sdk_doc`, and the
  labware catalog through `search_labware`.

**Strengths**
- The simplest setup: no ports, no firewall rules, no other process to keep running.
- The AI sees the server's built-in instructions, which cover safety, the selector syntax
  and the liquid-class workflow.

**Limits**
- Only that one client on that PC can use it. A hub or orchestrator can't reach it.
- The spoke stops when the client closes. It closes an open session on the way out, so the
  VENUS method doesn't keep running with nobody to stop it. If the client kills it outright,
  the method keeps running, and the next `start_session` refuses until someone confirms it
  can be aborted (`venus_abort`).
- No `/ping`, so hub discovery can't find it. Webhook push still works, because the
  spoke makes outbound calls.

**Setup**
1. Run `VenusPythonSdkInstaller.exe` and tick **Install MCP server for AI agents** and
   **Set up AI assistants**. This installs the Hamilton plugin for Claude Code (the server,
   Hamilton skills and an approval prompt before real hardware moves) and adds the server
   to Claude Desktop. See [AI Assistants](../ai_harness/ai-assistants.md).
2. To register the server by hand instead, run this for Claude Code:
   ```powershell
   claude mcp add --transport stdio hamilton-venus -- "C:\Program Files (x86)\Hamilton\Python\.venv\Scripts\hamilton-venus-mcp.exe"
   ```
   For Claude Desktop, add the following to its `claude_desktop_config.json`
   (Settings > Developer > Edit Config; the Microsoft Store build keeps it under
   `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude`, the classic build under
   `%APPDATA%\Claude`), then restart Claude Desktop:
   ```json
   { "mcpServers": { "hamilton-venus": {
       "command": "C:\\Program Files (x86)\\Hamilton\\Python\\.venv\\Scripts\\hamilton-venus-mcp.exe" } } }
   ```
3. Ask the AI to start a simulated session, for example: *"Start a simulated Vantage
   session with the last deck and show me the tip counters."*

---

### Mode B: network spoke, direct (recommended for orchestrators)

The spoke runs as a long-lived process on the instrument PC and listens for MCP over HTTP
(`streamable-http`). Clients connect to it directly.

**What you can do**
- Everything in Mode A, from any PC on the network.
- Webhook subscriptions, status pushes and the long-poll event feed (section 6).
- Be found and added by a hub. The hub can also reach a direct spoke, so B and C can be
  used together.

**Strengths**
- **Fastest path for step-by-step workflows.** Each command goes straight to the spoke,
  with no relay hop; in testing this was about 3 s round trip against about 7 s through
  the hub.
- The session stays open between calls, so separate card processes share one connected
  instrument and pay the initialization cost only once.

**Limits**
- The spoke has to be kept running, for example from the desktop batch file.
- The firewall has to allow the port (8000 by default).
- **Set a bearer token** (`HAMILTON_MCP_AUTH_TOKEN`, section 7). Without one, anyone who
  can reach the port can drive the instrument; the spoke logs a warning at startup.
- One session per spoke. A later `start_session` silently replaces an earlier one, so
  pass `expected_connection_id` to guard against that.

**Setup**
1. Install with **Install MCP server for AI agents** ticked. The installer writes
   `Start MCP Spoke.bat` in the repository root.
2. In `Start MCP Spoke.bat`, uncomment `HAMILTON_MCP_AUTH_TOKEN` and set a long random
   value, plus any other settings you need (section 8). Double-click it and leave the
   window open.
3. Allow the port through Windows Firewall, and check that the network profile isn't
   *Public* (`Get-NetConnectionProfile`).
4. Point clients at `http://<instrument-pc>:8000/mcp`:
   - **Orchestrator:** `Instrument("http://<instrument-pc>:8000/mcp", token="<token>")`
     (see Mode D).
   - **Claude Code:**
     ```powershell
     claude mcp add --transport http hamilton-venus http://<instrument-pc>:8000/mcp --header "Authorization: Bearer <token>"
     ```
   - **Claude Desktop:** use the `mcp-remote` bridge:
     `"command": "npx", "args": ["mcp-remote", "http://<instrument-pc>:8000/mcp", "--header", "Authorization: Bearer <token>"]`.

---

### Mode C: hub (fleet)

The hub runs on any PC and relays tool calls to registered spokes. Spokes push their
status to it, and it serves a dashboard at `http://<hub>:8000/dashboard`.

**What you can do**
- **Reach any spoke:**
  - `call_tool_on(spoke_id, tool, arguments)` calls any spoke tool, for example
    `call_tool_on("star1", "call_sdk_command", {...})`.
  - `broadcast_tool_call(...)` runs the same tool on every spoke at once and returns
    one result per spoke.
- **Fleet view:**
  - `list_spokes`, `get_fleet_status`, `list_pending_interventions` (script prompts) and
    `list_command_holds` (held command streams).
  - `get_fleet_consumables` (fleet tip and reagent levels).
- **Manage spokes:** `discover_spokes`, `add_spoke` and `remove_spoke`. The spoke list is
  saved across hub restarts.
- **Dashboard:**
  - Live status per spoke: idle, running, error, hold, paused or terminated, in VENUS
    light colors.
  - Connection and session state, the "On hold" card, and the "Needs an operator" panel
    for answering script-run errors (needs the operator token).
  - Low consumables and recent outbound commands.

**Strengths**
- One connection and one dashboard for every instrument.
- Operators answer script-run errors from a browser. Agents can see these prompts but
  can never answer them.
- Spokes push status changes, so the dashboard updates straight away instead of on the
  5 s poll.
- A failed or offline spoke only fails its own calls.

**Limits**
- Every call goes through the hub, which adds latency. For tight step-by-step loops, use
  Mode B.
- The hub keeps no instrument state; sessions live on the spokes. Each relayed call has a
  timeout (`call_timeout_s`, default 30 s), so long calls must raise it.
- Status push needs the spoke to reach the hub's callback address. Set
  `HAMILTON_MCP_HUB_URL` if the hub PC has several networks.
- The dashboard pages have no login, even when the hub's MCP endpoint requires a token.
  Anyone who can open the dashboard can see the fleet, add or remove spokes and, once an
  operator token is set, answer prompts. Keep it on a trusted network.
- Claude Desktop needs the `mcp-remote` bridge or a custom connector to reach it.

**Setup**
1. Run the installer with **MCP Hub** ticked. The hub needs no VENUS, so any PC works.
   This writes `Start MCP Hub.bat`.
2. Start every spoke in Mode B.
3. In `Start MCP Hub.bat`, set:
   - `HAMILTON_MCP_SPOKE_TOKEN` to the spokes' token, or `HAMILTON_MCP_SPOKE_TOKENS` if
     the spokes have different tokens.
   - `HAMILTON_MCP_AUTH_TOKEN`, so that AI clients need a token to use the hub.

   Uncomment any other settings you need (section 8), then double-click it.
4. Open `http://<hub-pc>:8000/dashboard`, click **Search for spokes**, then **Connect**
   and **Add spoke**. Alternatively, set `HAMILTON_MCP_SPOKES=id=url,...` before starting
   the hub.
5. Connect an AI to the hub:
   ```powershell
   claude mcp add --transport http hamilton-venus-hub http://<hub-pc>:8000/mcp --header "Authorization: Bearer <hub token>"
   ```
   Then ask, for example: *"List the spokes and start a simulated session on star1."*
6. To answer script-run errors from the dashboard, set the same
   `HAMILTON_MCP_OPERATOR_TOKEN` on the hub and on the spokes.

---

### Mode D: orchestrator cards (`orchestrator_client`)

Many workflow engines run each step as an independent script, a "card", with nothing
kept in memory between them. `orchestrator_client` is a standard-library-only package
for those scripts. Each call opens a short MCP connection, does one thing, and returns.
The session stays open on the spoke between cards.

**What you can do**
- **Start and finish:** `start()` (Initialize card) opens and connects the session.
  `finish()` (Finish card) closes it, which also turns the status light off.
- **Typed SDK calls:** `Instrument` has a method for every SDK command, with the same
  keyword arguments as `StarClient`/`VantageClient`, for example
  `instrument.aspirate(positions=..., volumes=..., liquid_class=...)`.
- **Stop / Resume / Resume From** (section 4):
  - `instrument.stop()`, `instrument.resume()`, `instrument.resume_from(step)` and
    `instrument.release_hold()`.
  - Recovery commands use the same typed methods on a handle, for example
    `instrument.recovery().tip_eject(...)`.
- **Hold notifications:** `Instrument(..., on_held=callback)` calls back as soon as a step
  is held. Also available: `wait_for_command_event()` and `subscribe_command_events()`.
- **Example cards** in `hamilton_venus_mcp_hub/examples/`: `card_connect`, `card_action`,
  `card_add_reagent`, `card_stop`, `card_recovery_action`, `card_resume` and
  `card_terminate`.

**Strengths**
- Each card's script reads like a normal SDK script.
- **Held steps pause the workflow in place.** When a step is held, the card's call simply
  doesn't return until someone resumes it, so the orchestrator's loop needs no
  error-handling branches.
- The same code works in direct mode (`spoke_id=None`, URL of the spoke) and hub mode
  (URL of the hub plus a `spoke_id`).

**Limits**
- Each card opens its own MCP session on its first call, which costs a few milliseconds.
  Later calls in the same card reuse it, so each costs one HTTP request.
- Nothing closes a session automatically if the workflow dies. Always run a Finish card,
  even on failure.
- A session and a whole-script run can't be active on the same spoke at once.
- The tip-counter dialog (`tip_pool_show_tip_counter`) opens on the instrument PC's
  screen and blocks until someone closes it there.

**Setup**
1. Run the spoke in Mode B (recommended), or Mode C.
2. Make `orchestrator_client` importable on the orchestrator PC: install it, or copy the
   `orchestrator_client` folder next to the card scripts. If the spoke or hub requires a
   token, pass `Instrument(URL, token=...)`, or set `HAMILTON_MCP_AUTH_TOKEN` in the
   orchestrator's environment.
3. Write one script per card. A minimal card set:
   ```python
   from orchestrator_client import Instrument, InstrumentType

   URL = "http://instrument-pc:8000/mcp"          # direct to the spoke
   inst = Instrument(URL)                          # hub mode: Instrument(HUB_URL, "star1")

   # Initialize card -- the returned connection_id can be passed to later cards.
   # session_name is the run's name in VENUS run control and history (default "hamilton-venus-mcp").
   inst.start(simulate=True, instrument_type=InstrumentType.VANTAGE, load_previous_deck=True,
              hold_on_error=True, error_profile="cancel_all", session_name="Plate prep 3")

   # Step card(s)
   inst.tip_pickup(channels=[1, 2, 3, 4, 5, 6, 7, 8], tip_pool="tips1000")
   inst.aspirate(positions="washbuffer@all", channels=[1, 2, 3, 4, 5, 6, 7, 8],
                 volumes=50.0, liquid_class="HighVolume_Water_DispenseJet_Empty")

   # Finish card -- always run it
   inst.finish()
   ```
4. Pass the `connection_id` from the Initialize card to later cards
   (`Instrument(URL, connection_id=...)`). A card then refuses to act on a different
   workflow's session.

#### Orchestrator on the instrument PC: `Instrument.local()`

When the orchestrator runs on the same PC as the instrument, the spoke doesn't need to be
on the network at all. `Instrument.local()` runs it on `127.0.0.1` only and starts it on
demand:

```python
from orchestrator_client import Instrument, InstrumentType

inst = Instrument.local()          # starts the local spoke if needed, then connects to it
inst.start(simulate=True, instrument_type=InstrumentType.VANTAGE, load_previous_deck=True)
inst.tip_pickup(channels=[1, 2, 3, 4, 5, 6, 7, 8], tip_pool="tips1000")

Instrument.local_status()   # running? pid, url, uptime, log file -- never starts it
Instrument.local_health()   # process, /ping, MCP round trip, VENUS reachable -> "healthy"
Instrument.stop_local()     # closes any open session first, then stops the spoke
```

- **Starting:** every card can call `Instrument.local()`. The first one starts the spoke;
  later ones find it running in a few milliseconds. If two cards start at the same moment,
  only one spoke is started.
- **Background process:** the spoke runs detached and outlives the card that started it. It
  logs to `%LOCALAPPDATA%\Hamilton\mcp_local_spoke\spoke-<port>.log`.
- **Security:** nothing else on the network can reach it, so it needs no token, firewall
  rule or HTTPS.
- **Finding the spoke:** it is found automatically. `HAMILTON_MCP_SPOKE_EXE` sets it
  explicitly, and `exe=` overrides both.
- **Spokes started another way:** a spoke started some other way on the same port, for
  example `Start MCP Spoke.bat` with `HAMILTON_MCP_HOST=127.0.0.1`, is used as-is. It can be
  checked and stopped the same way.
- **Stopping:** `stop_local` closes an open session first, so the VENUS method ends cleanly
  and the light goes off. It refuses while a script run is in progress, unless
  `force=True`.
- **Example card:** `card_local_server.py` does start, status, health or stop, and exits 1
  when the spoke is unhealthy.
- **Example workflow cards:** `card_local_add_reagent.py` (opens a session if none is open,
  then adds reagent with the same tips) and `card_local_terminate.py` (closes the session,
  optionally stopping the local spoke).

---

## 4. Ways of working on a spoke

### Interactive session (one command at a time)

**What you can do**
- **Session:** `start_session` (simulate or real hardware, STAR or Vantage, deck layout,
  `hold_on_error`, `error_profile`), then `connect_instrument`. The user always chooses
  simulation vs live and the deck layout:
  - From an app that can show forms (Claude Code, Claude Desktop), `start_session`
    always asks the user simulation or live, then boots the client (no instrument
    connection) and asks for a blank layout, the last layout used (with a summary of its
    carriers, labware and tip pools) or a saved layout. Whatever the AI passed is only
    pre-selected in those forms.
  - When the app can't show forms (the hub, scripts), `simulate` must be passed. A call
    without a deck choice returns `deck_choice_required` with the options for the AI to
    ask about (always blank, the last layout used and the saved layouts), then
    `select_deck_layout` loads the answer and connects the instrument (`connect=False` only
    loads it). `connect_instrument` refuses until a layout is chosen.
  - Scripts and orchestrators pass `deck_name`, `load_previous_deck=True` or
    `blank_deck=True` and are never asked. `orchestrator_client` sends `blank_deck=True`
    when no layout is given.
  - **Run name:** `session_name` names the session's run in VENUS run control, run
    history and the run log's file name, for example `"Plate prep 3"`. This is how a
    script's file name names its run. Without it the run is `hamilton-venus-mcp`. Use
    letters, digits, spaces, `-` and `_`, up to 64 characters. `get_session_status`
    reports it, and `orchestrator_client`'s `start(..., session_name=...)` passes it on.
- **Commands:** `call_sdk_command(name, kwargs)` runs any SDK command.
  `list_sdk_commands` and `describe_sdk_command` show what exists and its parameters.
  `send_raw_command` is a fallback.
- **Waiting on a value:** `poll_sdk_command_until` checks a value on the spoke itself
  (for example a temperature or "is idle") instead of one network call per check.
- **Errors:** `get_recent_events` shows trace lines and operator prompts, and
  `resolve_operator_prompt` answers a prompt in the session.
- **Testing errors:** `set_simulated_error` / `clear_simulated_errors` make errors happen
  in simulation.

**Stop / Resume / Resume From:**
- **Step numbers.** Every normal command gets a step number, and the spoke keeps a
  journal of them for the session.
- **Holds.** With `hold_on_error=True`, a command whose error ends in **Cancel** is
  **held** instead of failing; VENUS keeps running. `stop_commands()` holds the *next*
  command before it runs.
- **Recovery while held.** Commands sent with `recovery=True` (door unlock/lock, tip
  eject/pickup) run straight away and are never replayed. Any other command is refused
  until the hold is resolved.
- **Ways to continue:**
  - `resume_commands()` re-runs the held step.
  - `resume_commands_from(step)` replays the earlier successful steps from `step` on,
    then re-runs the held step.
  - `release_command_hold()` fails the held step.
- **Make errors end in Cancel.** Use `error_profile="cancel_all"`. Under the `standard`
  profile errors are retried first and then go to an operator prompt. An **Abort** ends
  the VENUS method and can never be resumed.

**Strengths**
- Full SDK coverage, discovered automatically, so new SDK commands appear with no MCP
  changes.
- Fine-grained control and recovery in place, with no re-initialization.

**Limits**
- A network round trip per command.
- One session per spoke, and none while a script run is active.
- Logic such as loops and conditions lives in the caller.

### Whole-script runs

**What you can do**
- **Store and validate:** `import_script` stores a script and checks it against the
  real SDK: commands, arguments, catalog names, and no GUI or unsafe calls.
  `validate_script` checks it again.
- **Run and follow:** `run_script(script, simulate=True)` starts it.
  `get_run_events(wait_s=20)` long-polls its progress, and `get_run` shows its state,
  current line, tips, labware and the liquid seen at each aspirate.
- **Control:** `pause_run`, `resume_run` and `abort_run`.
- **Results:** `get_run_summary` for the outcome, timing, errors and consumables, and
  `get_consumables_usage` / levels for tracking over time.

**Strengths**
- The whole protocol runs on the spoke with no per-step network calls. It is the fastest
  and most robust option for long or loop-heavy protocols.
- Validated before it runs. Simulate is forced unless hardware is explicitly allowed.
- Errors wait for a person on the operator page or hub dashboard; an AI is only ever
  informed.

**Limits**
- Needs `HAMILTON_MCP_OPERATOR_TOKEN`; without it `run_script` is refused.
- Real hardware needs `HAMILTON_MCP_ALLOW_HARDWARE=1`, which can only be set on the
  spoke itself.
- No step-level Resume From. Use pause and resume, or rerun.
- The front status light isn't driven by script runs.

### Standalone devices

`hhc_*` (Hamilton Heater Cooler), `odtc_*` (Inheco ODTC), `tilt_module_*` (MFX tilt
module) and `media_fill_*` commands drive the device directly over its own COM object or
serial port.

- **Strengths:** no session or VENUS method needed. They don't wait behind instrument
  commands.
- **Limits:** they aren't journaled, so Stop/Resume doesn't apply to them. A tilt module
  only moves hardware; pair it with `tilt_labware` so the deck layout matches.

### VENUS-level control

`get_venus_run_state`, `get_venus_current_run_data`, `list_venus_run_history`,
`get_venus_run_detail`, `get_venus_run_trace`, `venus_pause`, `venus_resume` and
`venus_abort`.

- **Strengths:** they work on any method VENUS is running, including ones not started
  through MCP.
- **Limits:** coarse-grained. Pause and abort apply to the whole method.

---

## 5. Recovery walkthroughs

**The reservoir runs dry mid-loop**
1. Start with `hold_on_error=True, error_profile="cancel_all"`.
2. The aspirate fails, is cancelled and is held. The spoke status becomes **error** and
   the light turns red. Webhooks, the hub "On hold" card and the `on_held` callback all
   fire at once.
3. Recovery commands: `front_cover_unlock`, someone refills the reservoir, then
   `front_cover_lock`.
4. `resume()` re-runs the aspirate. The loop's waiting call returns its result and the
   workflow carries on.

**Damaged tips**
1. `stop()`. The status becomes **hold** and the light turns blue. The next command is
   held before it runs.
2. Recovery commands: `tip_eject`, then `tip_pickup`. Optionally unlock the cover to
   inspect the plate, then lock it again.
3. `resume_from(step)`, where `step` is the first step of the affected cycle. It replays
   that cycle with the new tips, then runs the held step.

---

## 6. Status, notifications and the status light

**Spoke status**

| Status | Meaning | Front light (full, progress 5) |
|---|---|---|
| `idle` | A session is open and no command has run for 5 s. Read-only queries (`get_*`, `is_*`, `list_*` and similar) don't count, so polling doesn't wake it. | White |
| `running` | Commands (other than read-only queries), a resume or a script run are in progress. | Green |
| `error` | A step is held on an error, a script prompt is waiting, or a failed run hasn't been acknowledged. | Red |
| `hold` | A stop was requested, or a step is held by it. | Blue |
| `paused` | A script run is paused, or `venus_pause` paused VENUS. | Unchanged |
| `terminated` | No session is open. | Off (progress 0) |

**STAR or Vantage.** The spoke detects which instrument its own VENUS is installed for (not the calling computer's) and refuses the other: `start_session` (leave `instrument_type` out to use the installed one; `installed_instrument_type` in `get_session_status` shows it) and scripts that build the other family's client. So a PC with a STAR installed can drive a networked Vantage, and the Vantage accepts no STAR connection. Only the spoke's owner can lift this, with `HAMILTON_MCP_ALLOW_INSTRUMENT_MISMATCH=1`.

**How to be told about changes, without polling**

| Mechanism | Best for | How |
|---|---|---|
| Webhook | Orchestrator software | `subscribe_command_events(url, kinds)`, or `HAMILTON_MCP_HOLD_WEBHOOKS=url1,url2` at startup. The spoke POSTs JSON for each `status`, `held`, `stop_requested`, `resuming`, `resumed`, `released`, `replay_failed`, `error` (a command failed without being held), `operator_prompt` and `operator_prompt_resolved` event. Delivery is best effort: one attempt, 5 s timeout. |
| Long poll | AI agents and watcher loops | `wait_for_command_event(since_seq, wait_s=20)` returns within about 0.1 s of an event. Loop on `next_since_seq`. |
| Callback | The card whose command was held | `Instrument(..., on_held=fn)`. |
| Hub dashboard | People | The hub subscribes itself to every spoke and shows the status at once, plus the "On hold" card and a card for session operator prompts that are waiting. Each instrument's page has a "Needs attention" card and an "Instrument errors" list (failed commands, holds and operator prompts, with command, step, session and time) that stays after the instrument recovers. |
| Status light | People at the instrument | Automatic (table above). `HAMILTON_MCP_STATUS_LIGHT=0` turns it off. |

---

## 7. Safety

- **The user chooses simulation or live.** `start_session` has no default: it asks the
  user, or the AI has to. `run_script` defaults to `simulate=True`. Script runs on real
  hardware also need `HAMILTON_MCP_ALLOW_HARDWARE=1` on the spoke.
- **People answer script errors, not AI.** Script-run prompts can only be answered with
  the operator token, on the operator page or the hub dashboard. Agents never receive the
  token.
- **Guard against the wrong session.** Pass `expected_connection_id` so a card or agent
  never acts on another workflow's session.
- **Bearer tokens on the network.**
  - **Spoke:** with `HAMILTON_MCP_AUTH_TOKEN` set, every request needs
    `Authorization: Bearer <token>`. Only `/ping` stays open, and it returns just the
    spoke's name and whether a token is required. Without a token, the spoke logs a
    warning at startup.
  - **Hub:**
    - It sends each spoke its token: `HAMILTON_MCP_SPOKE_TOKEN` for all spokes, or
      `HAMILTON_MCP_SPOKE_TOKENS=id=token,...` per spoke.
    - Its own `/mcp` endpoint can require `HAMILTON_MCP_AUTH_TOKEN`. Otherwise the hub
      would be an open way to reach protected spokes.
    - The callback that spokes push status to is signed with a per-spoke key, so nobody
      else can post fake statuses.
  - **Where tokens live:** only in environment variables. They are never stored in
    `spokes.json` or passed through a tool call.
  - **What a token is:** a shared secret, not per-user accounts. Anyone with the token has
    full control. Use a long random value, change it if it leaks, and keep everything on
    a trusted network. Plain HTTP doesn't encrypt the token, so anyone who can read the
    network traffic can see it.
- **The dashboard and stdio.** Dashboard pages stay open, because a browser can't send a
  bearer header. A stdio spoke has no network endpoint, so it needs no token.

---

## 8. Settings reference

Set these in the batch files the installer writes. They contain commented-out examples:
remove the leading `::` to enable a line, and put no spaces around `=`.

**Spoke** (`Start MCP Spoke.bat`)

| Variable | Default | Purpose |
|---|---|---|
| `HAMILTON_MCP_TRANSPORT` | `stdio` (the batch file sets `streamable-http`) | `stdio`, `sse` or `streamable-http`. |
| `HAMILTON_MCP_HOST` / `HAMILTON_MCP_PORT` | `127.0.0.1` / `8000` | Address to listen on. Use `0.0.0.0` for the network. |
| `HAMILTON_MCP_AUTH_TOKEN` | not set | **Recommended.** Bearer token required on every request except `/ping`. |
| `HAMILTON_MCP_SPOKE_NAME` | PC hostname | Name shown when a hub searches for spokes. |
| `HAMILTON_MCP_OPERATOR_TOKEN` | not set | Needed for script runs. Use the same value on the hub. |
| `HAMILTON_MCP_ALLOW_HARDWARE` | not set | `1` allows `run_script(simulate=False)`. |
| `HAMILTON_MCP_SCRIPTS_DIR` | `<SDK>\mcp_scripts` | Where stored scripts and run records live. |
| `HAMILTON_MCP_OPERATOR_HOST` / `_PORT` | `127.0.0.1` / `8765` | The operator page for script prompts. |
| `HAMILTON_MCP_PROMPT_ABORT_AFTER_S` | off | Abort a run whose prompt goes unanswered this long. |
| `HAMILTON_MCP_COMMAND_TIMEOUT_S` | `1800` | Per-command timeout inside script runs. |
| `HAMILTON_MCP_STATUS_LIGHT` | on | `0` leaves the front status light alone. |
| `HAMILTON_MCP_IDLE_LIGHT_S` | `5` | Seconds with no command before the status goes from running to idle (green to white). |
| `HAMILTON_MCP_HOLD_WEBHOOKS` | not set | URLs subscribed to all events at startup. |
| `HAMILTON_MCP_COM_TRACE` | off | `1` embeds the firmware COM trace in run logs. |
| `HAMILTON_MCP_VENUS_API_BASE` | `http://localhost:42400/api/vector/v3` | VENUS Web API address. |

**Hub** (`Start MCP Hub.bat`)

| Variable | Default | Purpose |
|---|---|---|
| `HAMILTON_MCP_TRANSPORT` | `streamable-http` | `stdio` disables status push. |
| `HAMILTON_MCP_HOST` / `HAMILTON_MCP_PORT` | `127.0.0.1` (the batch file sets `0.0.0.0`) / `8000` | Address to listen on. |
| `HAMILTON_MCP_SPOKES` | not set | `id=url,...` spokes to add at startup. |
| `HAMILTON_MCP_SPOKES_FILE` | `%PROGRAMDATA%\Hamilton\mcp_hub\spokes.json` | Where added spokes are saved. |
| `HAMILTON_MCP_AUTH_TOKEN` | not set | Bearer token required on the hub's own `/mcp` endpoint. The dashboard stays open. |
| `HAMILTON_MCP_SPOKE_TOKEN` | not set | Token the hub sends to every spoke. |
| `HAMILTON_MCP_SPOKE_TOKENS` | not set | `id=token,...` per-spoke tokens, overriding `HAMILTON_MCP_SPOKE_TOKEN`. |
| `HAMILTON_MCP_OPERATOR_TOKEN` | not set | Lets the dashboard answer script prompts. |
| `HAMILTON_MCP_HUB_URL` | worked out automatically | How spokes reach this hub for status push, for example `http://hub-pc:8000`. |
| `HAMILTON_MCP_HUB_EVENT_PUSH` | on | `0` stops the hub subscribing to spokes' events. |
| `HAMILTON_MCP_DISCOVER_PORTS` / `_PREFIX` / `_TIMEOUT_S` / `_CONCURRENCY` | `8000-8010` / `24` / `0.75` / `100` | Tuning for "Search for spokes". |

---

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| "requires a bearer token", "token was rejected", or HTTP 401. | Give the client the spoke's or hub's `HAMILTON_MCP_AUTH_TOKEN`: `token=` or the environment variable for the orchestrator, `--header` for Claude, `HAMILTON_MCP_SPOKE_TOKEN(S)` for the hub. |
| The client reports "server failed to connect". | Run the `.exe` by hand to see its error. For HTTP, check the firewall and network profile. |
| `start_session` refuses because "VENUS Run Control is RUNNING". | A method not started by this session is running. Close it, or confirm it's safe to clear. |
| An error retries or prompts instead of holding. | The session isn't using `error_profile="cancel_all"`, or `hold_on_error` is off. |
| "Step N is held" on a normal command. | Send recovery commands with `recovery=True` (or `instrument.recovery()`), then resume or release. |
| The hub dashboard status only updates every 5 s. | The spoke can't reach the hub's callback. Set `HAMILTON_MCP_HUB_URL`, and check the hub's firewall. |
| A command hangs with nobody acting. | The tip-counter dialog is open on the instrument PC, or a step is held and waiting for resume. Check `get_command_hold`. |
| Code changes don't take effect. | The running spoke or hub is loading another copy of the code. Update that copy and restart it. |

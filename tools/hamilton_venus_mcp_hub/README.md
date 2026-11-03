# hamilton-venus-mcp-hub

An MCP (Model Context Protocol) hub that fans tool calls out to several networked
`hamilton_venus_mcp` "spoke" servers -- one per instrument PC -- and compiles their
results, so an AI agent can talk to a fleet of Hamilton STAR/Vantage instruments (plus
their HHC/ODTC devices) through a single connection instead of one per PC.

The hub never touches VENUS or the Hamilton SDK directly -- it has no dependency on
`hamilton-venus-sdk` or `hamilton-workflow-framework` at all (see `pyproject.toml`),
only on `mcp`. Every instrument interaction is relayed as an MCP tool call over the
network to a spoke (see the sibling `mcp_server` project), which is the process that
actually needs VENUS installed. That means the hub itself can run on any PC (or VM)
with Python -- it doesn't need to be one of the instrument PCs, doesn't need VENUS, and
doesn't need to be Windows.

Each call to a spoke opens a fresh connection, calls one tool, and closes it again --
deliberately, not an oversight. An earlier version held one persistent connection open
per spoke for the hub's whole lifetime, and killing a spoke while its connection was
held open crashed the *entire hub*, taking every other spoke down with the dead one
(see `spokes.py`'s module docstring). Reconnecting per call costs a few tens of
milliseconds on a LAN -- negligible for this workload, since polling itself already
runs locally on each spoke via `poll_sdk_command_until` rather than over the network --
and means a dead spoke can now only ever fail its own call.

## Prerequisites

- Python 3.12+ on the hub PC. That's it -- no VENUS, no Hamilton SDK.
- One or more `hamilton_venus_mcp` spokes already running with
  `HAMILTON_MCP_TRANSPORT=streamable-http` (see the `mcp_server` project's own README)
  and reachable from the hub PC over the network.
- An MCP-capable client -- Claude Code or Claude Desktop are covered below.

## Install

Run `VenusPythonSdkInstaller.exe` at the repo root and tick **Install MCP Hub**. The hub has no VENUS
dependency, so nothing else needs to be ticked. It installs the `hamilton-venus-mcp-hub` console script into
`.venv\Scripts\` and writes `Start MCP Hub.bat` at the repo root.

## Configure spokes

`HAMILTON_MCP_SPOKES` is **optional** -- the hub starts fine with zero spokes configured and
they can be added afterward from the dashboard (see **Adding/removing spokes at runtime**
below), which is the expected path when the hub was started from the installer's "Start MCP
Hub.bat" with no spoke PCs known yet. To pre-configure some at startup instead, set it to a
comma-separated `id=url` list, one entry per spoke's `streamable-http` endpoint:

```powershell
$env:HAMILTON_MCP_SPOKES = "star1=http://192.168.1.11:8000/mcp,star2=http://192.168.1.12:8000/mcp"
```

This is read once, at hub startup, merged with whatever was persisted from a previous
session (see **Adding/removing spokes at runtime** below) -- on an id collision,
`HAMILTON_MCP_SPOKES` always wins, and a spoke it lists is never itself persisted. You
don't have to get it exactly right up front, though -- see below for changing the spoke
list without restarting the hub, and for finding a spoke's URL automatically instead of
typing it by hand.

By default the hub listens on `streamable-http` at `127.0.0.1:8000` (unlike the spoke,
which defaults to local `stdio` -- a hub is only useful if something else can reach it
over the network). Override with:

```powershell
$env:HAMILTON_MCP_HOST = "0.0.0.0"    # or the hub PC's own LAN IP
$env:HAMILTON_MCP_PORT = "8000"
$env:HAMILTON_MCP_TRANSPORT = "streamable-http"   # or "stdio" for local-only testing
```

If the hub PC is on Windows, remember to add a matching inbound firewall rule for
whatever port you choose, and check the network adapter's connection profile
(`Get-NetConnectionProfile`) if it's on WiFi -- the Public profile (WiFi's common
default) blocks inbound connections more aggressively than Private/Domain.

## Verify it runs standalone

```powershell
.venv\Scripts\hamilton-venus-mcp-hub.exe
```

It connects to every configured spoke, then starts serving. Watch the log for each
spoke's connection attempt, then confirm from another terminal:

```powershell
curl http://127.0.0.1:8000/api/status.json
```

You should see every spoke listed, each with `"connected": true` if it's reachable.
Press `Ctrl+C` to stop.

## Register with Claude Code

The hub runs over `streamable-http`, not `stdio`, so registration differs from the
spoke's:

```powershell
claude mcp add --transport http hamilton-venus-hub http://<hub-host>:8000/mcp
```

`--scope user`/`--scope project` work the same as for any other server. Manage it with
the usual `claude mcp list` / `claude mcp get hamilton-venus-hub` /
`claude mcp remove hamilton-venus-hub`.

### Alternative: `.mcp.json`

```json
{
  "mcpServers": {
    "hamilton-venus-hub": {
      "type": "http",
      "url": "http://<hub-host>:8000/mcp"
    }
  }
}
```

The `"type": "http"` field is required for a remote server entry -- an entry with a
`url` but no `type` is read as a (broken) stdio server instead.

## Register with Claude Desktop

Claude Desktop's `claude_desktop_config.json` only supports local `stdio` servers
directly -- there's no `"url"`/`"type": "http"` entry it understands there (that shape
is Claude Code's, above). For a remote server like this hub, use one of:

- **Settings > Connectors > Add Custom Connector**, pasting the hub's URL. This routes
  through Anthropic's own infrastructure rather than talking to the hub directly from
  your machine, and needs a paid plan -- likely not what you want for a hub that's only
  ever meant to be reachable on the lab's own network.
- **The `mcp-remote` bridge** (needs Node.js/npm installed), which wraps the HTTP
  connection in a local stdio process Claude Desktop can talk to normally:

  ```json
  {
    "mcpServers": {
      "hamilton-venus-hub": {
        "command": "npx",
        "args": ["mcp-remote", "http://<hub-host>:8000/mcp"]
      }
    }
  }
  ```

  Add this under `mcpServers` in `%APPDATA%\Claude\claude_desktop_config.json` (Settings
  > Developer > Edit Config), then fully quit and restart Claude Desktop.

## Security: bearer tokens

| Variable (hub environment) | Effect |
|---|---|
| `HAMILTON_MCP_SPOKE_TOKEN` | Sent as `Authorization: Bearer <token>` to every spoke. This is each spoke's own `HAMILTON_MCP_AUTH_TOKEN`. |
| `HAMILTON_MCP_SPOKE_TOKENS` | `id=token,id2=token2` for spokes with different tokens. Overrides the one above for those ids. |
| `HAMILTON_MCP_AUTH_TOKEN` | The hub's own MCP endpoint (`/mcp`) requires this bearer token. Without it, the hub would be an open way to reach protected spokes. |

- **Where tokens live:** only in the hub's environment, never in `spokes.json` or a tool
  call.
- **Error messages:** a spoke that refuses the hub shows a clear "requires a bearer token"
  or "rejected the hub's bearer token" error, both from `call_tool_on` and on the
  dashboard.
- **Status pushes:** the callback URL that spokes push status to carries a per-spoke key
  derived from these tokens. The hub rejects pushes without it, so nobody can post fake
  statuses.
- **What stays open:** the dashboard pages and their `/api` routes, because a browser
  can't send a bearer header. Keep the hub on a trusted network.

Connect Claude Code to a protected hub with
`claude mcp add --transport http hamilton-venus-hub http://<hub-host>:8000/mcp --header "Authorization: Bearer <token>"`.

## Dashboard: live spoke status + activity monitor

Open `http://<hub-host>:8000/dashboard` in a browser. It shows:

- Every configured spoke, its connection status, when it was last successfully
  reached, and its last error (if any) -- polling `/api/status.json` every ~2s.
- The most recent outbound commands (timestamp, spoke, tool, status, latency) as the
  hub actually sends them -- one row per spoke for a `broadcast_tool_call`, not one
  opaque row for the whole broadcast (capped to the most recent 25 shown, with a note
  when there are more).
- A **Low consumables** card: every spoke's tips/reagents currently below their
  configured threshold, merged into one fleet-wide list (each row links to that
  spoke's own page) -- polls `/api/fleet-consumables.json` every ~15s, the same data
  the `get_fleet_consumables` tool returns. A spoke that can't be reached is named in
  a note under the table rather than silently dropped from it.
- An **Add spoke** form and a **Remove** button per row -- see below.

Styled to Hamilton's OneHamilton design system (Hamilton-blue sidebar, light/dark mode via the header
toggle). The sidebar lists every configured spoke -- click one to open its own page at
`/spokes/{spoke_id}`: that spoke's current run, a consumables table (tip/reagent levels, with a low/ok
pill), and its run history. Shared styling/assets live in `static/hub.css`, `static/hub.js`,
`static/img/`, served from `/static/...`.

## Fleet state, and errors that need a person

Every few seconds the hub asks each spoke for its own `get_spoke_state` and shows the answer next to
its connection status: **idle**, **running** (a script is active; the dashboard adds "paused"),
**error** (a person is needed: a run is waiting on a decision, or the last run failed and has not been
acknowledged), **unreachable**, or **unknown** (an older spoke without script runs). It is the
spoke's own report; the hub adds no state of its own.

- `list_spokes()` includes `state`; `get_fleet_status()` reads every spoke fresh and returns a count
  of each state plus every waiting prompt; `list_pending_interventions()` returns just the prompts.
- The dashboard has a **Needs an operator** panel: one button per option VENUS offers, and, for
  instrument errors, a dropdown per error group of the per-channel actions (Repeat / Exclude / Next)
  with **Apply choices**. Decisions are attributed to the name entered there.
- **Agents cannot answer these.** Answering uses `HAMILTON_MCP_OPERATOR_TOKEN` from the hub's own
  environment (the same value as on the spokes); it is never sent to, or accepted from, an MCP client.
  Without it the dashboard shows the prompts but disables the buttons.

Everything else about scripts (import, run, follow, pause/resume/abort) works through `call_tool_on`
on the spoke's own tools; see the spoke README's "Running whole scripts". When following a run through
the hub, keep the spoke tool's `wait_s` below `call_timeout_s` (for example `wait_s=20`,
`call_timeout_s=30`).

Anyone who can open the dashboard can answer prompts, so bind the hub to a trusted network.

## Adding/removing spokes at runtime

Both the dashboard and the MCP tools can add or remove a spoke without restarting the
hub:

- **From the dashboard**: click **Search for spokes** to scan this network (and this
  computer, on other ports) for spokes that aren't connected yet -- each result shows
  the spoke's own self-reported name (see `HAMILTON_MCP_SPOKE_NAME` in the spoke's own
  README); click **Connect** on one to pre-fill the id/url fields below, edit if you
  want, then **Add spoke**. Click **Remove** on any row in the Spokes table to drop one
  (with a confirmation prompt).
- **From an agent**: `discover_spokes()` to find one, `add_spoke(spoke_id, url)` /
  `remove_spoke(spoke_id)` to register/drop it (see Tools below).
- **Directly**: `GET /api/spokes/discover`, `POST /api/spokes` with a
  `{"id": ..., "url": ...}` JSON body, or `DELETE /api/spokes/{id}`.

**This persists.** Every add/remove here is written to a JSON file (default
`%PROGRAMDATA%\Hamilton\mcp_hub\spokes.json`, override with `HAMILTON_MCP_SPOKES_FILE`)
and reloaded automatically the next time the hub starts -- restarting the hub (or just
stopping and starting it from a shortcut) no longer loses anything added this way. A
spoke the persisted file knows about but can't currently reach is shown offline
(`"connected": false`, state `unreachable`) rather than being dropped or blocking the
hub from starting.

`HAMILTON_MCP_SPOKES` still works exactly as before for scripted/pinned deployments,
and always wins over a persisted entry with the same id on startup -- a spoke sourced
from that env var is itself never written to the persisted file, so it can't silently
outlive being removed from it.

**Discovery tuning** (all optional env vars, same defaults for a typical small LAN):
`HAMILTON_MCP_DISCOVER_PORTS` (default `8000-8010` -- the full range is scanned against
localhost and the hub's own IP specifically, covering a spoke colocated with the hub on
the same machine at a different port; every other host in the subnet is probed only on
the first port in this list), `HAMILTON_MCP_DISCOVER_PREFIX` (default `24`, the subnet
size to scan around the hub's own IP), `HAMILTON_MCP_DISCOVER_TIMEOUT_S` (default
`0.75`, per-candidate ceiling), `HAMILTON_MCP_DISCOVER_CONCURRENCY` (default `100`,
max simultaneous probes).

## Tools

| Tool | Purpose |
|---|---|
| `list_spokes()` | List every configured spoke: connection status and `state` (idle / running / error / unreachable / unknown). |
| `get_fleet_status(refresh=True)` | Every spoke's state, a count of each, and every prompt waiting for a person. |
| `list_pending_interventions(refresh=True)` | Runs waiting for a person, across the fleet, with the options offered. |
| `call_tool_on(spoke_id, tool_name, arguments=None, call_timeout_s=30.0)` | Call any tool on exactly one spoke's own `hamilton_venus_mcp` server -- works uniformly for `start_session`, `call_sdk_command`, `poll_sdk_command_until`, anything that spoke exposes. |
| `broadcast_tool_call(tool_name, arguments=None, spoke_ids=None, call_timeout_s=30.0)` | Call the same tool on every targeted spoke (default: all) concurrently and compile the results into one dict keyed by spoke id. One spoke failing never blocks or fails the others. |
| `discover_spokes()` | Scan this network (and this computer, on other ports) for spokes not already connected. Takes a few seconds -- see above. |
| `add_spoke(spoke_id, url)` | Register a new spoke at runtime and probe it immediately. Persisted -- see above. |
| `remove_spoke(spoke_id)` | Drop a spoke at runtime. Persisted -- see above. |

`call_timeout_s` is a per-call ceiling (default 30s) so one offline spoke fails fast
instead of hanging the caller. Raise it for a tool that's meant to run long -- e.g.
`broadcast_tool_call("poll_sdk_command_until", {"name": "odtc_get_temperature",
"target": 37.0, "tolerance": 0.5, "timeout_s": 120}, call_timeout_s=150)` -- give the
hub's own ceiling headroom above the spoke tool's internal `timeout_s` so it doesn't
fire first.

## Typical usage flow

1. `list_spokes()` to see what's configured and which spokes are currently reachable.
2. `call_tool_on(spoke_id, "start_session", {"simulate": True})` (and
   `"connect_instrument"`) per spoke you're about to use -- the hub has no session state
   of its own; each spoke manages its own exactly as it does standalone.
3. `call_tool_on(spoke_id, "call_sdk_command", {"name": ...})` for one spoke, or
   `broadcast_tool_call("call_sdk_command", {"name": ...})` to run the same command
   across every spoke at once and get back one compiled dict -- e.g. reading every
   STAR's ODTC temperature in a single round trip.
4. `broadcast_tool_call("poll_sdk_command_until", {...})` for a fleet-wide closed-loop
   wait (e.g. "block until every STAR reports idle") -- each spoke runs its own poll
   loop locally, so this is one network round trip per spoke, not one per poll tick.
5. Watch `/dashboard` to see this happening in real time.

## Persistent sessions for an orchestrator built from independent "cards"

Some orchestration/scheduling systems don't run one long-lived Python process --
they run a *workflow* as separate "cards" (an Initialize card, a Show-tip-counter
card, an Add-reagent-to-plate card, a Finish card, ...), each its own independent
script/process invocation with nothing shared in memory between cards. The same
`start_session` / `connect_instrument` / `call_sdk_command` / `close_session` flow
above works for that too, and is still the right tool -- it just needs a shape that
doesn't assume any one process holds the session open. The key fact that makes this
work: **the session (the open `StarClient`/`VantageClient`) already lives on the
spoke process**, not in whichever client happens to be connected to it, and nothing
about an MCP client disconnecting tears it down. So a card doesn't need to hold
anything open -- it opens a brief connection, does its one thing against whatever
session is *currently* open, and exits; a completely separate, later card reaches
that same still-open session the same way.

A ready-to-use reference library and four standalone card scripts live in two
places, both stdlib Python only -- no MCP client library or SDK dependency:

- **`orchestrator_client/`** (a top-level sibling of this hub, not nested inside it --
  it's hub-agnostic, used the same way whether a card talks straight to a spoke or
  through this hub) -- the actual deployable library: `orchestrator_session.py` (the
  `start`/`run`/`status`/`finish` functions below are built on) and, for a typed
  alternative to hand-building `run()`'s kwargs, `instrument.py`/
  `generated_instrument_commands.py` (see "Typed command methods" further down). This
  is a real, independently pip-installable package (`pip install -e
  "C:\...\Python\orchestrator_client"`) -- do that in whatever venv a card, or an IDE
  editing one, needs it in (e.g. the hub's own venv, for real autocomplete over every
  `Instrument` method instead of needing to remember the command catalog). For a
  genuinely bare orchestrator PC with no Python packaging at all, pip isn't required
  either: copy the inner `orchestrator_client/orchestrator_client/` folder as-is
  (it's a real package dir, `__init__.py` included) to sit as a bare sibling next to
  whichever card script(s) you're deploying -- Python auto-adds a running script's own
  directory to `sys.path`, so the sibling package resolves with no further setup.
- **`hamilton_venus_mcp_hub/examples/`** -- the four card scripts below, showing how
  to use that library (`from orchestrator_client import ...`).

Each card script has its settings as plain variables in a clearly marked block near
the top, meant to be edited directly (copy the file per card/workflow rather than
parameterize one shared script), **no command-line arguments** -- matching a card
being its own small script rather than a generic tool invoked differently each time:

- **`card_connect.py`** -- the Initialize card: opens a session and connects the
  instrument (this is where the expensive instrument-init cost, often a minute or
  more, is paid -- once, not once per action). Prints its result as JSON, including
  a fresh `connection_id`.
- **`card_action.py`** -- any "do X" card (Show tip counter, Add reagent to plate,
  Move plate, ...). The *same* script serves every one -- which action a given card
  performs is just editing its own `NAME`/`KWARGS` variables, e.g.:
  ```python
  NAME = "aspirate"
  KWARGS = {"positions": "Plate1@col:1", "volumes": 100.0, "liquid_class": "..."}
  ```
- **`card_terminate.py`** -- the Finish card: closes the session. Always run this at
  the end of a workflow, even on failure.
- **`card_add_reagent.py`** -- a worked example of a card that needs *several*
  related calls, not just one: tip pickup, aspirate, dispense, tip eject, chained on
  one `Instrument` instance (see "Typed command methods" below) within this one
  card's process. Use it as a template for any multi-step card -- the sequence
  itself is the part to change per card.

```bash
# Same PC as the instrument, no hub, simulation -- the defaults each script starts
# with. Edit NAME/KWARGS in a copy of card_action.py per action, then run them in order:
python card_connect.py
# -> {"connection_id": "a1b2c3...", "simulate": true, "connected": true, ...}

python card_action.py   # NAME = "tip_pickup", KWARGS = {"channels": [1,2,3,4,5,6,7,8], "tip_pool": "Tips1000"}
python card_action.py   # (another copy) NAME = "aspirate", KWARGS = {"positions": "Plate1@col:1", "volumes": 100.0, ...}
# -- or, in one card instead of two: python card_add_reagent.py
python card_terminate.py
```

For a separate PC, routed through this hub instead, edit each script's `URL` to the
hub's endpoint and `SPOKE_ID` to `"FM STARlet"` (or whichever spoke); everything
else works the same. Setting `SPOKE_ID` wraps every call in `call_tool_on` (the same
tool a hub-connected agent uses above) -- useful when a card's PC is different from
the instrument's, or the deployment already runs a hub for the rest of the fleet.
Leaving it `None` talks straight to a spoke's own MCP endpoint instead (that spoke
needs `HAMILTON_MCP_TRANSPORT=streamable-http` -- see the `mcp_server` README's
install section; a hub already requires this of every spoke it reaches). Either way
the session itself lives on the spoke process; going through the hub only adds a
relay hop, not a second copy of that state. All four scripts, and the underlying
functions they wrap (`start`/`run`/`status`/`finish` in `orchestrator_session.py`,
and `Instrument` for `card_add_reagent.py`), work identically in both modes.

Load a saved deck layout (`card_connect.py`'s `DECK_NAME`) instead of rebuilding it
with `add_carrier`/`add_plate`/`add_tip_rack` every session -- see `card_action.py`
with `NAME = "deck_get_saved"` to discover a saved name, and `NAME = "deck_save"`,
`KWARGS = {"deck_name": "...", "overwrite": True}` to save one.

**`CONNECTION_ID`: telling "my" session apart from a later, different one.** A
spoke has exactly one session slot, and `start_session` always silently tears down
and replaces whatever was already open -- so if two workflows ever ran against the
same spoke close together, a later card from one could execute against the other's
session instead of its own, with nothing to catch it by default.
`card_connect.py`'s printed `connection_id` is a fresh value every time a session
opens; set it as a later card's `CONNECTION_ID` and that card refuses with a clear
error instead of silently acting on the wrong session if a different one is active
by the time it runs. Two ways to get that value into a later card:

1. **If your orchestrator can carry a value from one card's output into a later
   card's input** (common even in tools that can't hold live objects between
   cards): wire `card_connect.py`'s printed `connection_id` into every later card's
   `CONNECTION_ID`, including the Finish card. Full protection across the whole
   workflow.
2. **If it can't, or that's unclear:** have a card call `orchestrator_session.py`'s
   `status()` function first to read whatever `connection_id` is currently open
   (a few lines -- `from orchestrator_session import status; print(status(URL,
   SPOKE_ID)["connection_id"])` -- is enough for a small "status card" built the
   same way as the other three), then immediately use that same value for its own
   action. This only guards the narrow window within that one card's own two calls,
   not the whole workflow -- weaker, but needs no data-passing between cards at
   all, and it still turns "no session open" (nobody ran the Initialize card, or it
   failed) into a clear error instead of a confusing one from deeper in the SDK.
   Worth checking your orchestrator's own docs for whether it can pass even one
   small string forward -- that upgrades a workflow from this fallback to full
   protection.

A few more things worth knowing before relying on this for unattended operation:

- **Nothing cleans up a session left open by a card process that disappears
  uncleanly.** The session (and the instrument connection) stays open until
  something explicitly closes it (run the Finish card even on a workflow failure)
  or the spoke restarts.
- **A session and a whole-script `run_script` are mutually exclusive on one spoke.**
  `start_session` refuses while a script run is active there, and `run_script`
  refuses while a session is open -- if anything else (the dashboard, an AI agent)
  might run a stored script against this same spoke while a workflow's session is
  open, that call is refused with a clear message rather than silently interfering.
- **The tip-counter dialog still needs a person, once per session.** See "Tip
  counter dialogs cannot be seen through the hub" below -- this design pays that
  cost once per session instead of once per pipetting action, but it still can't be
  answered remotely.

## Typed command methods: Instrument (an ergonomic wrapper over run())

`run(url, spoke_id, name, **kwargs)` works for any SDK command, but `name`/`kwargs`
are just a string and a dict -- nothing checks or autocompletes them, so writing a
card by hand means getting the exact keyword arguments right from memory or by
looking them up. `orchestrator_client`'s `Instrument` class wraps every command from
the SDK's own reflection-based catalog as a real typed method, with the exact same
keyword arguments the base `StarClient`/`VantageClient` method itself takes -- so an
IDE shows real parameter names and types while writing a card, not just a bare
`kwargs` dict:

```python
from orchestrator_client import Instrument, InstrumentType

instrument = Instrument(URL, SPOKE_ID)
instrument.start(simulate=True, instrument_type=InstrumentType.STAR)
instrument.add_carrier(labware_definition="tip_car_480bc", left_track=1, labware_id="test")
instrument.call("some_not_yet_generated_command", foo=1)   # escape hatch, same as run()
instrument.finish()
```

(Note: the real command is `add_carrier`, not `layout_add_carrier` -- `call_sdk_command`
dispatches directly by the SDK's own method name, with no renaming layer.)

`InstrumentType.STAR` / `InstrumentType.VANTAGE` are the two valid `instrument_type`
values as constants, so the editor offers them and a typo (e.g. "Vantge") can't slip
through to the spoke. The older `STAR` / `VANTAGE` names still work as aliases.

See `hamilton_venus_mcp_hub/examples/card_add_reagent.py` for a full worked card built this way -- several
typed calls (tip pickup, aspirate, dispense, tip eject) chained on one `Instrument`
within a single card, instead of one `card_action.py` copy per call.

Construct one `Instrument` per card script, same as the card model everywhere else
in this file -- nothing on it holds a connection open across process invocations.
`.start()` updates `instrument.connection_id` from the result automatically, so later
calls on that same object are guarded without threading `CONNECTION_ID` through by
hand; `.call(name, **kwargs)` remains available on the same object as the escape
hatch for any command not in the generated set, exactly like `run()`. Both new files
(`instrument.py`, and the generated `generated_instrument_commands.py` it's built
on) are stdlib-only with no `hamilton_venus`/`hamilton_venus_mcp` import, safe to
copy to a thin orchestrator PC exactly like `orchestrator_session.py` already is.

`run()`/`start()`/`status()`/`finish()` in `orchestrator_session.py` remain the
lower-level, always-available option -- `Instrument` is a convenience layer on top
of them, not a replacement. `generated_instrument_commands.py` already ships
committed in this repo, pre-built from the current SDK -- nothing here needs
regenerating as part of installing or running the hub/a spoke/`Instrument` itself.
See "Regenerating `Instrument`'s commands after an SDK upgrade" below for when (and
why) that ever changes. Every generated method's return type is `Any` --
`call_sdk_command`'s response never carries the real SDK return type across the
wire, so the ergonomic win here is on the input side (autocomplete-shaped kwargs),
not the output side.

## Live spoke status on the dashboard

The dashboard's **Status** column shows what each spoke is doing: `idle`, `running`,
`error`, `hold`, `paused` or `terminated`. The colors match VENUS's status light: green
running, red error, blue hold, white idle. Hover over a status for its detail and when it
started.

The spoke pushes each change to the hub as it happens, so the status doesn't wait for the
5 s poll:
- **Automatic subscription.** Each poll checks whether the spoke still lists this hub's
  callback, `http://<this PC>:<port>/api/spoke-events?spoke_id=<id>`, among its webhook
  subscriptions. If not (a new spoke, or one that restarted), the hub calls
  `subscribe_command_events` on it.
- **Holds refresh at once.** A pushed hold, resume or release triggers an immediate
  re-poll of that spoke, so the "On hold" card updates straight away too.
- **Callback address.** The hub works out its own address on the route to each spoke. Set
  `HAMILTON_MCP_HUB_URL` (for example `http://hub-pc:8000`) if spokes can't reach the one
  it picks.
- **Turning it off.** `HAMILTON_MCP_HUB_EVENT_PUSH=0` turns pushing off; the dashboard then
  only updates on its regular poll. A hub running over stdio never subscribes.

## Stop, Resume and Resume From for card workflows

A card workflow can pause in place without aborting VENUS, let someone recover by hand,
and then continue. The spoke does the holding; the full rules are in the spoke README
under "Stop, Resume and Resume From". From the card side:

- **Turn on hold-on-error:** `start(..., hold_on_error=True)` or
  `Instrument.start(hold_on_error=True)`. A command that fails with an error answered as
  **Cancel** is then held, and `run()` / `instrument.<command>()` don't return yet. They
  wait in short `await_command_step` long polls, so no single HTTP/hub call runs long.
  The orchestrator's loop simply pauses on that command. Pass `on_held=` to notify
  someone, or `max_hold_s=` to stop waiting.
- **Stop:** `stop()` (example card: `card_stop.py`) holds the next command the workflow
  sends, before it runs.
- **Recovery while held:** use the same typed SDK methods on a recovery handle. Use it
  for door unlock/lock, tip eject, tip pickup and so on (example card:
  `card_recovery_action.py`). These commands run straight away and are never replayed.

  ```python
  recover = instrument.recovery()
  recover.front_cover_unlock()
  recover.tip_eject(channels=CHANNELS, eject_mode="waste")
  recover.tip_pickup(channels=CHANNELS, tip_pool=TIP_POOL)
  ```

  `with instrument.recovery():` makes the instrument's own calls recovery commands for the
  length of the block. The function-style `recovery_call(url, spoke_id, "tip_eject", ...)`
  still works too.
- **Continue:** `card_resume.py` does one of three things:
  - `resume()` re-runs the held command, and the workflow's waiting call returns its
    result.
  - `resume_from(step)` first replays the earlier successful steps from `step` on, for
    example to add the reagent again after replacing damaged tips. `journal()` /
    `hold_status()` show the step numbers.
  - `release_hold()` gives up, and the waiting call raises `OrchestratorCallError`.

**Errors must end in Cancel.** Start with `start(..., hold_on_error=True, error_profile="cancel_all")`.
Every error is then cancelled straight away, with no retry and no prompt, and held. Under
the `standard` profile an error is retried first, and a simulated error clears on the retry.

**Knowing that a hold happened.** An orchestrator doesn't have to poll for holds:
- `subscribe_command_events(URL, SPOKE_ID, "http://my-orchestrator/hold", kinds=["held"])`
  makes the spoke POST each hold to your endpoint.
- A watcher loop on `wait_for_command_event(URL, SPOKE_ID, since_seq=...)` wakes within a
  fraction of a second.
- The instrument's front status light blinks red while a step is held.
- On the hub, `list_command_holds()` and the dashboard's "On hold" card show every held
  spoke.
- Failures that are not held (the default), and operator prompts a session command is
  blocked on, are published as `error`, `operator_prompt` and `operator_prompt_resolved`
  events. The hub keeps the last 200 per spoke and lists them in the "Instrument errors" card
  on each instrument's page and in each spoke's `recent_errors` in `/api/status.json`, even
  after the hold or prompt has cleared. The overview shows only what is waiting now: the
  "On hold" card and an "instrument error prompt" card for session prompts. The spokes table's "Connection error" column is
  only about reaching a spoke. Each spoke's instrument type (STAR or Vantage, from the spoke's own install)
  is shown next to it on the overview, in the sidebar and on its page, and is `instrument_type` in
  `get_fleet_status`. All of them are available from the hub's memory (nothing is
  sent to the spoke) through `get_spoke_errors(spoke_id, since=None, kind=None, limit=50)`
  and `GET /api/spokes/{spoke_id}/events.json?since=<epoch s>&kind=error|held|operator_prompt&limit=200`,
  newest first; pass the newest `at` you have as `since` to catch up. They are lost when
  the hub restarts.

Talk to a spoke's own URL rather than through the hub when you can: each command then
skips the hub relay hop.

Example: an aspirate in the loop runs the reservoir dry, and the error is answered with
Cancel. The loop is now held at step N. Run `card_recovery_action.py` to unlock the door,
refill the reservoir, then run it again to lock the door. Then run `card_resume.py`: the
aspirate runs again and the loop carries on.

## Tip counter dialogs cannot be seen through the hub

`tip_pool_show_tip_counter`/`tip_pool_show_tip_counters` open a dialog on VENUS's own screen, on
the instrument PC -- through a spoke this is already invisible over the network, and going
through the hub adds nothing: `call_tool_on(spoke_id, "call_sdk_command", {"name":
"tip_pool_show_tip_counter", ...})` just blocks until a person at that instrument closes the
dialog, then returns its result. Treat a long-blocked call to either as normal, not a dead
spoke. For programmatic tip-counter reads/changes (from an agent, a hub-driven script, or
anything else automated), call `tip_pool_get_tip_counter(s)` / `tip_pool_initialize_tip_counter`
/ `tip_pool_reset_tip_counter` / `tip_pool_set_tip_counter` instead -- see the spoke README's
own section on this for the full picture.

## Labware ids are lower-cased on the deck layout

Same caveat as the spoke: VENUS stores every labware id added to a deck layout lower-cased,
regardless of the case it was added with -- a spoke's `call_tool_on(spoke_id, "add_reservoir",
{"labware_id": "Trough1", ...})` is later reported back by that spoke's own tracking/query
tools as `"trough1"`. A `positions` selector string is matched server-side and does not need
lower-casing, but comparing a labware id you typed against one a spoke tool returned does --
see the spoke README's "Labware ids on the deck layout are lower-cased" for the full picture,
including why this matters for `register_reagent`.

## Regenerating `Instrument`'s commands after an SDK upgrade

This is a maintainer step, not an install step -- most people using the hub, a
spoke, or `Instrument` never need to run this.
`orchestrator_client/orchestrator_client/generated_instrument_commands.py` is already
committed to this repo, built from whatever version of `hamilton_venus`
(`StarClient`/`VantageClient`) that commit was generated against; a normal
install/checkout just uses that committed file as-is, the same way it uses any
other committed source file.

It only goes stale if the SDK's own commands change -- a new `hamilton_venus`
release, a new command, a changed signature -- which is a source-code change to
this repo, not something any particular install's environment or VENUS data
affects (contrast with `src/hamilton_venus/tools/generate_catalog.py`'s
labware/liquid-class catalogs, which really do depend on what's installed on
*this* machine's VENUS, and so really are regenerated as part of setup). After
upgrading `hamilton_venus` in this repo, from an environment with both
`hamilton-venus-sdk` and `hamilton-venus-mcp` installed:

```bash
cd orchestrator_client
python generate_instrument_commands.py          # overwrites generated_instrument_commands.py
python generate_instrument_commands.py --check   # (optional) verify without writing -- exits nonzero if out of date
```

Then commit the diff along with the SDK upgrade itself.
`mcp_server/tests/test_generate_instrument_commands.py` regenerates in memory and
compares against the committed file on every normal test run, so a forgotten
regeneration after an SDK change fails that test rather than silently shipping a
stale `Instrument`.

## Troubleshooting

- **A spoke shows `"connected": false`**: check `last_error` in `/api/status.json` (or
  the dashboard) first. Common causes: the spoke process isn't running, it's not on
  `HAMILTON_MCP_TRANSPORT=streamable-http`, a firewall is blocking the port, or the
  hub's `HAMILTON_MCP_SPOKES` URL/port doesn't match what the spoke is actually bound to.
- **A call to one spoke times out around 30s**: that's `call_timeout_s`'s default
  ceiling. If the underlying spoke tool is meant to run longer (e.g.
  `poll_sdk_command_until` with a large `timeout_s`), pass a larger `call_timeout_s` too.
- **A spoke I removed/added keeps coming back the "wrong" way after a restart**:
  `HAMILTON_MCP_SPOKES` always wins over a persisted entry with the same id -- check
  whether that env var is set in the hub's environment and still lists it.
- **Search for spokes finds nothing, but a spoke is definitely running**: confirm the
  spoke is actually on `HAMILTON_MCP_TRANSPORT=streamable-http`/`sse` (`/ping` doesn't
  exist over `stdio`) and that its port is covered by `HAMILTON_MCP_DISCOVER_PORTS`
  (default `8000-8010`) if it's not using the default port -- see **Adding/removing
  spokes at runtime** above.
- **Client shows "failed to connect"**: run the standalone check above first (`curl
  .../api/status.json`) -- if that doesn't respond, the client won't either, and its
  error message won't tell you why.

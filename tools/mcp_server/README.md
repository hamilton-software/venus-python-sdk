# hamilton-venus-mcp

An MCP (Model Context Protocol) server that exposes the Hamilton VENUS Python SDK
(`hamilton_venus.StarClient`) as tools an AI agent can call directly -- start a
session, connect an instrument, discover and run SDK commands, watch trace output,
and resolve operator prompts, all through the same session-management code
(`hamilton_workflow_framework.WorkflowSession`) every Hamilton STAR workflow UI in
this repo uses.

Command discovery and dispatch (`hamilton_venus_mcp/catalog.py`, `coercion.py`) are
reflection-based: every public `StarClient` mixin method -- status, deck, channel,
labware, liquid-class, compound-command, taught-location, device, etc. -- is
automatically callable through `call_sdk_command`, with no per-method registry to
maintain as the SDK grows. (The taught-location commands, e.g.
`register_taught_offset` / `register_taught_position`, are local file I/O that
records teach points into `Active Layout\TaughtLocations.json` for a VENUS method
to enforce -- see the SDK's `docs/star_commands.md`.)

## Prerequisites

- An MCP-capable client -- [Claude Code](https://claude.com/claude-code) or
  [Claude Desktop](https://claude.ai/download) are covered below, but any MCP client
  that supports local stdio servers works the same way.

## Install

Run **`VenusPythonSdkInstaller.exe`** at the repo root and tick the "Install MCP server for AI
agents" checkbox. It sets up `.venv\` (installing `hamilton-venus-sdk` and
running the one-time `setup-venus-sdk` machine setup that `hamilton_venus_mcp` also
depends on) and installs `hamilton-venus-mcp` (this folder) into it in the same run,
then prints the full path to the installed `hamilton-venus-mcp.exe` console script,
which is what you point your MCP client at below.

To reinstall after pulling code changes to this folder, just re-run the installer with
that checkbox ticked again.

## Verify it runs standalone

Before wiring it into a client, confirm the server itself starts cleanly:

```powershell
& .venv\Scripts\hamilton-venus-mcp.exe
```

It should sit there waiting on stdin/stdout (this is normal for a stdio MCP server --
there's no visible "ready" message). Press `Ctrl+C` to stop it. If this fails, fix
that before trying to register it with a client, since a client will just report a
generic "server failed to connect."

## Register with Claude Code

The installer's **Set up AI assistants** option does this for you. It installs the
`hamilton-venus` Claude Code plugin (this server, the Hamilton skills, and an approval
prompt before real hardware moves) and adds the server to Claude Desktop. See
[ai-assistants.md](../ai_harness/ai-assistants.md). To register the server by hand instead:

```powershell
claude mcp add --transport stdio hamilton-venus -- "C:\Program Files (x86)\HAMILTON\Python\.venv\Scripts\hamilton-venus-mcp.exe"
```

Adjust the path if your repo isn't at the default SDK install location. By default
this registers the server at `local` scope (available only to you, in whichever
project directory you run the command from). Pass `--scope user` instead to make it
available across every project, or `--scope project` to share it with a team via a
committed `.mcp.json`.

Manage it afterward with:

```powershell
claude mcp list                 # see all registered servers + connection status
claude mcp get hamilton-venus   # details for this one
claude mcp remove hamilton-venus
```

### Alternative: `.mcp.json`

Instead of the CLI, you can add an entry directly to a `.mcp.json` file (project
root, for `--scope project`-equivalent sharing):

```json
{
  "mcpServers": {
    "hamilton-venus": {
      "command": "C:\\Program Files (x86)\\HAMILTON\\Python\\.venv\\Scripts\\hamilton-venus-mcp.exe"
    }
  }
}
```

## Register with Claude Desktop

Claude Desktop is a separate app from Claude Code with its own config file:

1. Open **Settings > Developer > Edit Config**, or edit the file directly. The Microsoft
   Store build keeps it at
   `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude\claude_desktop_config.json`,
   the classic build at `%APPDATA%\Claude\claude_desktop_config.json`.
2. Add (or merge in) an entry under `mcpServers`:

   ```json
   {
     "mcpServers": {
       "hamilton-venus": {
         "command": "C:\\Program Files (x86)\\HAMILTON\\Python\\.venv\\Scripts\\hamilton-venus-mcp.exe"
       }
     }
   }
   ```
3. Fully quit and restart Claude Desktop for the change to take effect.

If it doesn't show up, check `logs\mcp-server-hamilton-venus.log` in the same folder as
the config file for the server's own stderr output.

## Security: require a bearer token on a network spoke

A spoke on `streamable-http` or `sse` will take commands from anyone who can reach its
port. Set `HAMILTON_MCP_AUTH_TOKEN` to a long random value to require
`Authorization: Bearer <token>` on every request:

- **What stays open:** only `/ping`, which hub discovery uses. It reports nothing more
  than the spoke's name and `auth_required`.
- **Without a token:** a spoke listening on a non-loopback address logs a warning at
  startup.
- **Clients:**
  - **Orchestrator client:** `Instrument(url, token=...)`, `set_auth_token(url, token)`,
    or `HAMILTON_MCP_AUTH_TOKEN` in the orchestrator's environment.
  - **Claude Code:** `claude mcp add --transport http hamilton-venus http://<pc>:8000/mcp --header "Authorization: Bearer <token>"`.
  - **Hub:** `HAMILTON_MCP_SPOKE_TOKEN` (all spokes) or `HAMILTON_MCP_SPOKE_TOKENS=id=token,...`.
- **stdio:** unaffected, since there's no network endpoint.

The token is a shared secret over plain HTTP, so keep spokes on a trusted lab network.

## Safety: the user chooses simulation or live

When the app can show forms (MCP elicitation: Claude Code, Claude Desktop), `start_session`
always asks the user whether to use the VENUS simulator or the real instrument, then boots
the client without connecting the instrument and asks for a blank layout, the last layout
used (with a summary of its carriers, labware and tip pools) or a saved layout. Whatever the
AI passed for `simulate` or the deck is only pre-selected. **Only pass `simulate=False` when
the user chose the live instrument** -- this is also called out in the server's own MCP
instructions text, which the connected agent sees automatically.

Without forms (the hub, scripts, orchestrators), `simulate` is required and an explicit
`deck_name` / `load_previous_deck` / `blank_deck` is used as given. With no deck choice,
`start_session` returns `deck_choice_required` and `deck_options`, and `select_deck_layout`
loads the answer and connects the instrument. `connect_instrument` refuses until a layout is
chosen. A repeated `start_session` with the same mode and instrument that names a layout
while one is pending reuses the open session the same way instead of restarting it.

## Optional: capture the firmware COM trace

Set `HAMILTON_MCP_COM_TRACE=1` in the server's environment to embed VENUS's firmware
communication trace (`.trc`) into each session's `*_SdkRunLog.json` (via
`RunLogConfig.include_com_trace`). Off by default -- it roughly doubles the run-log
size and only helps low-level firmware debugging. The trace file's directory is
resolved from VENUS itself (`GET /api/vector/v3/system/paths`).

## Tools

| Tool | Purpose |
|---|---|
| `start_session(simulate=None, deck_name=None, load_previous_deck=False, blank_deck=False)` | Start (or restart) a `StarClient` session. Tears down any existing session first. Does not connect the instrument yet. Asks the user simulation vs live and the deck layout when they aren't given (see Safety above). |
| `select_deck_layout(deck_name=None, load_previous_deck=False, blank_deck=False, connect=True)` | Load the deck layout the user chose after `start_session` returned `deck_choice_required`, then connect the instrument. |
| `connect_instrument(initialize=False)` | Connect the instrument runtime for the active session (call after `start_session`). |
| `close_session()` | Tear down the active session, disconnecting the instrument. |
| `get_session_status()` | Whether a session is active, whether the instrument is connected, and whether it's in simulate mode. |
| `list_sdk_categories()` | List the distinct SDK command categories (e.g. `Channel`, `Deck`, `TipPool`, `LiquidClass`). |
| `list_sdk_commands(category=None, search=None)` | List available SDK commands, optionally filtered by category or a case-insensitive text search. |
| `describe_sdk_command(name)` | Full docstring, parameter schema, and return type for one command. |
| `call_sdk_command(name, kwargs=None, recovery=False)` | Call a named SDK command with keyword arguments matching its schema. Requires an active, connected session. Each normal STAR/Vantage command gets a `step` number (see [Stop, Resume and Resume From](#stop-resume-and-resume-from)). |
| `stop_commands` / `resume_commands` / `resume_commands_from(step)` / `release_command_hold` / `await_command_step(step)` / `get_command_hold` / `get_command_journal` / `set_hold_on_error` | Hold the command stream in place without aborting VENUS, recover, then re-run the held step or replay from an earlier one. |
| `send_raw_command(category, action_name, parameters=None)` | Advanced fallback: send a structured command directly for anything without a dedicated typed method. |
| `get_recent_events(max_items=50)` | Drain pending SDK trace log lines and `operator_prompt` events from the session's event queue. |
| `resolve_operator_prompt(error_uuid, action)` | Resolve a pending `operator_prompt` event with one of its advertised actions (e.g. `retry`, `ignore`, `abort`). |
| `list_scripts()` / `get_script(name)` / `import_script(...)` / `validate_script(name)` | Manage and check the scripts stored on this spoke (see [Running whole scripts](#running-whole-scripts)). |
| `run_script(script, simulate=True, max_runtime_s=None)` | Start a stored script; returns a `run_id` at once. |
| `get_run(run_id?)` / `list_runs(limit)` / `get_run_events(run_id?, since_seq, max_items, wait_s, types)` | Follow a run: state, tracking (labware, tips, liquid), events, prompts. |
| `pause_run` / `resume_run` / `abort_run` / `acknowledge_run_error` | Control a run, or mark a failed one as seen. |
| `get_spoke_state()` | `idle` / `running` / `error`, the active run, pending prompts, and where the operator page is. |
| `operator_resolve_prompt(...)` | **Human operators only.** Answers a run's prompt; needs the operator token. |
| `get_venus_run_state` / `get_venus_current_run_data` / `list_venus_run_history` / `get_venus_run_detail` / `get_venus_run_trace` / `venus_pause` / `venus_resume` / `venus_abort` | VENUS's own run state, history and pause/resume/abort, whoever started the run. |

## Typical usage flow

This is the flow described in the server's own MCP instructions (visible to any
connected agent automatically), included here for reference:

1. `start_session()` to boot a `StarClient`; the user chooses simulation vs live and the deck layout.
2. `connect_instrument()` to bring the instrument runtime online.
3. `list_sdk_commands()` / `list_sdk_categories()` to discover what's available;
   `describe_sdk_command(name)` to see a command's full parameter schema.
4. `call_sdk_command(name, kwargs)` to run it. `send_raw_command` is a fallback for
   anything without a dedicated typed method.
5. `get_recent_events()` after a call to see SDK trace output; if an instrument
   error raises an `operator_prompt` event, resolve it with
   `resolve_operator_prompt` before retrying.
6. `close_session()` when done.

## Persistent sessions for an orchestrator built from independent "cards"

The same flow above is exactly what an external orchestrator built from separate
"cards" (an Initialize card, a Show-tip-counter card, an Add-reagent-to-plate card,
a Finish card, ... -- each its own independent script/process invocation, not one
long-lived Python process) should use too: nothing needs to hold a session open,
because the session (the open `StarClient`/`VantageClient`) already lives on this
spoke process, not in whichever client happens to be connected to it. A card just
opens a brief connection, does its one thing against whatever session is currently
open, and exits -- a later, completely independent card reaches that same
still-open session the same way, instead of every action paying VENUS's connect +
instrument-init cost on its own.

A ready-to-use, stdlib-only reference library and three standalone card scripts
(`card_connect.py` / `card_action.py` / `card_terminate.py`) are at
`hamilton_venus_mcp_hub/examples/` -- no command-line arguments, just plain
variables near the top of each script to edit directly. They talk directly to this
spoke's own `streamable-http` endpoint when left with `SPOKE_ID = None` (a card on
the same PC as the instrument, or any PC that can reach this spoke directly), or
through the fleet hub with the same scripts otherwise. See that hub's README
("Persistent sessions for an orchestrator built from independent 'cards'") for the
full write-up, both modes' settings, the `connection_id` guard that keeps one
workflow's cards from
silently acting on a different workflow's session, and the operational caveats (no
automatic cleanup on an unclean disconnect, session-vs-`run_script` exclusivity, the
tip-counter dialog below still needing a person once per session) -- plus a typed
`Instrument` wrapper over the same `run()`/`start()`/`finish()` functions (that same
README's "Typed command methods" section), for when hand-writing `run()`'s kwargs
dict by name gets tedious.

## Stop, Resume and Resume From

These let an orchestrator pause where it is, let someone recover by hand, and continue.
VENUS is not aborted. Every normal `call_sdk_command` on the STAR/Vantage gets a step
number, and the spoke keeps them in a journal for the session. A new `start_session` or
`close_session` clears the journal.

- **Hold on error.** Turn this on with `start_session(hold_on_error=True)` or
  `set_hold_on_error(True)`. A command whose instrument error ends in **Cancel** is then
  held instead of failing. Cancel means the step is cancelled and the VENUS method keeps
  listening for commands. The call returns `{"status": "held", "step": N}`, and its caller
  waits with `await_command_step(N)`. The orchestrator client's `run()` does that waiting
  for you, so a card's loop just pauses.
- **Stop.** `stop_commands()` holds the *next* normal command before it runs. A command
  that is already running finishes normally.
- **Recovery while held.** Commands sent with `call_sdk_command(..., recovery=True)` run
  straight away: door unlock/lock, tip eject, tip pickup and so on. They are journaled
  without a step number and are never replayed. Any other normal command is refused
  until the hold is resolved.
- **Resume.** `resume_commands()` re-runs the held step and hands its result to the
  waiting caller. If the step fails again with a Cancel, it stays held.
- **Resume From.** `resume_commands_from(K)` replays the steps from K up to the held
  step, in order, then re-runs the held step. Only steps that succeeded the first time
  are replayed. Use `get_command_journal()` to find the step number. If a replay fails
  with a Cancel, the hold moves to that point and `resume_commands()` carries on from
  there. If a replay is aborted, the held step fails.
- **Give up.** `release_command_hold()` fails the held step, so the waiting caller gets
  an error with `error_type` `"HoldReleased"`.

What can be held:

- **Abort is never held.** An ABORT (`VenusCommandAbortedError`) ends the VENUS method,
  so there is nothing left to resume.
- **Only Cancel triggers a hold.** Make sure the errors you want to hold end in Cancel.
  The `standard` error profile sends, for example, insufficient liquid on aspirate to
  Repeat and then the operator prompt. Answer that prompt with Cancel
  (`resolve_operator_prompt`), or use an error profile whose actions end in CANCEL.
- **Door access during a prompt.** While a prompt is still open, the only instrument
  actions available are the door/tray access actions it offers. After the Cancel, use
  the normal door commands with `recovery=True`.

### STAR or Vantage

A VENUS install is one instrument or the other. The spoke reads which from its own registry (the
instrument config file name: `VStar.cfg` is Vantage, anything else STAR) and reports it as
`installed_instrument_type` in `get_session_status` and `get_spoke_state`. What the calling
computer has installed doesn't matter: a PC with a STAR installed can drive a networked Vantage, but a
Vantage spoke accepts no STAR connection, and a STAR spoke no Vantage one.

- `start_session` uses the installed family when `instrument_type` is left out, and refuses the other
  with the call to make instead.
- `validate_script` / `run_script` refuse a script that builds the other family's client (rule `V028`),
  and the run itself refuses it too.
- A caller cannot override this. The spoke's owner can, to simulate the other family on a development PC,
  by setting `HAMILTON_MCP_ALLOW_INSTRUMENT_MISMATCH=1` where the spoke starts (see `Start MCP Spoke.bat`).
- If the registry can't be read, nothing is refused and the default is STAR.

### Being told about a hold

Every hold, stop, resume and release is a numbered event. There are four ways to hear
about one without polling:

| How | For | Details |
|---|---|---|
| `wait_for_command_event(since_seq, wait_s=20)` | an AI agent, or any watcher loop | Long poll: returns within about 0.1 s of a hold, or after `wait_s` (25 s at most) with no events. Call it again with `since_seq=next_since_seq`. `restarted: true` means the spoke restarted; start again from 0. |
| `subscribe_command_events(url, kinds=None)` | orchestrator software | The spoke POSTs each event as JSON to `url` (one attempt, 5 s timeout). The body includes `spoke`, `connection_id`, `kind`, `step`, `command`, `reason` and `message`. `HAMILTON_MCP_HOLD_WEBHOOKS=url1,url2` subscribes URLs at startup. See also `unsubscribe_command_events` and `list_command_event_subscriptions`. |
| Front status light | a person at the instrument | Uses VENUS's own colors, solid at full progress (5; the range is 0-5): **white** when the session connects and when idle, **green** while commands or a resume run, **red** while a step is held on an error, **blue** after a stop. It goes off (progress 0) when the session closes. It drops back to white after 5 s with no command (`HAMILTON_MCP_IDLE_LIGHT_S`). Control it with `set_status_light_tracking(enabled, idle_after_s)`, or start the spoke with `HAMILTON_MCP_STATUS_LIGHT=0` to leave the light alone. |
| Hub | fleet view | `list_command_holds()` on the hub, plus an "On hold" card and a "HELD at step N" note on the hub dashboard. |

Event kinds are `held`, `stop_requested`, `resuming`, `resumed`, `released`,
`replay_failed`, `status`, `error`, `operator_prompt` and `operator_prompt_resolved`.

You don't need `hold_on_error` to hear about a failure:

- `error`: a command failed and nobody is holding it (the default, `hold_on_error=False`;
  an Abort; or an SDK exception such as a bad argument). The event carries `step`,
  `command`, `error_type`, `message` (400 characters at most), `held: false`, `session_id`
  and `at`.
- `operator_prompt` / `operator_prompt_resolved`: a session command is blocked on an
  instrument error prompt (`error_uuid`, `code`, `title`, `top_level_actions`,
  `channel_error_count`) and then answered by `resolve_operator_prompt`. The spoke status
  is `error` while a prompt waits. `get_recent_events` still carries the full prompt,
  including per-channel errors.
- `held` (with `hold_on_error=True`) is unchanged: the failed step is held and the stream
  blocks until it is resumed or released.

`get_spoke_state` keeps the last 20 of these as `recent_errors` (failed commands, holds
that were errors, and prompts), and the waiting prompts as `pending_operator_prompts`, so
a poll after the instrument has recovered still shows what went wrong. The hub keeps them
too.

### Spoke status

The spoke reports one overall status, whoever is driving it: a whole-script run
(`run_script`) or a session driven one command at a time.

| Status | Meaning | Light |
|---|---|---|
| `idle` | A session is open; nothing has run for `HAMILTON_MCP_IDLE_LIGHT_S` (default 5 s). | white |
| `running` | Commands, a resume or a script run are in progress. | green |
| `error` | A step is held on an error, a script run's or a session command's operator prompt is waiting, or the last script run failed and nobody has acknowledged it. | red |
| `hold` | `stop_commands` was called, or a step is held by it. | blue |
| `paused` | A script run is paused (`pause_run`), or `venus_pause` paused VENUS. | unchanged |
| `terminated` | No session is open. | off |

Each change is a `status` event that carries `status`, `previous`, `detail` and `source`
(`session`, `script` or `venus`). It reaches webhook subscribers and
`wait_for_command_event` the moment it happens. `get_spoke_state` also reports it as
`status`. A hub subscribes itself to these events, as described in the hub README. The orchestrator client's `run(on_held=...)` callback also fires as soon
as its own call is held.

`get_spoke_state` (and so the hub's `get_fleet_status`) reports `command_control`: the
stop/resume state, a short summary of the held step, and `last_event_seq`.
`get_recent_events` carries the same `run_hold` and `run_control` events.

## Running whole scripts

Besides driving one command at a time, the spoke can run a whole Python script, follow it as it
runs, and stop for a **human** when the instrument needs a decision. Scripts live in one folder
on the spoke and are checked against the SDK before they can run.

### Setup

| Environment variable | Purpose |
|---|---|
| `HAMILTON_MCP_OPERATOR_TOKEN` | **Required to run scripts.** The shared secret people use to answer a run's errors. No tool ever returns it, and it is removed from the environment of every script. Set the same value on the hub if you use the hub dashboard. Unset: `run_script` is refused. |
| `HAMILTON_MCP_ALLOW_HARDWARE=1` | Lets `run_script(simulate=False)` drive real hardware. Any other value, or unset, refuses it. It can only be set in the spoke's own environment, not through a tool call. |
| `HAMILTON_MCP_SCRIPTS_DIR` | Where scripts live. Default `<SDK repo>\mcp_scripts`. Run records go in `<folder>\.runs\`. |
| `HAMILTON_MCP_OPERATOR_HOST` / `HAMILTON_MCP_OPERATOR_PORT` | Where the operator page listens. Default `127.0.0.1:8765`. |
| `HAMILTON_MCP_PROMPT_ABORT_AFTER_S` | Optional. Abort a run whose prompt nobody answered within this many seconds. Off by default: an unanswered prompt waits. |
| `HAMILTON_MCP_VENUS_API_BASE` | Optional. VENUS Web API base URL. Default `http://localhost:42400/api/vector/v3`. |
| `HAMILTON_MCP_SPOKE_NAME` | Optional. This spoke's human-facing display name, reported via `GET /ping` and `get_spoke_state`'s `name` field -- a `hamilton-venus-mcp-hub`'s "Search for spokes" can find this spoke and suggest the name automatically instead of it being typed in by hand. Default: this PC's hostname. Only reachable over `streamable-http`/`sse` -- `/ping` doesn't exist over `stdio`. |

### Workflow

1. `import_script(name, content=...)` (or `source_path=` for a `.py` already on the spoke) stores the
   script and validates it. The report lists errors and warnings with a rule id, line and, usually, a
   suggestion. Fix errors and import again with `overwrite=True`. A script with errors is stored but
   cannot run.
2. `run_script(script, simulate=True)` re-validates, then starts it and returns a `run_id`. The run's
   `simulate` value is forced into every `StarClient`/`VantageClient` the script builds (and VENUS's
   system-wide simulation mode is set to match; the previous value is reported in the run and is *not*
   restored afterwards).
3. Follow it with `get_run_events(run_id, since_seq, wait_s=20)` (a long poll) and `get_run(run_id)`.
   `pause_run` / `resume_run` / `abort_run` control it.
4. `get_spoke_state()` answers `idle`, `running` or `error` at any moment.

### What gets checked (`validate_script`)

Static analysis only; the script is never executed. Rule ids: `V001` syntax; `V010` forbidden import;
`V011` forbidden call; `V012` GUI dialog or `input()` (scripts run headless); `V014` module not
installed; `V020` unresolved `hamilton_venus` import; `V021` unknown client command; `V022` bad
arguments (unknown keyword, missing required, too many); `V023` an argument that fails pydantic
validation; `V025` unknown catalog or enum name; `V026` empty `channels`; `V027` unparseable position
selector; warnings `W030` labware used but never added, `W032` no client created, `W033` hard-coded
`simulate=False`, `W034` value wrapped in literal quotes. Arguments whose value cannot be worked out
without running the script are counted as "unverified", not failed. The forbidden-import and
forbidden-call rules are a guardrail, not a sandbox.

### Errors need a person

When the SDK cannot recover from an instrument error by itself, or tips/liquid need reloading, the
script **stops and waits**. The prompt, with the options VENUS advertises (including per-channel
actions such as Repeat/Exclude/Next), shows up in `get_run_events`, `get_run` and `get_spoke_state`
(state `error`, `error_kind: prompt_pending`). An agent can see it but cannot answer it: answering needs
`HAMILTON_MCP_OPERATOR_TOKEN`. A person answers on the operator page (`get_spoke_state` →
`operator_ui.url`, or the hub dashboard). If a chosen fix does not clear the error and VENUS raises it
again, the person is asked again. Every decision (options, choice, who, when) is kept in the run record.
A failed run keeps the spoke in `error` (`run_failed`) until `acknowledge_run_error`.

### VENUS-level tools

`get_venus_run_state`, `get_venus_current_run_data`, `list_venus_run_history`, `get_venus_run_detail`,
`get_venus_run_trace`, `venus_pause`, `venus_resume`, `venus_abort` use VENUS's own Web API, so they see
and control any run, whoever started it.

## Tip counter dialogs are local to the instrument PC

`tip_pool_show_tip_counter(tip_pool)` and `tip_pool_show_tip_counters(tip_pools=None)` open a
tip-counter-editing dialog **drawn by VENUS on the instrument PC's own screen**. That dialog has
no network presence at all -- calling either through this server (directly, or via the hub)
cannot show it, read it, or click anything in it. What actually happens: the call blocks (tip
pool commands never time out) until a person physically at the instrument closes the dialog,
and only then does it return with whatever that person left in the counter. A long-blocked call
to one of these two is expected behavior, not a stuck spoke -- there is no way to tell, from
here, whether anyone is even at the instrument to close it.

For anything that needs to read or change a tip counter **programmatically** -- from an agent,
a script, or the hub -- use the dialog-free commands instead, none of which ever block on a
person:

| Command | Does |
|---|---|
| `tip_pool_get_tip_counter(tip_pool)` / `tip_pool_get_tip_counters()` | Read the current count(s). |
| `tip_pool_initialize_tip_counter(tip_pool)` | Initialize the counter (first use of a pool). |
| `tip_pool_reset_tip_counter(tip_pool)` | Reset the counter to empty/unknown. |
| `tip_pool_set_tip_counter(tip_pool, available_tips)` | Set the counter to an explicit state. |

These are also what `run_script`'s child process (and any script it runs) should use, since a
script run through the spoke has no console to show a dialog on either.

## Labware ids on the deck layout are lower-cased

VENUS stores every labware id added to the deck layout -- `labware_id`, `plate_id`, `lid_id`,
`tip_pool`, and any name VENUS assigns automatically when one is omitted -- **lower-cased**,
regardless of the case it was added with. `call_sdk_command("add_reservoir", {"labware_id":
"Trough1", ...})` is later reported back, by every query (`get_added_plates`, `get_added_
reservoirs`, `get_added_tip_racks`, ...) and by every tracking event a `run_script` run emits
(`labware`, `aspirate`, `tips`, ...), as `"trough1"`.

A `positions`-style selector string (e.g. `"Trough1@all"`) is matched against VENUS's own
(lower-cased) storage server-side, so **it does not need to be lower-cased by the caller**. But
anywhere else a labware id is compared -- a labware id typed by a script or a tool call against
one read back from a tracking event or query result, or used as a dict key -- normalize both
sides (e.g. `.lower()`) before comparing rather than assuming the original casing survives the
round trip. This bites `register_reagent(labware, ...)` specifically: it matches a run's own
live tracking key exactly, case-sensitive, not VENUS's lower-cased storage, so pass `labware` in
the same casing the script's own `positions=` selector uses.

## Troubleshooting

- **`run_script` refused: "HAMILTON_MCP_OPERATOR_TOKEN"**: set the variable in the spoke's environment
  and restart it. The startup log says so when it is missing.
- **`run_script` refused: an interactive session is active / VENUS is busy**: `close_session` first, or
  wait for (or deliberately abort) the running method.
- **A run seems stuck**: `get_spoke_state` shows whether it is waiting on a person; open
  `operator_ui.url`. To clear a stuck simulated run from outside, `abort_run` (or `venus_abort`).
- **Server won't start / import errors**: re-run
  `VENUS Python SDK Installer\VenusPythonSdkInstaller.exe` with both the "Set up VENUS
  SDK" and "Install MCP server" checkboxes ticked (`setup-venus-sdk` must have run at
  least once on this machine).
- **Client shows "failed to connect"**: run the standalone check above first --
  client error messages are usually too generic to debug from directly.
- **Claude Code**: `claude mcp get hamilton-venus` shows the last known status.
- **Claude Desktop**: check `logs\mcp-server-hamilton-venus.log` next to its `claude_desktop_config.json` (see above for where that is).

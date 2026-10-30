# Run Log

The SDK can produce a structured JSON run log that captures every HTTP request/response, SignalR event, and console interaction during a run. The log is a single file designed for post-run analytics, AI-driven LIMS integration, and custom viewer applications.

## Quick Start

`StarClient` and `VantageClient` write a run log by default, with VENUS's firmware COM trace embedded:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

with StarClient() as star:
    star.instrument_init()
    # Assumes a deck with tips picked up and a plate named "Plate".
    star.aspirate(
        channels=[1, 2],
        positions="Plate@col:1",
        volumes=50.0,
        liquid_class=LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY,
    )
```

After the `with` block exits, a finalized `.json` file appears in VENUS's LogFiles directory, next to
VENUS's own trace for the run. The SDK takes that directory from the registry
(`HKLM\SOFTWARE\WOW6432Node\Phoenix\Directories\Logfiles`, default value), else uses
`C:\Program Files (x86)\Hamilton\Logfiles`. If it cannot write there, the log goes to the current
working directory instead. Set `output_dir` to write somewhere else.

To turn the run log off, pass `run_log=False`, set `enabled = false` in the `[venus.run_log]` section
of the TOML config file (see [Configuration](../../configuration.md#toml-file)), or set
`HAMILTON_VENUS_RUN_LOG_ENABLED=0`.

## Full Configuration

Use `RunLogConfig` for fine-grained control:

```python
from hamilton_venus import StarClient
from hamilton_venus.config import RunLogConfig

config = RunLogConfig(
    enabled=True,
    output_dir=r"C:\logs",
    console_capture=True,       # capture print() and input()
    include_http=True,          # log raw HTTP request/response
    include_signalr=True,       # log SignalR events
    include_cmd_comms=True,     # log command communication channel messages
    redact_auth=True,           # strip credentials from payloads
    signalr_event_filter=[],    # empty = log all events
    max_payload_bytes=1_048_576,  # truncate payloads > 1 MB
    include_com_trace=True,     # embed VENUS's firmware .trc (default on; see below)
    com_trace_logfiles_dir="", # "" = ask VENUS (system/paths), then the default
    com_trace_max_bytes=5_242_880,  # cap embedded trace; keep newest lines
)

with StarClient(run_log=config) as star:
    star.instrument_init()
```

The same settings can be specified in TOML:

```toml
[venus.run_log]
enabled = true
output_dir = "C:\\logs"
console_capture = true
include_http = true
include_signalr = true
include_cmd_comms = true
redact_auth = true
signalr_event_filter = []
max_payload_bytes = 1048576
include_com_trace = true
com_trace_logfiles_dir = ""
com_trace_max_bytes = 5242880
```

Or via environment variables:

| Variable | Description |
|----------|-------------|
| `HAMILTON_VENUS_RUN_LOG_ENABLED` | Run log. On by default. Disable: `0`, `false`, `no`, or `off`. Enable: `1`, `true`, `yes`, or `on`. Also applies to a `RunLogConfig` built in code. |
| `HAMILTON_VENUS_RUN_LOG_DIR` | Override the output directory (default: VENUS's LogFiles directory). |
| `HAMILTON_VENUS_RUN_LOG_CONSOLE_CAPTURE` | Capture console output: on by default. Disable: `0`, `false`, `no`, or `off`. |
| `HAMILTON_VENUS_RUN_LOG_INCLUDE_HTTP` | Include HTTP requests/responses: on by default. Disable: `0`, `false`, `no`, or `off`. |
| `HAMILTON_VENUS_RUN_LOG_INCLUDE_SIGNALR` | Include SignalR events: on by default. Disable: `0`, `false`, `no`, or `off`. |
| `HAMILTON_VENUS_RUN_LOG_INCLUDE_CMD_COMMS` | Include command communication entries: on by default. Disable: `0`, `false`, `no`, or `off`. |
| `HAMILTON_VENUS_RUN_LOG_REDACT_AUTH` | Redact credentials: on by default. Disable: `0`, `false`, `no`, or `off`. |
| `HAMILTON_VENUS_RUN_LOG_SIGNALR_EVENT_FILTER` | Comma-separated list of SignalR event types to log (for example `runtime_status,progress`). |
| `HAMILTON_VENUS_RUN_LOG_MAX_PAYLOAD_BYTES` | Max serialized payload size per log entry in bytes. |
| `HAMILTON_VENUS_RUN_LOG_INCLUDE_COM_TRACE` | Embed the VENUS firmware `.trc` trace. On by default. Disable: `0`, `false`, `no`, or `off`. Enable: `1`, `true`, `yes`, or `on`. Also applies to a `RunLogConfig` built in code. |
| `HAMILTON_VENUS_RUN_LOG_COM_TRACE_DIR` | Override the VENUS `Logfiles` directory the `.trc` is read from. |
| `HAMILTON_VENUS_RUN_LOG_COM_TRACE_MAX_BYTES` | Cap on the embedded trace size in bytes (`0` = unlimited; newest lines kept). |

## Output Files

During a run, the SDK writes two streaming files:

```
run_<session_id>_<YYYYMMDD_HHMMSS>.jsonl        # streaming entries (during run)
run_<session_id>_<YYYYMMDD_HHMMSS>.meta.json    # session metadata (during run)
```

On clean exit, the `.jsonl` and `.meta.json` are removed and a single finalized `.json` is written. Its name mirrors the VENUS artifact convention (`<methodName>_<runGuid>_<descriptor>`) so the SDK log sits alongside the VENUS trace/database files for the same run:

```
<methodName>_<runGuid>_SdkRunLog.json           # when a VENUS run control GUID is linked
```

The `runGuid` is normalized to its hyphen-less form to match VENUS's filenames. If no VENUS run GUID is available, the SDK falls back to the invoking script name and session id:

```
<scriptName>_<session_id>_SdkRunLog.json        # fallback (no run GUID linked)
```

## Reading the Log

The finalized `.json` file is a single object:

```json
{
  "schema_version": "1.0",
  "session_id": "a1b2c3d4...",
  "run_guid": "ec05242f-790b-4196-ba32-60c9d921cf47",
  "method_name": "MyMethod",
  "sdk_version": "0.4.0",
  "script_name": "my_protocol.py",
  "started_at": "2026-05-05T19:40:10.000000+00:00",
  "started_at_local": "2026-05-05T15:40:10.000000-04:00",
  "ended_at": "2026-05-05T19:42:32.158000+00:00",
  "ended_at_local": "2026-05-05T15:42:32.158000-04:00",
  "log": [
    { "timestamp": "...", "timestamp_local": "...", "sequence": 1, "source": "SDK", "direction": "Out", "type": "session_start", "payload": {} },
    { "timestamp": "...", "timestamp_local": "...", "sequence": 2, "source": "WebAPI", "direction": "Out", "type": "http_request", "payload": {} }
  ]
}
```

The canonical (hyphenated) `run_guid` is preserved in the payload even though the filename uses the hyphen-less form. Both `run_guid` and `method_name` are `null` when no VENUS run control GUID was linked.

Every UTC timestamp (`started_at`, `ended_at`, and each entry's `timestamp`) is paired with an `_local` field (`started_at_local`, `ended_at_local`, `timestamp_local`) -- the same instant re-expressed as ISO 8601 in the host machine's local timezone. Run logs written before this field was added simply don't have it; code reading older logs should treat it as optional.

Load entries programmatically:

```python
import json

with open("MyMethod_ec05242f790b4196ba3260c9d921cf47_SdkRunLog.json") as f:
    data = json.load(f)

for entry in data["log"]:
    print(f"[{entry['sequence']}] {entry['source']}/{entry['type']}: {entry['timestamp']}")
```

## Crash Recovery

If the process crashes before the client exits and finalizes the log, both the `.jsonl` and `.meta.json` survive on disk. Each line of the `.jsonl` is a valid JSON object:

```python
import json

with open("run_a1b2c3d4_20260505_194010.jsonl") as f:
    entries = [json.loads(line) for line in f]
```

Use `recover_run_log()` to convert a crash file into the standard finalized format:

```python
from hamilton_venus import recover_run_log

final_path = recover_run_log("run_a1b2c3d4_20260505_194010.jsonl")
print(f"Recovered to: {final_path}")
```

## Command Communication Entries

The communication channel carries mid-command status messages (for example liquid level detection and tip presence) while a command is running. When `include_cmd_comms=True` (default), these messages are recorded as `command_communication` entries.

The method only posts them when `[venus.method].disable_status_communication` is `false` (it defaults to `true`, which makes each command faster). Set it to `false` when you want these entries in the run log; see [Configuration](../../configuration.md).

```json
{
  "timestamp": "2026-05-05T19:41:05.123000+00:00",
  "timestamp_local": "2026-05-05T15:41:05.123000-04:00",
  "sequence": 42,
  "source": "WebAPI",
  "direction": "In",
  "type": "command_communication",
  "payload": {
    "channel": "communication",
    "hasMessage": true,
    "messageId": "msg-abc",
    "timestamp": "2026-05-05T19:41:05.100Z",
    "data": {
      "id": "liq-detection-1",
      "category": "Channels",
      "command": "aspirate",
      "status": "running"
    },
    "active_operation_context": "Channels/aspirate"
  }
}
```

The `active_operation_context` field is set to the current command's `"category/action_name"` string when the message is received while a command is active, and `null` when received outside of an active command.

Disable communication channel logging when you do not need granular mid-command telemetry:

```python
with StarClient(run_log=RunLogConfig(enabled=True, include_cmd_comms=False)) as star:
    star.instrument_init()
```

## Disabling Specific Capture

Disable console capture (keep HTTP and SignalR only):

```python
from hamilton_venus import StarClient
from hamilton_venus.config import RunLogConfig

with StarClient(run_log=RunLogConfig(enabled=True, console_capture=False)) as star:
    star.instrument_init()
```

Disable HTTP logging (keep SignalR and console only):

```python
with StarClient(run_log=RunLogConfig(enabled=True, include_http=False)) as star:
    star.instrument_init()
```

Filter to specific SignalR events:

```python
with StarClient(run_log=RunLogConfig(enabled=True, signalr_event_filter=["runtime_status", "progress"])) as star:
    star.instrument_init()
```

## Combining with VENUS Trace Files

Each run log entry has a `timestamp` (ISO 8601, UTC), `timestamp_local` (the same instant in the host's local timezone -- see above), and a `sequence` number. Use these fields to correlate with VENUS `.trc` files and firmware logs, which are typically local-time:

- **`timestamp`** provides UTC wall-clock alignment with other log sources; **`timestamp_local`** aligns directly with locally-timestamped sources like VENUS trace files without a manual conversion.
- **`sequence`** resolves ordering when multiple events arrive within the same millisecond.

Together with the `session_id`, these fields uniquely identify every interaction in a run across all log sources.

### Embedding the firmware COM trace

VENUS writes a per-day firmware communication trace (`< sent` / `> received` lines) to its
`Logfiles` directory:

| Instrument | Trace file |
|---|---|
| STAR (live) | `HxUsbComm<YYYYMMDD>.trc` |
| Vantage (live) | `HxTcpIpBdzComm<YYYYMMDD>.trc` |
| any instrument, simulation | `ComTrace_Simulator<YYYYMMDD>.trc` |

With `include_com_trace=True` (default **on**), the SDK snapshots that file's size at
`__enter__` and, at `__exit__` — once the instrument has disconnected and VENUS has
flushed — embeds the bytes appended in between as chunked `com_trace` log entries, plus a
`com_trace_snapshot` entry near the session start:

```python
from hamilton_venus import StarClient
from hamilton_venus.config import RunLogConfig

with StarClient(run_log=RunLogConfig(enabled=True, include_com_trace=True)) as star:
    star.instrument_init()
    # ... run commands ...
# the finalized *_SdkRunLog.json now contains the firmware trace for this run's window
```

A runnable end-to-end example (enable it, do a transfer, then read the embedded
entries back out) is in [`example_scripts/run_log_com_trace.py`](../../../example_scripts/run_log_com_trace.py).

Each `com_trace` entry's payload carries `path`, `chunk_index`/`chunk_count`,
`start_offset`/`end_offset`, `line_count`, `truncated`, and `lines` (a list of raw trace
lines). `com_trace_logfiles_dir` overrides the directory; left empty, the SDK asks VENUS
where it writes its logs (`GET /api/vector/v3/system/paths` → `paths["LogFiles"]`) and
falls back to `C:\Program Files (x86)\Hamilton\Logfiles` only if that lookup fails.
`com_trace_max_bytes` caps the total embedded (0 = unlimited) and keeps the **newest**
lines when the trace is larger, flagging `truncated` on the first chunk.

Notes:

- The `.trc` is shared by every VENUS activity that day; snapshotting the offset at
  `__enter__` scopes the capture to this client session's window, not other concurrent work.
- A session that crosses local midnight rolls to the next day's file automatically.
- Capture is best-effort — a missing directory or unreadable file disables it silently and
  never affects the run or the rest of the log.

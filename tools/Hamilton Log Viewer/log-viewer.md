# Log Viewer

The Hamilton Log Viewer reads the run logs the SDK writes and lays them out for working out what happened in a run: what went wrong and why, the full trace, a run summary, and where every sample went.

Set it up with the **Install Hamilton Log Viewer app** option of `VenusPythonSdkInstaller.exe`, in the repository root. Then open `HamiltonLogViewer.exe` in this folder.

## Opening a run

Every SDK run writes `<method>_<runGuid>_SdkRunLog.json` to VENUS's LogFiles folder (`C:\Program Files (x86)\HAMILTON\LogFiles` by default; see [Run Log](../../docs/examples/advanced/run_log.md)), next to VENUS's own trace `<method>_<runGuid>_Trace.trc` and, for a Script Manager run, `<method>_<runGuid>_ScriptLines.json`.

- **Open Log…** opens a run log from disk. Its VENUS trace and script-line file are loaded with it when they sit next to it. The file list shows the newest logs first. Logs you open are kept under **Recent files**.
- **Drag and drop** a run log onto the window. A log that is also in LogFiles (or a folder you opened logs from) is opened from there, so its VENUS trace and script lines come along; otherwise drop its `_Trace.trc` and `_ScriptLines.json` together with it.
- **VENUS runs** lists the Python runs in VENUS's run history, newest first, through the VENUS API. Runs without an SDK log (VENUS methods not run from Python) are left out, as the viewer can only show their trace; open those in VENUS's own trace viewer. The host field is the VENUS PC to read from: `localhost` (default), a PC name, or `name:port` (the API's port is 42400). Pick a run and the viewer fetches its SDK log, script lines and VENUS trace from that PC. A VENUS method that was not run from Python has no SDK log; it opens with just its VENUS trace.
  Runs are grouped by day. A run whose SDK log says it ended in an error is marked red, and each day shows how many did; runs without an SDK log are dimmed. Runs on the instrument (not simulated) are tagged **LIVE**. Filter the list by method name, and narrow it with **Errors only** and **Live only** (both can be on). VENUS itself records every run as *Finished*, so the error marking comes from the SDK log, and so does live versus simulation (only its first few KB are read); for a run without an SDK log, VENUS's own run details say whether its instrument was simulated.
- `HamiltonLogViewer.exe <path>\<log>_SdkRunLog.json` opens a log straight away (e.g. with *Open with*).

The header shows the script, result, simulation or instrument, method, start time, duration, run GUID and where the log came from, plus anything that could not be loaded.

## Errors

The tab a failed run opens on. At the top is the outcome: whether the run finished cleanly, the exception that ended it, and the command it stopped in (with its script line when the run came from the Script Manager).

Below it is one card per incident:

| Section | What it shows |
|---|---|
| **What happened** | VENUS's message for each group of channels, and the error code decoded: `P1:08/78` is the 1000 µL channels' *Tip handling: No tip or wrong tip type detected.* |
| **Command** | The SDK command that was running: action, result, script line, channels, positions (labware@wells), volumes, liquid class, tip pool. |
| **Recovery** | Every attempt with the recovery chosen (a *Repeat* that failed again is another attempt on the same card), and the recoveries VENUS offered. |
| **Likely cause** | The usual causes of that kind of error, and what to check. |
| **Context** | The commands just before the error, and the VENUS trace and firmware (COM trace) lines from 10 s before to 2 s after it, with the failing firmware reply highlighted. |

**Show in trace** jumps to the error's moment in the Trace tab.

## Trace

The whole run in time order: the script's console output, VENUS's trace (from the `.trc` when it is available), SDK commands and their results, VENUS status messages, the firmware COM trace, and errors. The filter chips, search and word wrap work as in the Script Manager's Terminal tab; COM Trace and Debug (raw HTTP and housekeeping events) start hidden.

## Commands

Every command the script sent to the SDK, in order: time, action, target (labware@wells, tip pool, ...), result, duration and script line. Commands that failed, raised instrument errors or never got a response are marked. Filter by text, or show only those with problems.

Expand a command to see its request parameters, VENUS's status messages for it, the instrument errors raised while it ran (per channel), the VENUS trace and firmware (COM trace) lines from its start to its response, and the full response (return parameters, TADM data, ...). **Show in trace** jumps to it in the Trace tab.

## Summary

The Script Manager's Summary tab for any run: result, run time, mode, errors, tips used by type, labware used, reservoir volumes and TADM curves.

## Sample Tracking

The Script Manager's Sample Tracking tab: a card per labware that received liquid, with every well's transfers, sources and volumes, the labware report (CSV and JSON export) and the TADM curves of each transfer.

A run recorded by the Script Manager shows exactly what it recorded live. For any other run (a plain Python script, the MCP server, a demo app) the tracking is rebuilt from the logged aspirate and dispense commands with the same rules: a dispense's source is whatever that channel last aspirated, a reservoir is one pool, dispenses into a reservoir are refills (except the liquid waste), and split-well slots show as their parent well. The note above the cards says which it is.

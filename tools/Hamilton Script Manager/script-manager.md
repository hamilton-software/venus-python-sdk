# Script Manager

The Hamilton Script Manager keeps shortcuts to your Python scripts in folders and runs them from one window. You switch between simulation and the instrument with one toggle, and while a script runs you can follow it line by line, pause it, answer its prompts and instrument errors, and watch tips, reagents and samples. The scripts need no changes to run here.

Set it up with the **Install Hamilton Script Manager app** option of `VenusPythonSdkInstaller.exe`, in the repository root. Then open `HamiltonScriptManager.exe` in this folder.

## Shortcuts

The left panel is a tree of folders and shortcuts.

- **New shortcut** points at a Python script on disk; **New folder** groups shortcuts. Shortcuts and folders can be renamed, moved and deleted.
- A shortcut stores a **read-only copy** of the script. What runs is that copy, not the file it came from, so editing the original doesn't change a shortcut until you re-sync it. Deleting a shortcut doesn't touch the original.
- **Re-sync from Source** copies the original file over the shortcut's copy.

If the original has changed since the last sync, the app warns you when you select the shortcut or press Run. **Re-sync Now** updates the copy, and **Continue** keeps the copy you have. Both behaviors can be changed in [Settings](#settings).

## Running a script

| Control | What it does |
|---|---|
| **Simulate** | On: the run uses the simulator. Off: it runs on the instrument. Applies to the next run, and is remembered. |
| **Run** | Runs the selected shortcut. |
| **Pause / Resume** | Pauses the run through VENUS, once the instrument command in progress has finished, and carries on from there on Resume. VENUS decides what the front cover does during a pause. |
| **Stop** | Ends the run. |
| **View Deck Layout** | Opens the live 3D deck view. |

The toggle overrides whatever the script says: a script with `StarClient(simulate=False)` still runs in simulation when **Simulate** is on. The app also sets VENUS's own system-wide simulation mode to match, because that setting decides whether a real or simulated instrument answers. The status bar shows the run state and the instrument's serial number, or *(simulated)*.

Both `StarClient` and `VantageClient` scripts work. If VENUS is already running a method when you press Run, the **Instrument Is Busy** prompt offers **Cancel**, which leaves it running, or **Abort Existing Run**.

## Tabs

### Script

The read-only script. During a run the current line is highlighted. If the run ends in an error, the line that actually failed is marked, not the script's own cleanup code that ran afterwards.

### Terminal

The script's output, SDK messages and errors as they happen, with filter chips, search, word wrap and auto-scroll. **Export Log** saves the finished run's log.

### Consumables

Live tip counts per tip pool, and tracked reagent reservoirs with their percent full and remaining volume.

- Each tip pool has its own low-count warning threshold. Pools you haven't set use the default from Settings.
- A reservoir appears when the run uses it. One you add by hand is shown on every run.
- Reservoir volumes come from the liquid levels measured at aspiration.

If a pickup needs more tips than remain, the **Tips Running Low** prompt pauses the run. Load tips and choose **Show Tip Counter** to confirm with the instrument, or **Abort**. The run continues once there are enough tips. Compound commands make the same check before they start.

### Sample Tracking

A card for each labware that received liquid, with every well's transfers, sources and volumes. The labware report exports to CSV (one row per target well) or JSON (every transfer per well, with error and TADM data), and each transfer's TADM curves can be opened.

### Summary

Available once a run has finished: result, run time, mode, errors, tips used by type, labware used, reservoir volumes and TADM curves.

The [Log Viewer](../Hamilton%20Log%20Viewer/log-viewer.md) shows the same Summary and Sample Tracking for any finished run, along with the full trace and an error breakdown.

## Prompts during a run

The app answers these so a script doesn't need a console:

| The script or instrument does | What appears |
|---|---|
| Calls `input()` | **Script Input Needed**, with a text field. |
| Calls a `tkinter.messagebox` or `tkinter.simpledialog` function | The same dialog, drawn in the app, with its usual buttons. `showinfo`, `showwarning`, `showerror` and `askyesno` have no Cancel, so one of the buttons must be chosen. |
| Hits an error the SDK can't recover from automatically | **Operator Action Required**. The instrument stays stopped until you answer. Channels with the same error share one list of recoveries, and channels with a different error get their own. |

## Settings

| Setting | Default | What it does |
|---|---|---|
| **Warn if a shortcut's saved copy is out of sync** | On | Shows the out-of-sync warning. |
| **Automatically re-sync a shortcut** | Off | Re-syncs instead of warning. Takes priority over the warning. |
| **Default tip pool warning threshold** | 10 tips | For pools without their own threshold. |
| **Reservoir warning threshold** | 10% | Warns below this percent full. 0% turns the warning off. |
| **Show SDK debug logging and the VENUS runtime trace in the Terminal** | Off | For troubleshooting. Slows runs. The run log is saved either way. |

## Files

| What | Where |
|---|---|
| Shortcuts, consumables configuration and settings | `backend\data\shortcuts.json`, `consumables.json`, `settings.json` in the app folder |
| The shortcuts' script copies | `backend\data\scripts\<shortcut id>\` |
| Run logs | `C:\Program Files (x86)\HAMILTON\LogFiles`, as `<method>_<runGuid>_SdkRunLog.json` with `<method>_<runGuid>_ScriptLines.json` next to it |

Consumables configuration is thresholds and which reservoirs to track. Measured tip counts and volumes exist only during a run. The `backend\data` folder belongs to this PC, so back it up if you want to keep your shortcuts.

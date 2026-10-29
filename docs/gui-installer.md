# GUI Installer Guide: VENUS Python SDK Installer

This guide explains how to use `VenusPythonSdkInstaller.exe` -- the desktop installer for the VENUS Python SDK -- including exactly what gets installed by default and what each checkbox adds.

## What it is

`VenusPythonSdkInstaller.exe` is a standalone desktop app (no separate installer-of-the-installer, no MSI wizard). It sets up a Python virtual environment, installs the VENUS Python SDK into it, deploys the VENUS-side method structure, and can optionally assemble a small set of add-on desktop apps.

## Prerequisites

- Windows, with Python 3.11 or newer already installed and available on `PATH` (the installer looks for `py` or `python`; it does not bundle its own Python). If neither is found, or the one that's found is older than 3.11, the install stops immediately at the "Locating Python" step with a message pointing to python.org.
- Administrator rights. The exe requests elevation (a UAC prompt) automatically when you launch it -- setup writes to protected locations (`C:\Program Files (x86)\HAMILTON\SDK` by default) and updates a machine-level registry key.
- VENUS 6.5 or newer installed. The one-time `setup-venus-sdk` step reads the installed VENUS version from the registry (`HKLM\SOFTWARE\WOW6432Node\Phoenix\Release`) and stops the install with a clear error in the log if VENUS is missing or older than 6.5 -- the SDK does not work against older VENUS releases.

## Running the installer

Double-click `VenusPythonSdkInstaller.exe`. Approve the UAC elevation prompt. The window that opens has:

1. An **SDK install location** field, pre-filled with the folder the exe itself is sitting in (fully editable, with a **Browse...** button). This is where the Python SDK checkout, its virtual environment, and any add-on apps you select will live. It can be any folder -- it's created automatically if it doesn't exist.
2. Up to five checkboxes (below). A VENUS install is STAR **or** Vantage, never both, so the installer reads the installed instrument type from the registry and hides the demo-app checkbox for the instrument that isn't installed, pre-checking the one that is. If it can't tell (no VENUS detected), both demo checkboxes are shown, unchecked.
3. An **Install** button. Clicking it reveals a step-progress list and a live log pane, plus a **Save log...** button to copy the full log to a file if you need to share it for troubleshooting.

## What always happens, regardless of checkboxes

These steps are **not** gated by any checkbox -- they run on every install:

1. Locate Python on `PATH`.
2. Create the install location folder if needed.
3. Create (or reuse, if one already exists) a virtual environment at `<install location>\.venv`.
4. Upgrade `pip` inside that virtual environment.
5. Install `hamilton-venus-sdk` (editable) into the virtual environment.
6. Install `hamilton-workflow-framework` (editable) into the virtual environment.
7. Install shared app dependencies (`fastapi`, `uvicorn`, `websockets`) into the virtual environment -- these back the add-on apps below whether or not you install any of them.
8. Verify the install by importing `hamilton_venus` in the new virtual environment.

If any step fails, the whole run stops at that point and the log explains why -- nothing partial is left running silently.

## The checkboxes

| Checkbox | Default | What it does |
|----------|---------|---------------|
| **Set up / update VENUS SDK** | **Checked** | Copies the SDK files to the install location and runs the elevated machine-level setup helper. See [Set up / update VENUS SDK](#set-up--update-venus-sdk) below. |
| **Install Hamilton STAR Demo app** | Unchecked (hidden on a Vantage VENUS install; pre-checked on a STAR one) | Assembles the "Hamilton STAR Demo" desktop app folder next to `.venv`. |
| **Install Hamilton Vantage Demo app** | Unchecked (hidden on a STAR VENUS install; pre-checked on a Vantage one) | Assembles the "Hamilton Vantage Demo" desktop app folder next to `.venv`. |
| **Install Hamilton Script Manager app** | Unchecked | Assembles the "Hamilton Script Manager" desktop app folder next to `.venv`. |
| **Install Hamilton Log Viewer app** | Unchecked | Assembles the "Hamilton Log Viewer" desktop app folder next to `.venv`: open SDK run logs or recent VENUS runs to see their errors, trace, summary and sample tracking. |
| **Install MCP server for AI agents** | Unchecked | Lets tools like Claude Code drive the SDK directly. |
| **Install MCP Hub (fleet coordinator)** | Unchecked | Fans commands out to networked MCP servers on other instrument PCs and compiles their results. Does not require VENUS or the SDK on this PC -- just Python. |

Wording above is verbatim from the installer UI. Details on each:

### Set up / update VENUS SDK

Checked by default -- leave this on for a normal, first-time install. Three things happen when it's checked:

- **File copy.** The SDK payload bundled with the installer (`docs`, `src`, `prerequisites`, `sdk_method_structure`, `example_scripts`, plus `pyproject.toml`, `README.md`, `SECURITY.md`, `LICENSE`) is copied into your chosen install location, flattened -- no extra subfolder. This is a copy, not a move: the installer's own bundled copy stays intact, so you can re-run it against a different location later. Existing files at the destination that overlap are overwritten; anything else already there is left alone.
- **Labware Converter app.** The bundled `LabwareConverter\` folder (a prebuilt desktop tool -- no build) is copied verbatim to `<install location>\LabwareConverter\`. Its self-regenerating WebView2 runtime profile is not shipped or copied.
- **Machine-level setup.** The `setup-venus-sdk --force` helper runs from inside the new virtual environment. This deploys the VENUS-side method structure (labware definitions, method library, layout files, command catalogs) to the fixed location VENUS itself reads from -- see [Where things get installed](#where-things-get-installed) below -- and points a registry key at your chosen SDK location. It also pulls this machine's labware and liquid classes into the static `hamilton_venus.catalog` (no instrument connection required); the instrument type for that pull is auto-detected from the registry (`InstCfgFile`), so a Vantage install pulls as Vantage and a STAR install as STAR without any flag.

**If you uncheck this box**, all of the above are skipped, and the install only succeeds if the target location you picked already has a real SDK checkout in it (specifically, a `pyproject.toml` file) -- otherwise it stops with an error telling you to either check this box or point at a location that already has one. Unchecking it is only useful when you're re-running the installer purely to add an optional app or the MCP server to an SDK you already set up.

### Install Hamilton STAR Demo app / Install Hamilton Vantage Demo app

A drag-and-drop demo desktop app for exercising the SDK against a STAR (or Vantage, for the Vantage checkbox) instrument. Checking either creates a `Hamilton STAR Demo\` or `Hamilton Vantage Demo\` folder next to `.venv` in your install location, with the app's exe and its backend files, pre-configured to use the virtual environment that was just created.

If the installer bundle you're running doesn't include a particular demo app (for example, a STAR-only distribution), checking its box logs a skip message rather than failing the whole install.

### Install Hamilton Script Manager app

A desktop app for managing and running shortcuts to existing Hamilton STAR Python scripts -- create/organize scripts in folders, toggle Simulate/Live, pause with door unlock, watch the current line execute, view a read-only script pane, a terminal/trace pane, and a 3D deck view. Checking this creates a `Hamilton Script Manager\` folder next to `.venv`, pre-configured the same way as the demo apps above.

### Install Hamilton Log Viewer app

A desktop app for reading the run logs the SDK writes (`<method>_<runGuid>_SdkRunLog.json` in VENUS's LogFiles folder). Open a log from disk, or pick a recent run from VENUS (on this PC or another) and the viewer fetches its SDK log and VENUS trace. It shows the run's errors broken down for root cause, the full trace with the Script Manager's filters, search and word wrap, the run summary, and the sample tracking. Checking this creates a `Hamilton Log Viewer\` folder next to `.venv`, pre-configured the same way as the apps above.

### Install MCP server for AI agents

Installs `hamilton-venus-mcp`, a Model Context Protocol (MCP) server that exposes the SDK's `StarClient` as tools an AI agent (Claude Code, Claude Desktop, or any other MCP client) can call directly, instead of you writing Python by hand. Checking this box:

- Copies the bundled `mcp_server` folder into your install location and installs it (editable) into the virtual environment.
- Verifies the install by importing the MCP server module.
- Writes `Start MCP Spoke.bat` at your install location -- double-click it to run this spoke as a persistent, network-reachable process (`streamable-http`, bound to `0.0.0.0`) in its own terminal window, the thing you'd leave running on an instrument PC so a Hub elsewhere can reach it. Add it to a Hub's spokes from that Hub's dashboard once it's running; closing the window stops the spoke. It also carries two commented-out placeholder lines you can turn on by editing the file: `HAMILTON_MCP_OPERATOR_TOKEN` (needed for a human to resolve an instrument error from a Hub's dashboard -- must match the Hub's own batch file exactly) and `HAMILTON_MCP_ALLOW_HARDWARE` (required before `run_script` will run anything against real hardware instead of just simulating). **Do not put spaces around `=`** when editing either -- `set NAME = value` sets a variable literally named `NAME ` (trailing space) in `cmd.exe`, not `NAME`, and the setting is silently ignored.
- Prints the exact command to register it with Claude Code at the end of the run:

  ```
  claude mcp add --transport stdio hamilton-venus -- "<install location>\.venv\Scripts\hamilton-venus-mcp.exe"
  ```

See `mcp_server/README.md` in the SDK folder for more on using the MCP server once it's registered.

### Install MCP Hub (fleet coordinator)

Installs `hamilton-venus-mcp-hub`, a separate MCP server that fans tool calls out to several networked `hamilton-venus-mcp` servers (the one above, running on other instrument PCs) and compiles their results -- so an agent can drive a fleet of STAR/Vantage instruments through one connection instead of one per PC.

Unlike every other checkbox on this page, **this one has no VENUS SDK dependency at all** -- it can be checked by itself, with "Set up / update VENUS SDK" unchecked, on a PC with no VENUS install whatsoever (a dedicated coordinator machine, for instance). When it's the only thing selected, the installer skips the VENUS SDK/workflow-framework/shared-app-dependency steps and the `hamilton_venus`-import verification entirely -- it only needs Python and a virtual environment, same as the SDK-dependent path needs for everything else.

Checking this box:

- Copies the bundled `hamilton_venus_mcp_hub` folder into your install location and installs it (editable) into the virtual environment.
- Verifies the install by importing the hub's server module.
- Writes `Start MCP Hub.bat` at your install location -- double-click it to run the hub in its own terminal window, bound to `0.0.0.0` so other PCs can reach it. It starts with **no spokes pre-configured on purpose**: add each instrument from the hub's own dashboard (`http://<hub-host>:8000/dashboard`, printed by the batch file and below) once it's running, rather than needing to know every spoke PC's address up front. Closing the window stops the hub. It also carries a commented-out `HAMILTON_MCP_OPERATOR_TOKEN` placeholder line -- uncomment it and set it to the same value as each spoke's own batch file to resolve instrument errors from this dashboard (without it, the dashboard shows prompts but its resolve buttons stay disabled). Same warning as the spoke's file: no spaces around `=`, or `cmd.exe` silently sets the wrong variable.
- Prints setup reminders and the registration command at the end of the run (the hub runs over `streamable-http`, not `stdio`, so registration differs from the MCP server above):

  ```
  claude mcp add --transport http hamilton-venus-hub http://<hub-host>:8000/mcp
  ```

See `hamilton_venus_mcp_hub/README.md` in the install location for configuring spokes, the live dashboard, and adding/removing spokes at runtime.

## Default install (nothing changed from what opens)

With the window left exactly as it opens and **Install** clicked:

- Only "Set up / update VENUS SDK" is checked.
- The install location is wherever the exe suggested (its own parent folder) unless you changed it.
- Result: a virtual environment and SDK checkout at your install location, the VENUS-side method structure deployed to `C:\Program Files (x86)\HAMILTON\SDK`, and nothing else. No demo apps, no Script Manager, no MCP server, and no code editor of any kind are installed by default -- there is no such option anywhere in the installer.

## Where things get installed

Two separate destinations are involved, and it's worth knowing the difference:

| What | Where | Controlled by |
|------|-------|----------------|
| Python SDK checkout, `.venv`, Labware Converter app, any add-on apps (demo apps, Script Manager, MCP server, MCP Hub) | The **SDK install location** field -- any folder you choose | You, via the location field |
| VENUS method structure (labware, method library, layout, command catalogs) | A fixed location VENUS itself reads from: `C:\Program Files (x86)\HAMILTON\SDK` by default, or wherever a prior install pointed the registry | "Set up / update VENUS SDK" checkbox |

The installer does not modify your user `PATH` or environment variables. It does write one registry value (`HKLM\SOFTWARE\WOW6432Node\Phoenix\Directories\SDK`, VENUS's own registry namespace) pointing at your chosen SDK location, and it adjusts folder permissions on the install location so the `Users` group can read/write it.

## Checking prerequisite versions

The installer bundles a handful of Hamilton HSL library prerequisites and warns automatically (in the log) if anything installed on the machine is out of date. The GUI does not expose a full version report -- for that, open a terminal in `<install location>\.venv\Scripts\` and run:

```powershell
.\setup-venus-sdk.exe check-versions
```

Add `--json` for machine-readable output, or `--check-manifest` to also flag prerequisites the manifest declares but this bundle doesn't ship an installer for.

## Uninstalling

There is no uninstall button in the GUI installer. Uninstalling is command-line only, via `uninstall-venus-sdk` from an elevated terminal:

```powershell
cd "<install location>\.venv\Scripts"
.\uninstall-venus-sdk.exe
```

This removes the VENUS-side method structure at the fixed target location (`C:\Program Files (x86)\HAMILTON\SDK` by default), removes the registry key, and uninstalls the bundled prerequisites -- see the root `README.md`'s uninstall section for the full flag reference (`--structure-only`, `--keep-registry`, `--keep-prereqs`, `--dry-run`, and so on).

`uninstall-venus-sdk` does **not** touch your SDK install location, `.venv`, or any add-on apps the GUI installer created there (Hamilton STAR Demo, Hamilton Vantage Demo, Hamilton Script Manager). To remove those, delete the install location folder manually after uninstalling.

## Troubleshooting

- **Install stops at "find-python" / Python not found**
  Install Python 3.11 or newer from python.org and make sure it's on `PATH`, then re-run the installer.
- **Install stops at "find-python", saying the found Python is older than 3.11**
  The installer found a `py`/`python` on `PATH`, but it's older than 3.11 -- the SDK uses `enum.StrEnum`, added in Python 3.11. Install Python 3.11 or newer, make sure it comes first on `PATH` (or, if you use the `py` launcher and already have 3.11+ installed alongside an older version, set `PY_PYTHON` to pick it), then re-run the installer.
- **Install stops before the file copy, saying no SDK is present at the target**
  You unchecked "Set up / update VENUS SDK" but pointed the install location at a folder that doesn't already have an SDK checkout in it. Either check that box, or pick a location where you've already installed the SDK once.
- **Install stops at "setup-venus-sdk", saying VENUS is missing or older than 6.5**
  Install or upgrade VENUS to 6.5 or newer, then re-run the installer -- the SDK does not work against older VENUS releases. The log line names the exact detected version (or that none was found).
- **Install stops at "setup-venus-sdk", saying Python is older than the minimum**
  This means `setup-venus-sdk` ran under an interpreter older than 3.11 (for example, invoked directly outside the installer's own virtual environment). Re-run it from a Python 3.11+ virtual environment.
- **`ImportError: cannot import name 'StrEnum' from 'enum'`**
  The SDK was installed into a virtual environment created with Python 3.10 or older (this bypasses the installer's own "find-python" version check -- for example, a `.venv` created manually before re-running the installer, which reuses an existing venv rather than recreating it). Delete the `.venv` folder under the SDK install location and re-run the installer so it creates a fresh one with a qualifying Python.
- **"Install Hamilton STAR Demo app" (or Vantage/Script Manager) logs a skip instead of installing**
  The installer bundle you're running doesn't include a prebuilt exe for that app. This isn't an error -- it just means that particular add-on isn't part of this distribution.
- **Need to share logs for support**
  Use the **Save log...** button after a run to write the full log to a file.
- **Re-running after a failed or partial install**
  Re-running the installer is safe -- the virtual environment is reused if it already exists, and `--force` ensures the VENUS-side method structure is refreshed rather than silently skipped.

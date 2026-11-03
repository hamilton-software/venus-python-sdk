# AI Assistants (Claude Code and Claude Desktop)

The VENUS Python SDK's MCP server lets an AI assistant control a Hamilton STAR or Vantage. The MCP server only provides tools, though. The assistant itself runs in a **harness**: the app that sends your request to the AI model, runs the tools the model asks for, and shows you the results. Claude Code and Claude Desktop are both harnesses.

The installer's **Set up AI assistants** option configures both for you, so you don't have to register the MCP server by hand.

For a ready-made app instead, with its own approval cards, deck view and conversation records and no Claude app needed, see the [AI Assistant app](../Hamilton%20AI%20Assistant/ai-assistant-app.md).

## What gets set up

| | Claude Code | Claude Desktop |
|---|---|---|
| Hamilton MCP server (`hamilton-venus`) | ✔ (plugin) | ✔ (added to its config) |
| Hamilton skills: labware compatibility, liquid handling rules, liquid class optimization, tip counter setup, script authoring | ✔ (plugin) | Upload the zips yourself (see below) |
| Approval prompt before anything moves a real instrument or device | ✔ (plugin hook) | Claude Desktop's own tool permission prompts |
| Log of every executed hardware call | ✔ | – |

Claude Code covers the terminal, the VS Code and JetBrains extensions, and the Code tab in Claude Desktop. The plugin is installed for the current Windows user, so it is available in all of them.

Other agents, such as Abacus AI, get the same skills and MCP server in a generic form: see [Other agents](#other-agents-abacus-ai-and-others).

## Requirements

- The VENUS Python SDK with the **MCP server** option (this install or an earlier one).
- Claude Code and/or Claude Desktop installed for the Windows user who runs the installer, signed in with a Claude account.

## Setup

1. Run `VenusPythonSdkInstaller.exe` and tick **Install MCP server for AI agents** and **Set up AI assistants**.
2. Restart Claude Desktop if it was open. Restart any open Claude Code sessions, or run `/reload-plugins` in them.
3. Ask for something in simulation, for example: *"Start a simulated STAR session with the last deck and show me the tip counters."*

The setup is a script you can re-run at any time, for example after installing Claude Code or Claude Desktop later:

```powershell
& "C:\Program Files (x86)\Hamilton\Python\.venv\Scripts\python.exe" "C:\Program Files (x86)\Hamilton\Python\tools\ai_harness\setup_ai_harness.py" --venv "C:\Program Files (x86)\Hamilton\Python\.venv"
```

Adjust the paths if the SDK is installed elsewhere. `--skip-claude-code` and `--skip-claude-desktop` set up only one of the two.

### What the setup changes

- **Claude Code:**
  - Stages the plugin in `%LOCALAPPDATA%\Hamilton\ai_harness\marketplace`, registers that folder as the local marketplace `hamilton`, and installs `hamilton-venus@hamilton` at user scope.
  - Check it with `claude plugin list`.
  - If you registered the server by hand before (`claude mcp add ... hamilton-venus`), remove that entry with `claude mcp remove hamilton-venus` so the tools aren't listed twice.
- **Claude Desktop:**
  - Adds a `hamilton-venus` entry under `mcpServers` in `claude_desktop_config.json` and leaves everything else in the file unchanged. The original file is backed up next to it as `claude_desktop_config.json.<date>.bak`.
  - An existing `hamilton-venus` entry is left as it is.
  - The file's location depends on how Claude Desktop was installed:

| Claude Desktop install | Config file |
|---|---|
| Microsoft Store / MSIX | `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude\claude_desktop_config.json` |
| Classic installer | `%APPDATA%\Claude\claude_desktop_config.json` |

### Hamilton skills in Claude Desktop

Claude Desktop doesn't load plugin skills from disk. Upload each zip in `%LOCALAPPDATA%\Hamilton\ai_harness\claude_desktop\skills\`, which the setup creates, under **Settings > Capabilities > Skills**.

## Other agents (Abacus AI and others)

The Hamilton skills are plain [Agent Skills](https://agentskills.io): a folder per skill with a `SKILL.md` (its name is the folder name, plus a description) and the files it refers to, with nothing that only Claude understands. Many agents read that format, so the setup also installs them generically:

- **Skills:** copied to `%USERPROFILE%\.agents\skills\hamilton-*`, the user-level folder Abacus AI and other agents read. Abacus AI also reads `<project>\.agents\skills` and `%USERPROFILE%\.abacusai\skills`. Only `hamilton-*` folders are touched; an earlier copy is replaced. Start a new session to load them (in Abacus: `/skills list` shows them).
- **MCP server:** if Abacus AI is installed (`%USERPROFILE%\.abacusai` exists), `hamilton-venus` is added to `%USERPROFILE%\.abacusai\mcp.json`, the file its desktop app, VS Code extension and CLI share. The file is backed up first, and an existing `hamilton-venus` entry is left as it is.

For any other tool, export a bundle and import it by hand:

```
<venv>\Scripts\python.exe <SDK>\ai_harness\setup_ai_harness.py --venv <venv> --export C:\temp\hamilton-ai
```

This writes `skills\` (the Agent Skills folders), `mcp.json` (the server in the usual `mcpServers` layout) and a short `README.md`, and changes nothing else on the PC. Tools that don't support skills still get the essentials from the MCP server's own instructions and its `get_usage_guide` tool.

To skip these steps, run the setup script by hand with `--skip-agent-skills` and/or `--skip-abacus`; `--agent-skills-dir <folder>` copies the skills somewhere else.

## Choosing simulation or live, and the deck layout

Every session starts with two questions: simulation or the live instrument, then a blank deck, the last layout used (with a summary of its carriers, labware and tip pools) or a saved layout.

- **Apps that show MCP forms** ask them as forms from the Hamilton server.
- **Apps that don't** ask through the AI in the chat instead. Claude Desktop's Code tab is one of these: it currently cancels the forms without showing them. The instrument still can't be connected until a layout has been chosen.

## Approval prompts (Claude Code)

The plugin's hook checks every `hamilton-venus` tool call before it runs. You approve control of real hardware **once per session**, not command by command. Claude Code shows an approval prompt with the reason:

| Approval | When it is asked | What approving covers |
|---|---|---|
| Control of the live instrument | Starting a live session (`start_session` with `simulate=false`), or the first hardware command in a live session the hook found already open | Every command of that session, until it is closed or another session is started. Choosing **Live** in `start_session`'s own simulation/live form counts as this approval. |
| Control of a standalone device (`hhc_*`, `odtc_*`, `inheco_tec_*`, `tilt_module_*`, `media_fill_*`) | The device's first command that isn't run with `simulate=true`. These devices run independently of the instrument session. | That device's commands from then on |
| VENUS run control (`venus_abort`, `venus_pause`, `venus_resume`) and a script run on hardware (`run_script` with `simulate=false`) | Every time, because these act on whatever VENUS is running | That one call |

Nothing is asked in a simulated session, for read-only queries (`get_*`, `is_*`, `list_*`, `*_status`, ...), or for docs and catalogs. Those follow your normal Claude Code permission settings.

`operator_resolve_prompt` is always refused: only a person answers script-run prompts, on the operator page or the hub dashboard.

The hook learns whether the session is simulated from `start_session` and `get_session_status`. When it doesn't know, it asks. If the hook itself fails, it asks too.

The approval prompt is an extra safeguard, not a replacement for the existing ones:
- Sessions and script runs are simulated unless real hardware is requested.
- Script runs on real hardware also need `HAMILTON_MCP_ALLOW_HARDWARE=1` on the spoke.
- People answer script errors.

See the [MCP Guide](../mcp_server/mcp-guide.md#7-safety).

### Hardware call log

Every executed hardware call, whether it was asked about or ran under an approval already given, is appended to `%LOCALAPPDATA%\Hamilton\ai_harness\hardware_calls.jsonl`. Each line records the time, Claude session id, tool, arguments, reason and result status.

## A network spoke or the hub

The plugin starts a local spoke on this PC. To drive a spoke on another PC, or the hub, add it to Claude Code as an HTTP server, as described in the [MCP Guide](../mcp_server/mcp-guide.md) (Modes B and C). The approval hook also covers a server you add under the name `hamilton-venus`.

## Removing it

- **Claude Code:** `claude plugin uninstall hamilton-venus@hamilton`, then `claude plugin marketplace remove hamilton`.
- **Claude Desktop:** delete the `hamilton-venus` entry under `mcpServers` in its config file, or restore the `.bak` copy, then restart Claude Desktop.
- **Abacus AI and other agents:** delete the `hamilton-*` folders in `%USERPROFILE%\.agents\skills`, and the `hamilton-venus` entry in `%USERPROFILE%\.abacusai\mcp.json` (or restore its `.bak` copy).

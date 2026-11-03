# AI Assistant

The Hamilton AI Assistant is a desktop app for running a STAR or Vantage by chatting with an AI agent. You ask in plain words ("add 100 µL of ethanol to every well of the Nunc plate"); the assistant plans the steps and runs them through the VENUS Python SDK, asking you before it does anything that matters.

It is built on the same pieces as the [AI assistant setup](../ai_harness/ai-assistants.md) for Claude Code and Claude Desktop: the Hamilton MCP server, the Hamilton skills and the approval rules. It is a dedicated app instead, with nothing else to install or configure:

- **Questions as cards:** simulation or live, the deck layout and approvals appear as cards in the chat, not as text questions.
- **Locked down:** the agent can only use the instrument tools. It has no file, shell or web access.
- **Records:** every conversation is kept on this PC.

## Installing

Tick **Install Hamilton AI Assistant app** in `VenusPythonSdkInstaller.exe`, in the repository root. It needs the MCP server, so ticking it ticks **Install MCP server for AI agents** too. Then open `HamiltonAIAssistant.exe` in this folder.

The install adds about 300 MB: the agent runtime (`claude-agent-sdk`) bundles its own engine.

## First start: the AI provider

The assistant talks to Claude through the Anthropic Messages API. Under **Settings**:

| Setting | What to enter |
|---|---|
| **Endpoint (base URL)** | Empty for Anthropic. For a company gateway, its address, for example `https://yourcompany.abacus.ai`. Any Anthropic-compatible endpoint works (Abacus, AWS Bedrock or Google Vertex gateways, LiteLLM, ...). |
| **Model** | Pick from the list of models your endpoint offers. Claude models come first: the assistant is built and tested with them. Any name the endpoint accepts can be typed. |
| **Sign-in** | How the assistant signs in to that endpoint: an API key, or your company's single sign-on (see below). Credentials are stored encrypted for your Windows user on this PC (Windows DPAPI) and are never shown again. **Test connection** sends a one-word message to check the sign-in, endpoint and model together. |

Changes apply to the next conversation.

### Signing in

Pick the **Sign-in method** under **Settings > Sign-in** (the choice appears when more than one is available).

**API key.** Paste the key for the endpoint. Some providers only give keys to developer accounts; if you can't get one, ask whether your company offers the sign-in below.

**Company sign-in (SSO).** For a company gateway or identity provider that supports the OAuth *device code* flow, the same kind of sign-in the Abacus VS Code extension uses. Your administrator gives you the **Issuer** (or the **device authorization** and **token** endpoints, under *Advanced*) and a **Client ID**. Then:

1. Click **Sign in**. The assistant shows a code and opens your browser.
2. Check the code on the page, sign in with your company account, and approve.
3. The assistant notices and shows who is signed in. **Sign out** forgets the sign-in.

The sign-in tokens stay inside the app and are refreshed by it. The agent engine never holds one for longer than a couple of minutes: it asks the app for the current token through a small helper program (`credential_helper.py`) that only works with a secret made when the app started, so long conversations carry on past one token's life. Use **The gateway reads the token from** (*Advanced*) if your gateway wants an `x-api-key` header instead of `Authorization: Bearer`.

**Anthropic Console / SSO.** Sign in with your organization's Anthropic Console account (API billing, or the organization's single sign-on, which you can tick). **Sign in** runs the agent engine's own sign-in, which opens your browser and keeps the login in the app's private folder; the assistant never sees it. The endpoint above is not used with this method: it talks to Anthropic.

**Cloud provider (Bedrock / Vertex / Foundry).** Use your company's cloud account for Claude, signed in with the cloud tool on this PC:

| Provider | Enter | **Sign in** runs |
|---|---|---|
| Amazon Bedrock | Region, and an AWS SSO profile (`aws configure sso`) | `aws sso login --profile <profile>` |
| Google Cloud (Vertex AI) | Region, project | `gcloud auth application-default login` |
| Microsoft Foundry | Resource name | `az login` |

The tool must be installed on this PC. The assistant shows who is signed in, and for Bedrock the engine signs in again by itself when the SSO session ends. Cloud providers name models their own way, so enter that name under **Model** (for example a Bedrock model or inference profile ID); the model list can't be read from them.

Not offered, on purpose: signing in with a personal Claude.ai (Free, Pro or Max) account. Anthropic's terms don't allow apps built on its Agent SDK to offer that, so the assistant works with API keys, your company's gateway or cloud provider, and a company sign-in.

## Running the instrument

1. **Ask.** For example *"Connect to the simulated STAR and show me the tip counters."*
2. **Answer the opening card.** The assistant always asks:
   - **Run mode:** simulation, or the live instrument.
   - **Session name** (optional): how the session appears in VENUS run control and run history, and the conversation's title. Left empty, the run is `hamilton-venus-mcp`.
3. **Choose the deck layout:** a blank deck, the last layout used (with a summary of its carriers, labware and tip pools), or one of the saved layouts.
4. The assistant connects the instrument, checks its configuration, and carries on with what you asked. Before a series of pipetting or transport steps it says what it is about to do, and afterwards what happened.

### Live instrument control

Choosing **Live instrument** in the opening card gives the assistant control of the real instrument for that session: it runs the session's commands without asking again until the session is closed. If the assistant asks to go live some other way, an approval card asks you first. Some actions always ask:

- each standalone device (Heater Cooler, ODTC, ...), once per conversation;
- VENUS run control (abort, pause, resume), every time.

Answering a script run's error prompt is never left to the assistant: a person answers it on the operator page.

**Stop** halts the assistant at any time.

## The status strip

Under the title, always in view while chatting:

| Item | Shows |
|---|---|
| **Connection** | This PC, a network spoke, or a hub (and which instrument). |
| **Session** | The conversation's title (click the pencil to rename it), then simulation or LIVE, the instrument and whether it is connected. The deck layout and the VENUS session name are in its tooltip. |
| **Instrument** | What the instrument server is doing, with the colour of the instrument's front status light: white idle, green running, red waiting on an error, blue stopped. |
| **VENUS** | What is happening right now, in words: *Running aspirate*, *Waiting for you: Which deck layout should this session use?*, *Session open, waiting for the next command*, *Waiting for a person: ...*. VENUS's own run state is in its tooltip. |

When a script run needs a person, a red notice gives the operator page's address.

**Auto-scroll** (bottom right) keeps the chat on the newest message, so a card waiting for your answer is always in view. With it off, a notice tells you when the assistant is waiting for you further down.

## The deck view

**View deck** shows the instrument's deck in 3D, live from VENUS: labware the assistant adds, plates it moves and tips it uses appear as they happen. It opens by itself the first time a session connects.

- **Resize:** drag the bar between the deck and the chat; the height is remembered.
- **Undock:** opens the deck in its own window, for a second monitor or beside the chat. It follows the same instrument and shows the conversation's title and what is happening. **Show it here instead** docks it again.
- **Auto-Zoom**, **Top / Default** view, **Refresh 3D View** and **Maximize** work as in the Script Manager.

## Conversations

Every conversation is kept on this PC (`%LOCALAPPDATA%\Hamilton\AI Assistant\conversations\`, one file per conversation). Each file records:

- who asked what (Windows user and time);
- each command the assistant ran and its result;
- each approval and form answer, and who gave it.

**Conversations** lists them by title, newest first, with those that used the live instrument marked. **Open** reopens one: the history comes back and the assistant remembers what was said. Any instrument session from then has been closed, so ask it to start a new one.

**New conversation** ends the current one and closes its instrument session.

## Instrument connection

Under **Settings > Instrument connection**:

| Choice | Use when |
|---|---|
| **This PC** (default) | VENUS and the instrument are on this PC. The assistant starts the MCP server itself. |
| **Network spoke** | The instrument is on another PC running the MCP server in network mode ([MCP guide](../mcp_server/mcp-guide.md), Mode B). Enter its address (`http://instrument-pc:8000/mcp`; a PC name alone gets port 8000 and `/mcp`) and its bearer token. |
| **Hub** | A hub relays to several instrument PCs ([MCP guide](../mcp_server/mcp-guide.md), Mode C). Enter the hub's address and token. The assistant asks which instrument to use; approvals apply to each instrument separately. **Deck viewer shows** picks whose deck the viewer follows (by default, the instrument the assistant is working on). |

The deck view and the VENUS status read VENUS directly on the instrument PC (port 42400), so that port must be reachable from this PC. **Deck viewer address** is only needed when the instrument PC can't be reached by the name in the address (over a VPN, for example).

Through a hub the app can't show the opening card, so the assistant asks simulation or live and the deck layout in the chat.

## Troubleshooting

| Problem | What to do |
|---|---|
| "Add your API key under Settings" | No key is saved: add one under Settings and press **Test connection**. |
| **Test connection** fails | The message says whether the endpoint was unreachable, rejected the key, or answered with an error (for example an unknown model name). |
| "The Hamilton MCP server is not installed" | Re-run the installer with **Install MCP server for AI agents** ticked. |
| The assistant says VENUS is running a method it didn't start | Another program (or a left-over session) is running a method. Decide whether it is safe to stop: the assistant only aborts it after you approve. |
| The deck view says it can't reach VENUS | VENUS isn't running on the instrument PC, or port 42400 is blocked between the PCs. |
| The window closed unexpectedly | It is restarted automatically and the conversation is still there; a command that was running carries on. |

App logs: `%LOCALAPPDATA%\Hamilton\HamiltonAIAssistant\logs`.

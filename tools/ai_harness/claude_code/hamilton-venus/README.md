# hamilton-venus Claude Code plugin

Installed by the VENUS Python SDK installer ("Set up AI assistants"). It gives Claude Code:

- **The `hamilton-venus` MCP server** (the spoke), started over stdio from the SDK's `.venv`.
- **Hamilton skills:** labware ↔ carrier compatibility, liquid handling rules, liquid class optimization, tip counter setup, script authoring.
- **A hardware approval gate:** Claude Code asks you before any call that moves a real instrument or device, and every executed hardware call is logged to `%LOCALAPPDATA%\Hamilton\ai_harness\hardware_calls.jsonl`.

See `tools/ai_harness/ai-assistants.md` in the SDK for setup and details.

The `skills/` folder is copied from the SDK's `.claude/skills/` when the installer is built; edit the skills there, not here.

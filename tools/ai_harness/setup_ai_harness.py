"""Set up Claude Code and Claude Desktop to drive Hamilton instruments through the MCP spoke.

Run by the VENUS Python SDK installer ("Set up AI assistants") with the SDK venv's Python,
after this folder has been copied to the install location:

    <venv>\\Scripts\\python.exe <install>\\ai_harness\\setup_ai_harness.py --venv <venv>

It can be re-run by hand at any time; every step is idempotent.

1. Stages a ready copy of claude_code\\ in %LOCALAPPDATA%\\Hamilton\\ai_harness\\marketplace:
   {{VENV}} filled in (.mcp.json, hooks/hooks.json) and the Hamilton skills included
   (bundled with the installer, or the SDK's .claude\\skills when run from the repo).
   The files next to this script are never changed.
2. Claude Code: registers that copy as the local marketplace "hamilton"
   and installs the hamilton-venus plugin (MCP server + skills + hardware approval hook)
   for the current Windows user, using whichever claude.exe it finds (PATH, the native
   installer, Claude Desktop's bundled copy, or the VS Code extension's).
3. Claude Desktop: adds an "hamilton-venus" entry under mcpServers in each
   claude_desktop_config.json it finds (the Microsoft Store build keeps it under
   %LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude, the classic build under
   %APPDATA%\\Claude). Only that key is touched, the file is backed up first, and an
   existing hamilton-venus entry is left alone.

4. Other agents (Abacus AI and anything that follows the open Agent Skills format): copies the
   Hamilton skills to ~\\.agents\\skills, and, if Abacus AI is installed (~\\.abacusai), adds the
   hamilton-venus server to its mcp.json (backed up first; an existing entry is left alone).
   `--export DIR` instead writes a portable bundle (skills, mcp.json, README) for any other tool.

A step that can't run (no Claude Code, no Claude Desktop, no Abacus AI) is reported and skipped. The
exit code is non-zero only when every applicable step failed.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The SDK's own skills: next to this folder in an install (<sdk>\ai_harness), two levels up in the
# repo (<repo>\tools\ai_harness).
REPO_SKILLS = [HERE.parent / ".claude" / "skills", HERE.parent.parent / ".claude" / "skills"]
MARKETPLACE = "hamilton"
PLUGIN = "hamilton-venus"
SERVER = "hamilton-venus"
TEMPLATED = (Path(".mcp.json"), Path("hooks") / "hooks.json")


def log(message: str) -> None:
    print(message, flush=True)


def harness_dir() -> Path:
    override = os.environ.get("HAMILTON_AI_HARNESS_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Hamilton" / "ai_harness"


def stage_marketplace(venv: Path) -> Path:
    """Copy claude_code\\ to the per-user staging folder with the venv path and skills filled in."""
    dest = harness_dir() / "marketplace"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(HERE / "claude_code", dest, ignore=shutil.ignore_patterns("__pycache__"))
    plugin = dest / PLUGIN
    for rel in TEMPLATED:
        path = plugin / rel
        path.write_text(path.read_text(encoding="utf-8").replace("{{VENV}}", venv.as_posix()), encoding="utf-8")
    repo_skills = next((c for c in REPO_SKILLS if c.is_dir()), None)
    if not (plugin / "skills").is_dir() and repo_skills is not None:
        shutil.copytree(repo_skills, plugin / "skills")
    log(f"Staged the Claude Code plugin in {dest}")
    return dest


def build_desktop_skill_zips() -> Path | None:
    """Claude Desktop takes each skill as an uploaded zip: make them in the per-user folder."""
    source = skills_source()
    if source is None:
        return None
    dest = harness_dir() / "claude_desktop" / "skills"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for skill in source.glob("*/SKILL.md"):
        shutil.make_archive(str(dest / skill.parent.name), "zip", source, skill.parent.name)
    return dest


def _newest(paths: list[str]) -> str | None:
    existing = [p for p in paths if os.path.isfile(p)]
    return max(existing, key=os.path.getmtime) if existing else None


def find_claude_cli() -> str | None:
    """The claude.exe to install the plugin with: PATH first, then known install locations."""
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    native = home / ".local" / "bin" / "claude.exe"
    if native.is_file():
        return str(native)
    # Claude Desktop's bundled Claude Code (Store build, then classic), then the VS Code extension's.
    store_desktop = local / "Packages" / "Claude_*" / "LocalCache" / "Roaming" / "Claude"
    patterns = [
        store_desktop / "claude-code" / "*" / "*" / "claude.exe",
        roaming / "Claude" / "claude-code" / "*" / "*" / "claude.exe",
        home / ".vscode" / "extensions" / "anthropic.claude-code-*" / "resources" / "native-binary" / "claude.exe",
    ]
    return _newest([match for pattern in patterns for match in glob.glob(str(pattern))])


def _claude(cli: str, *args: str) -> subprocess.CompletedProcess[str]:
    # From the home folder, so a project's own .mcp.json / local MCP entries don't show up.
    return subprocess.run(
        [cli, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, cwd=Path.home()
    )


def setup_claude_code(cli: str | None, marketplace_dir: Path) -> bool | None:
    """True when the plugin is installed, False on failure, None when Claude Code isn't on this PC."""
    if cli is None:
        log("Claude Code: not found on this PC -- skipped. After installing Claude Code, run:")
        log(f'  claude plugin marketplace add "{marketplace_dir}"')
        log(f"  claude plugin install {PLUGIN}@{MARKETPLACE}")
        return None
    log(f"Claude Code: using {cli}")
    # Re-adding refreshes the marketplace from the staged folder, so a reinstall picks up new files.
    _claude(cli, "plugin", "uninstall", f"{PLUGIN}@{MARKETPLACE}")
    _claude(cli, "plugin", "marketplace", "remove", MARKETPLACE)
    added = _claude(cli, "plugin", "marketplace", "add", str(marketplace_dir))
    if added.returncode != 0:
        log(f"Claude Code: could not add the marketplace:\n{added.stdout}{added.stderr}")
        return False
    installed = _claude(cli, "plugin", "install", f"{PLUGIN}@{MARKETPLACE}")
    if installed.returncode != 0:
        log(f"Claude Code: could not install the plugin:\n{installed.stdout}{installed.stderr}")
        return False
    log(f"Claude Code: installed {PLUGIN}@{MARKETPLACE} (MCP server, Hamilton skills, hardware approval hook).")
    if _claude(cli, "mcp", "get", SERVER).returncode == 0:
        log(
            f'Claude Code: an older manually added MCP server "{SERVER}" is also registered; the plugin replaces it. '
            f"Remove it with: claude mcp remove {SERVER}"
        )
    return True


def desktop_config_paths() -> list[Path]:
    """claude_desktop_config.json of every Claude Desktop install found (it need not exist yet)."""
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    dirs = [Path(p) for p in glob.glob(str(local / "Packages" / "Claude_*" / "LocalCache" / "Roaming" / "Claude"))]
    if (roaming / "Claude").is_dir():
        dirs.append(roaming / "Claude")
    return [d / "claude_desktop_config.json" for d in dirs]


def add_desktop_server(config_path: Path, server_exe: Path, args: list[str] | None = None) -> str:
    """Add the hamilton-venus server to one MCP config (Claude Desktop's claude_desktop_config.json,
    Abacus's mcp.json: the same "mcpServers" layout). *args* is written when given (Abacus requires
    it for a local server). Returns what was done."""
    config: dict = {}
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8") or "{}")
    servers = config.setdefault("mcpServers", {})
    if SERVER in servers:
        return "already has a hamilton-venus server (left as it is)"
    if config_path.exists():
        backup = config_path.with_name(f"{config_path.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
        shutil.copy2(config_path, backup)
    servers[SERVER] = {"command": str(server_exe)} if args is None else {"command": str(server_exe), "args": args}
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return "added the hamilton-venus server"


# -- Agent Skills (generic) ------------------------------------------------------------------
# The Hamilton skills are plain Agent Skills (https://agentskills.io): skills/<name>/SKILL.md with
# a name (= the folder name) and a description, plus the files it refers to. Tools that follow that
# format read ~/.agents/skills, so one copy there serves them all (Abacus AI reads it, as do
# others); Claude Code gets the skills through its plugin instead.

def skills_source() -> Path | None:
    """The Hamilton skills to install: bundled with the installer, or the SDK's own when run from the repo."""
    for candidate in (HERE / "claude_code" / PLUGIN / "skills", *REPO_SKILLS):
        if candidate.is_dir() and any(candidate.glob("*/SKILL.md")):
            return candidate
    return None


def copy_skills(source: Path, target: Path) -> list[str]:
    """Copy each Hamilton skill folder to *target*, replacing an earlier copy. Only folders named
    hamilton-* with a SKILL.md are touched, so other skills in the folder are left alone."""
    names = []
    for folder in sorted(source.iterdir()):
        if not (folder.is_dir() and folder.name.startswith("hamilton-") and (folder / "SKILL.md").is_file()):
            continue
        dest = target / folder.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(folder, dest, ignore=shutil.ignore_patterns("__pycache__"))
        names.append(folder.name)
    return names


def agent_skills_dir() -> Path:
    return Path.home() / ".agents" / "skills"


def setup_agent_skills(target: Path | None = None) -> bool | None:
    source = skills_source()
    if source is None:
        log("Agent skills: the Hamilton skills were not found -- skipped.")
        return False
    target = target or agent_skills_dir()
    try:
        names = copy_skills(source, target)
    except OSError as exc:
        log(f"Agent skills: could not copy the skills to {target}: {exc}")
        return False
    log(f"Agent skills: {len(names)} Hamilton skills in {target} (read by Abacus AI and other tools that "
        "follow the Agent Skills format; start a new session to load them).")
    return True


# -- Abacus AI --------------------------------------------------------------------------------

def abacus_mcp_path() -> Path:
    """Abacus's user-level MCP config, shared by its desktop app, VS Code extension and CLI."""
    return Path.home() / ".abacusai" / "mcp.json"


def setup_abacus(venv: Path) -> bool | None:
    config = abacus_mcp_path()
    if not config.parent.is_dir():
        log("Abacus AI: not found on this PC (no .abacusai folder) -- skipped.")
        return None
    server_exe = venv / "Scripts" / "hamilton-venus-mcp.exe"
    try:
        log(f"Abacus AI: {config}: {add_desktop_server(config, server_exe, args=[])}")
    except (OSError, ValueError) as exc:
        log(f"Abacus AI: could not update {config}: {exc}")
        return False
    log("Abacus AI: start a new session to load the server.")
    return True


# -- Export for any other tool ----------------------------------------------------------------

EXPORT_README = """# Hamilton AI harness, for any agent

- skills\\    The Hamilton skills, in the open Agent Skills format (skills\\<name>\\SKILL.md).
- mcp.json   The Hamilton MCP server, in the usual "mcpServers" layout.

Abacus AI: copy the folders in skills\\ to %USERPROFILE%\\.agents\\skills (every project) or to
<project>\\.agents\\skills, and merge mcp.json's server into %USERPROFILE%\\.abacusai\\mcp.json.
Other tools that read Agent Skills: copy skills\\ to the folder they read skills from.
Tools without skills: the server's own instructions (and its get_usage_guide tool) carry the essentials.
"""


def export_portable(venv: Path, dest: Path) -> bool:
    source = skills_source()
    if source is None:
        log("Export: the Hamilton skills were not found.")
        return False
    names = copy_skills(source, dest / "skills")
    server_exe = venv / "Scripts" / "hamilton-venus-mcp.exe"
    mcp = {"mcpServers": {SERVER: {"command": str(server_exe), "args": []}}}
    (dest / "mcp.json").write_text(json.dumps(mcp, indent=2), encoding="utf-8")
    (dest / "README.md").write_text(EXPORT_README, encoding="utf-8")
    log(f"Export: {len(names)} skills, mcp.json and README.md written to {dest}")
    return True


def setup_claude_desktop(venv: Path) -> bool | None:
    paths = desktop_config_paths()
    if not paths:
        log("Claude Desktop: not found on this PC -- skipped.")
        return None
    server_exe = venv / "Scripts" / "hamilton-venus-mcp.exe"
    ok = True
    for path in paths:
        try:
            log(f"Claude Desktop: {path}: {add_desktop_server(path, server_exe)}")
        except (OSError, ValueError) as exc:
            log(f"Claude Desktop: could not update {path}: {exc}")
            ok = False
    if ok:
        log("Claude Desktop: fully quit and restart it to load the server.")
        skills = build_desktop_skill_zips()
        if skills is not None:
            log(f"Claude Desktop: to add the Hamilton skills, upload the zips in {skills} "
                "under Settings > Capabilities.")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--venv", required=True, type=Path, help="The SDK venv (holds Scripts\\hamilton-venus-mcp.exe)")
    parser.add_argument("--skip-claude-code", action="store_true")
    parser.add_argument("--skip-claude-desktop", action="store_true")
    parser.add_argument("--skip-agent-skills", action="store_true",
                        help="Don't copy the skills to ~/.agents/skills (read by Abacus AI and other agents)")
    parser.add_argument("--skip-abacus", action="store_true")
    parser.add_argument("--agent-skills-dir", type=Path, help="Copy the skills here instead of ~/.agents/skills")
    parser.add_argument("--export", type=Path, metavar="DIR",
                        help="Only write a portable bundle (skills, mcp.json, README) to DIR, for any other tool")
    args = parser.parse_args(argv)

    venv = args.venv.resolve()
    if not (venv / "Scripts" / "hamilton-venus-mcp.exe").is_file():
        log(f"No hamilton-venus-mcp.exe under {venv}\\Scripts -- install the MCP server first.")
        return 1
    if args.export:
        return 0 if export_portable(venv, args.export.resolve()) else 1
    results = []
    if not args.skip_claude_code:
        results.append(setup_claude_code(find_claude_cli(), stage_marketplace(venv)))
    if not args.skip_claude_desktop:
        results.append(setup_claude_desktop(venv))
    if not args.skip_agent_skills:
        results.append(setup_agent_skills(args.agent_skills_dir))
    if not args.skip_abacus:
        results.append(setup_abacus(venv))
    applicable = [r for r in results if r is not None]
    return 1 if applicable and not any(applicable) else 0


if __name__ == "__main__":
    sys.exit(main())

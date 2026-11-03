"""ai_harness/setup_ai_harness.py: plugin staging and the Claude Desktop config merge."""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "ai_harness" / "setup_ai_harness.py"

_spec = importlib.util.spec_from_file_location("setup_ai_harness", SCRIPT)
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("HAMILTON_AI_HARNESS_DIR", str(tmp_path / "harness"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def venv(tmp_path):
    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "hamilton-venus-mcp.exe").write_bytes(b"")
    return tmp_path / "venv"


def test_stage_fills_venv_and_skills_without_touching_sources(home, venv):
    before = (REPO_ROOT / "tools" / "ai_harness" / "claude_code" / "hamilton-venus" / ".mcp.json").read_text()
    staged = setup.stage_marketplace(venv)
    plugin = staged / "hamilton-venus"
    mcp = json.loads((plugin / ".mcp.json").read_text())
    assert mcp["mcpServers"]["hamilton-venus"]["command"] == f"{venv.as_posix()}/Scripts/hamilton-venus-mcp.exe"
    assert "{{VENV}}" not in (plugin / "hooks" / "hooks.json").read_text()
    assert (plugin / "skills" / "hamilton-liquid-handling-rules" / "SKILL.md").is_file()
    assert (REPO_ROOT / "tools" / "ai_harness" / "claude_code" / "hamilton-venus" / ".mcp.json").read_text() == before


def test_desktop_store_and_classic_configs_get_the_server(home, venv):
    store = home / "Local" / "Packages" / "Claude_abc" / "LocalCache" / "Roaming" / "Claude"
    store.mkdir(parents=True)
    (store / "claude_desktop_config.json").write_text(json.dumps({"preferences": {"sidebarMode": "x"}}))
    classic = home / "Roaming" / "Claude"
    classic.mkdir(parents=True)

    assert setup.setup_claude_desktop(venv) is True

    merged = json.loads((store / "claude_desktop_config.json").read_text())
    assert merged["preferences"] == {"sidebarMode": "x"}
    assert merged["mcpServers"]["hamilton-venus"]["command"].endswith("hamilton-venus-mcp.exe")
    assert list(store.glob("claude_desktop_config.json.*.bak"))
    assert "hamilton-venus" in json.loads((classic / "claude_desktop_config.json").read_text())["mcpServers"]


def test_desktop_existing_entry_is_left_alone(home, venv):
    classic = home / "Roaming" / "Claude"
    classic.mkdir(parents=True)
    original = {"mcpServers": {"hamilton-venus": {"command": "custom.exe"}}}
    (classic / "claude_desktop_config.json").write_text(json.dumps(original))
    setup.setup_claude_desktop(venv)
    assert json.loads((classic / "claude_desktop_config.json").read_text()) == original
    assert not list(classic.glob("*.bak"))


def test_nothing_installed_is_skipped_not_failed(home, venv, monkeypatch):
    monkeypatch.setattr(setup, "find_claude_cli", lambda: None)
    assert setup.main(["--venv", str(venv)]) == 0


def test_missing_server_exe_fails(home, tmp_path):
    assert setup.main(["--venv", str(tmp_path / "nowhere")]) == 1


# -- generic Agent Skills, Abacus AI and the portable export ----------------------------------

def test_skills_are_copied_for_other_agents_and_other_skills_are_left_alone(home):
    target = home / ".agents" / "skills"
    (target / "someone-elses-skill").mkdir(parents=True)
    (target / "someone-elses-skill" / "SKILL.md").write_text("---\nname: someone-elses-skill\ndescription: x\n---\n")
    (target / "hamilton-script-authoring").mkdir()
    (target / "hamilton-script-authoring" / "stale.txt").write_text("from an older install")

    assert setup.setup_agent_skills() is True

    installed = sorted(p.name for p in target.iterdir())
    assert installed == ["hamilton-channel-random-access", "hamilton-deck-geometry", "hamilton-deck-tracking",
                         "hamilton-gripper-transport", "hamilton-labware-compatibility",
                         "hamilton-liquid-class-optimization", "hamilton-liquid-handling-rules",
                         "hamilton-load-tray-autoload", "hamilton-script-authoring", "hamilton-tilt-module",
                         "hamilton-tip-counter-setup", "someone-elses-skill"]
    assert not (target / "hamilton-script-authoring" / "stale.txt").exists()  # replaced, not merged
    assert (target / "hamilton-script-authoring" / "template.py").is_file()  # the files a skill refers to come along
    assert (target / "someone-elses-skill" / "SKILL.md").is_file()


def test_every_skill_is_a_plain_agent_skill(home):
    """What other tools need: SKILL.md with a name that is the folder name and a description of at
    most 1,024 characters, and nothing that only Claude understands."""
    import re

    import yaml

    setup.setup_agent_skills()
    skills = sorted((home / ".agents" / "skills").iterdir())
    assert len(skills) == 11
    for folder in skills:
        text = (folder / "SKILL.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---")[1])
        assert meta["name"] == folder.name and re.fullmatch(r"[a-z0-9-]{1,64}", folder.name), folder.name
        assert 0 < len(meta["description"]) <= 1024, folder.name
        assert set(meta) <= {"name", "description", "license", "compatibility", "metadata"}, folder.name
        assert not re.search(r"(?i)claude code|mcp__|\.claude[\\/]|CLAUDE\.md", text), folder.name


def test_abacus_gets_the_server_and_an_existing_entry_is_left_alone(home, venv):
    config = home / ".abacusai" / "mcp.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x", "args": []}}}))

    assert setup.setup_abacus(venv) is True

    merged = json.loads(config.read_text())
    assert merged["mcpServers"]["other"] == {"command": "x", "args": []}
    entry = merged["mcpServers"]["hamilton-venus"]
    assert entry["command"].endswith("hamilton-venus-mcp.exe") and entry["args"] == []  # Abacus needs args
    assert list(config.parent.glob("mcp.json.*.bak"))

    before = config.read_text()
    assert setup.setup_abacus(venv) is True
    assert config.read_text() == before


def test_abacus_not_installed_is_skipped(home, venv):
    assert setup.setup_abacus(venv) is None
    assert not (home / ".abacusai").exists()


def test_export_writes_a_bundle_any_tool_can_use(home, venv, tmp_path):
    dest = tmp_path / "bundle"
    assert setup.main(["--venv", str(venv), "--export", str(dest)]) == 0
    assert (dest / "skills" / "hamilton-tip-counter-setup" / "SKILL.md").is_file()
    mcp = json.loads((dest / "mcp.json").read_text())
    assert mcp["mcpServers"]["hamilton-venus"]["args"] == []
    assert "Abacus" in (dest / "README.md").read_text()
    assert not (home / ".agents").exists()  # an export changes nothing on this PC


def test_skip_flags_and_a_custom_skills_folder(home, venv, monkeypatch):
    monkeypatch.setattr(setup, "find_claude_cli", lambda: None)
    elsewhere = home / "elsewhere"
    assert setup.main(["--venv", str(venv), "--skip-claude-code", "--skip-claude-desktop",
                       "--agent-skills-dir", str(elsewhere)]) == 0
    assert (elsewhere / "hamilton-script-authoring" / "SKILL.md").is_file()
    assert not (home / ".agents").exists()
    assert setup.main(["--venv", str(venv), "--skip-claude-code", "--skip-claude-desktop", "--skip-agent-skills",
                       "--skip-abacus"]) == 0
    assert not (home / ".agents").exists()


def test_plugin_skills_match_the_repo_skills():
    """The skills ship inside the harness; .claude/skills is the repo's own copy. They must not drift."""
    plugin = REPO_ROOT / "tools" / "ai_harness" / "claude_code" / "hamilton-venus" / "skills"
    repo = REPO_ROOT / ".claude" / "skills"
    if not repo.is_dir():  # a checkout without the repo's own .claude folder (e.g. the ADO repo)
        return

    def files(root):
        return {p.relative_to(root).as_posix(): p.read_bytes().replace(b"\r\n", b"\n")
                for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts}

    assert files(plugin) == files(repo), "tools/ai_harness/.../skills and .claude/skills differ; copy one over the other"


def test_claude_desktop_skill_zips_are_built_per_user(tmp_path, monkeypatch):
    monkeypatch.setenv("HAMILTON_AI_HARNESS_DIR", str(tmp_path))
    dest = setup.build_desktop_skill_zips()
    assert dest == tmp_path / "claude_desktop" / "skills"
    with zipfile.ZipFile(dest / "hamilton-deck-tracking.zip") as archive:
        assert "hamilton-deck-tracking/SKILL.md" in {n.replace("\\", "/") for n in archive.namelist()}

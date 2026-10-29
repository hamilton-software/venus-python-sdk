from __future__ import annotations

import argparse
import logging
from pathlib import Path

from hamilton_venus.setup_tools import cli


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "prereqs": Path("C:/sdk/prerequisites"),
        "structure": Path("C:/sdk/sdk_method_structure"),
        "target": None,
        "skip_prereqs": False,
        "skip_structure": False,
        "dry_run": False,
        "force": False,
        "interactive": False,
        "prompt": False,
        "verbose": False,
        "skip_catalog": False,
        "skip_version_check": True,
        "manifest": None,
        "install_py32": False,
        "py32_from": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_build_prereq_args_includes_headless_by_default() -> None:
    args = _args(dry_run=True, verbose=True, interactive=False)

    result = cli._build_prereq_args(args)

    assert result == [
        "--prereqs",
        str(Path("C:/sdk/prerequisites")),
        "--dry-run",
        "--verbose",
        "--headless",
    ]


def test_build_prereq_args_omits_headless_when_interactive() -> None:
    args = _args(interactive=True)

    result = cli._build_prereq_args(args)

    assert result == ["--prereqs", str(Path("C:/sdk/prerequisites"))]


def test_build_setup_args_includes_force_and_flags() -> None:
    args = _args(dry_run=True, force=True, verbose=True, target=Path("C:/custom/sdk"))

    result = cli._build_setup_args(args)

    assert result == [
        "--structure",
        str(Path("C:/sdk/sdk_method_structure")),
        "--target",
        str(Path("C:/custom/sdk")),
        "--dry-run",
        "--force",
        "--verbose",
    ]


def test_main_returns_2_when_both_steps_skipped(monkeypatch) -> None:
    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args(skip_prereqs=True, skip_structure=True))

    rc = cli.main([])

    assert rc == 2


def test_main_returns_1_when_user_declines(monkeypatch) -> None:
    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args(prompt=True))
    monkeypatch.setattr(cli, "confirm", lambda *_args, **_kwargs: False)

    rc = cli.main([])

    assert rc == 1


def test_main_returns_prereq_exit_code_on_prereq_failure(monkeypatch) -> None:
    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args())
    monkeypatch.setattr(cli.prerequisites, "main", lambda _argv=None: 7)
    monkeypatch.setattr(cli.structure, "main", lambda _argv=None: 0)
    monkeypatch.setattr(cli.generate_catalog, "main", lambda _argv=None: 0)

    rc = cli.main([])

    assert rc == 7


def test_main_runs_without_prompt_by_default(monkeypatch) -> None:
    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args(prompt=False))

    called = {"confirm": False}

    def _confirm(*_args, **_kwargs):
        called["confirm"] = True
        return False

    monkeypatch.setattr(cli, "confirm", _confirm)
    monkeypatch.setattr(cli.prerequisites, "main", lambda _argv=None: 0)
    monkeypatch.setattr(cli.structure, "main", lambda _argv=None: 0)
    monkeypatch.setattr(cli.generate_catalog, "main", lambda _argv=None: 0)

    rc = cli.main([])

    assert rc == 0
    assert called["confirm"] is False


def test_main_returns_structure_exit_code_on_structure_failure(monkeypatch) -> None:
    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args(skip_prereqs=True))
    monkeypatch.setattr(cli.structure, "main", lambda _argv=None: 9)
    monkeypatch.setattr(cli.generate_catalog, "main", lambda _argv=None: 0)

    rc = cli.main([])

    assert rc == 9


def test_main_runs_both_steps_successfully(monkeypatch) -> None:
    calls: list[tuple[str, list[str] | None]] = []

    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args())

    def _prereq_main(argv: list[str] | None = None) -> int:
        calls.append(("prereqs", argv))
        return 0

    def _structure_main(argv: list[str] | None = None) -> int:
        calls.append(("structure", argv))
        return 0

    def _catalog_main(argv: list[str] | None = None) -> int:
        calls.append(("catalog", argv))
        return 0

    monkeypatch.setattr(cli.prerequisites, "main", _prereq_main)
    monkeypatch.setattr(cli.structure, "main", _structure_main)
    monkeypatch.setattr(cli.generate_catalog, "main", _catalog_main)

    rc = cli.main([])

    assert rc == 0
    assert [name for name, _argv in calls] == ["prereqs", "structure", "catalog"]


def test_main_runs_catalog_by_default(monkeypatch) -> None:
    calls: list[tuple[str, list[str] | None]] = []

    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args())

    def _prereq_main(argv: list[str] | None = None) -> int:
        calls.append(("prereqs", argv))
        return 0

    def _structure_main(argv: list[str] | None = None) -> int:
        calls.append(("structure", argv))
        return 0

    def _catalog_main(argv: list[str] | None = None) -> int:
        calls.append(("catalog", argv))
        return 0

    monkeypatch.setattr(cli.prerequisites, "main", _prereq_main)
    monkeypatch.setattr(cli.structure, "main", _structure_main)
    monkeypatch.setattr(cli.generate_catalog, "main", _catalog_main)

    rc = cli.main([])

    assert rc == 0
    assert [name for name, _argv in calls] == ["prereqs", "structure", "catalog"]


def test_main_skips_catalog_when_flag_set(monkeypatch) -> None:
    calls: list[tuple[str, list[str] | None]] = []

    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args(skip_catalog=True))

    def _prereq_main(argv: list[str] | None = None) -> int:
        calls.append(("prereqs", argv))
        return 0

    def _structure_main(argv: list[str] | None = None) -> int:
        calls.append(("structure", argv))
        return 0

    def _catalog_main(argv: list[str] | None = None) -> int:
        calls.append(("catalog", argv))
        return 0

    monkeypatch.setattr(cli.prerequisites, "main", _prereq_main)
    monkeypatch.setattr(cli.structure, "main", _structure_main)
    monkeypatch.setattr(cli.generate_catalog, "main", _catalog_main)

    rc = cli.main([])

    assert rc == 0
    assert [name for name, _argv in calls] == ["prereqs", "structure"]


def test_main_passes_debug_flag_to_catalog_when_verbose(monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args(verbose=True))

    def _catalog_main(argv: list[str]) -> int:
        calls.append(("catalog", argv))
        return 0

    monkeypatch.setattr(cli.prerequisites, "main", lambda _argv=None: 0)
    monkeypatch.setattr(cli.structure, "main", lambda _argv=None: 0)
    monkeypatch.setattr(cli.generate_catalog, "main", _catalog_main)

    rc = cli.main([])

    assert rc == 0
    assert calls == [("catalog", ["--debug"])]


def test_main_skips_catalog_call_on_dry_run(monkeypatch, caplog) -> None:
    calls: list[tuple[str, list[str] | None]] = []

    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args(dry_run=True))

    def _prereq_main(argv: list[str] | None = None) -> int:
        calls.append(("prereqs", argv))
        return 0

    def _structure_main(argv: list[str] | None = None) -> int:
        calls.append(("structure", argv))
        return 0

    def _catalog_main(argv: list[str] | None = None) -> int:
        calls.append(("catalog", argv))
        return 0

    monkeypatch.setattr(cli.prerequisites, "main", _prereq_main)
    monkeypatch.setattr(cli.structure, "main", _structure_main)
    monkeypatch.setattr(cli.generate_catalog, "main", _catalog_main)

    with caplog.at_level(logging.INFO):
        rc = cli.main([])

    assert rc == 0
    assert [name for name, _argv in calls] == ["prereqs", "structure"]
    assert "[DRY-RUN] Would pull liquid classes from VENUS and generate static catalog" in caplog.text


def test_main_returns_catalog_exit_code_on_catalog_failure(monkeypatch) -> None:
    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args())
    monkeypatch.setattr(cli.prerequisites, "main", lambda _argv=None: 0)
    monkeypatch.setattr(cli.structure, "main", lambda _argv=None: 0)
    monkeypatch.setattr(cli.generate_catalog, "main", lambda _argv=None: 5)

    rc = cli.main([])

    assert rc == 5


def test_main_runs_py32_after_prereqs_before_structure(monkeypatch) -> None:
    calls: list[str] = []
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args(install_py32=True))

    def _prereq_main(argv: list[str] | None = None) -> int:
        calls.append("prereqs")
        return 0

    def _structure_main(argv: list[str] | None = None) -> int:
        calls.append("structure")
        return 0

    def _catalog_main(argv: list[str] | None = None) -> int:
        calls.append("catalog")
        return 0

    def _install(**kwargs: object) -> tuple[bool, str]:
        captured["kwargs"] = kwargs
        calls.append("py32")
        return True, "ok"

    monkeypatch.setattr(cli.prerequisites, "main", _prereq_main)
    monkeypatch.setattr(cli.structure, "main", _structure_main)
    monkeypatch.setattr(cli.generate_catalog, "main", _catalog_main)
    monkeypatch.setattr(cli.py32_runtime, "install_py32_runtime", _install)

    rc = cli.main([])

    assert rc == 0
    assert calls == ["prereqs", "py32", "structure", "catalog"]
    assert captured["kwargs"] == {"source_dir": None, "force": False, "dry_run": False}


def test_main_py32_from_implies_install(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda _argv=None: _args(
            skip_prereqs=True, skip_structure=True, skip_catalog=True, py32_from=Path("D:/py32-offline")
        ),
    )

    def _install(**kwargs: object) -> tuple[bool, str]:
        captured["kwargs"] = kwargs
        return True, "ok"

    monkeypatch.setattr(cli.py32_runtime, "install_py32_runtime", _install)

    rc = cli.main([])

    assert rc == 0
    assert captured["kwargs"] == {
        "source_dir": Path("D:/py32-offline"),
        "force": False,
        "dry_run": False,
    }


def test_main_skip_all_but_py32_is_not_nothing_to_do(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda _argv=None: _args(skip_prereqs=True, skip_structure=True, skip_catalog=True, install_py32=True),
    )
    monkeypatch.setattr(cli.py32_runtime, "install_py32_runtime", lambda **kwargs: (True, "ok"))

    rc = cli.main([])

    assert rc == 0


def test_main_py32_failure_returns_1_and_skips_structure(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "parse_args", lambda _argv=None: _args(skip_catalog=True, install_py32=True))

    def _prereq_main(argv: list[str] | None = None) -> int:
        calls.append("prereqs")
        return 0

    def _structure_main(argv: list[str] | None = None) -> int:
        calls.append("structure")
        return 0

    monkeypatch.setattr(cli.prerequisites, "main", _prereq_main)
    monkeypatch.setattr(cli.structure, "main", _structure_main)
    monkeypatch.setattr(cli.py32_runtime, "install_py32_runtime", lambda **kwargs: (False, "boom"))

    rc = cli.main([])

    assert rc == 1
    assert calls == ["prereqs"]

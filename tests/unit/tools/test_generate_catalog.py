from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from hamilton_venus.tools import main as tools_main
from hamilton_venus.tools.generate_catalog import (
    _assert_no_collisions,
    _collect_liquid_classes,
    _default_labware_path,
    _default_liquid_class_path,
    _load_existing_liquid_tree,
    _pull_liquid_classes,
    _render_liquid_class_module,
    _sanitize_identifier,
    _to_class_name,
    regenerate_catalog,
)
from hamilton_venus.tools.generate_catalog import main as generate_catalog_main


def test_sanitize_identifier_normalizes_values() -> None:
    assert _sanitize_identifier("Cos_96_Rd") == "COS_96_RD"
    assert _sanitize_identifier("X1-300Tip-B-Glycerin80-S-E") == "X1_300TIP_B_GLYCERIN80_S_E"
    assert _sanitize_identifier("384 Plate") == "N_384_PLATE"


def test_sanitize_identifier_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="Cannot create Python identifier"):
        _sanitize_identifier("---")


def test_assert_no_collisions_raises_for_conflicting_identifiers() -> None:
    with pytest.raises(ValueError, match="Identifier collision"):
        _assert_no_collisions("LABWARE.PLATES", ["Foo-Bar", "Foo Bar"])


def test_to_class_name_preserves_separator_between_parts() -> None:
    # Regression test: a naive "".join(...) between title-cased parts loses the
    # boundary between a folder-separator underscore and an underscore that is
    # part of a sanitized name (e.g. "Glycerin_80%" -> "GLYCERIN_80"), so a
    # sibling folder literally named "Glycerin80" -> "GLYCERIN80" would render
    # to the exact same class name and silently overwrite the other's subtree.
    assert _to_class_name("PARENT_GLYCERIN80") != _to_class_name("PARENT_GLYCERIN_80")


def test_render_liquid_class_module_keeps_sibling_folders_with_colliding_join_distinct() -> None:
    tree = {
        "Glycerin80": ["Foo_DispenseJet"],
        "Glycerin_80%": ["Bar_DispenseJet"],
    }

    content = _render_liquid_class_module("Generated static liquid class catalog.", "LIQUID_CLASSES", tree)

    class_names = re.findall(r"^class (\w+)\(", content, re.MULTILINE)
    assert len(class_names) == len(set(class_names))
    assert "FOO_DISPENSEJET" in content
    assert "BAR_DISPENSEJET" in content


def test_collect_liquid_classes_raises_when_path_missing(tmp_path: Path) -> None:
    missing_path = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError, match="Liquid class path not found"):
        _collect_liquid_classes(missing_path)


def test_collect_liquid_classes_reads_root_level_files(tmp_path: Path) -> None:
    liquid_root = tmp_path / "liquid class"
    liquid_root.mkdir(parents=True)
    (liquid_root / "Water_DispenseJet_Empty.xml").write_text("", encoding="utf-8")
    (liquid_root / "X1-300Tip-B-Glycerin80-S-E.liq").write_text("", encoding="utf-8")

    liquid_classes = _collect_liquid_classes(liquid_root)

    assert "STAR" in liquid_classes
    assert "Water_DispenseJet_Empty" in liquid_classes["STAR"]
    assert "X1-300Tip-B-Glycerin80-S-E" in liquid_classes["STAR"]


def test_default_paths_resolve_via_sdk_path_getters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hamilton_venus.tools.generate_catalog.get_sdk_labware_path",
        lambda: Path(r"C:\\sdk\\Labware"),
    )
    monkeypatch.setattr(
        "hamilton_venus.tools.generate_catalog.get_sdk_liquid_class_path",
        lambda: Path(r"C:\\sdk\\Liquid Class"),
    )

    assert _default_labware_path() == Path(r"C:\\sdk\\Labware")
    assert _default_liquid_class_path() == Path(r"C:\\sdk\\Liquid Class")


def test_generate_catalog_writes_expected_files(tmp_path: Path) -> None:
    labware_root = tmp_path / "Labware"
    (labware_root / "Carriers").mkdir(parents=True)
    (labware_root / "Plates").mkdir(parents=True)
    (labware_root / "Carriers" / "PLT_CAR_L5MD_A00.json").write_text("{}", encoding="utf-8")
    (labware_root / "Plates" / "Cos_96_Rd.json").write_text("{}", encoding="utf-8")

    liquid_root = tmp_path / "Liquid Class"
    (liquid_root / "STAR").mkdir(parents=True)
    (liquid_root / "STAR" / "Water_DispenseJet_Empty.liq").write_text("", encoding="utf-8")

    output_dir = tmp_path / "out"

    rc = generate_catalog_main(
        [
            "--labware-path",
            str(labware_root),
            "--liquid-class-path",
            str(liquid_root),
            "--output-dir",
            str(output_dir),
            "--skip-liquid-classes",
        ]
    )

    assert rc == 0
    labware_content = (output_dir / "labware.py").read_text(encoding="utf-8")
    init_content = (output_dir / "__init__.py").read_text(encoding="utf-8")

    assert "PLT_CAR_L5MD_A00" in labware_content
    assert "COS_96_RD" in labware_content
    assert "from hamilton_venus.catalog.labware import LABWARE" in init_content


def test_generate_catalog_verify_fails_when_output_is_stale(tmp_path: Path) -> None:
    labware_root = tmp_path / "Labware"
    (labware_root / "Carriers").mkdir(parents=True)
    (labware_root / "Carriers" / "PLT_CAR_L5MD_A00.json").write_text("{}", encoding="utf-8")

    liquid_root = tmp_path / "Liquid Class"
    output_dir = tmp_path / "out"

    generate_catalog_main(
        [
            "--labware-path",
            str(labware_root),
            "--liquid-class-path",
            str(liquid_root),
            "--output-dir",
            str(output_dir),
            "--skip-liquid-classes",
        ]
    )

    (output_dir / "labware.py").write_text("stale", encoding="utf-8")

    with pytest.raises(SystemExit, match="Catalog file is out of date"):
        generate_catalog_main(
            [
                "--labware-path",
                str(labware_root),
                "--liquid-class-path",
                str(liquid_root),
                "--output-dir",
                str(output_dir),
                "--skip-liquid-classes",
                "--verify",
            ]
        )


def test_tools_main_dispatches_generate_catalog(tmp_path: Path) -> None:
    labware_root = tmp_path / "Labware"
    (labware_root / "Carriers").mkdir(parents=True)
    (labware_root / "Carriers" / "PLT_CAR_L5MD_A00.json").write_text("{}", encoding="utf-8")

    output_dir = tmp_path / "out"

    rc = tools_main(
        [
            "generate-catalog",
            "--skip-liquid-classes",
            "--labware-path",
            str(labware_root),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert rc == 0
    assert (output_dir / "labware.py").exists()
    assert (output_dir / "__init__.py").exists()


def test_pull_liquid_classes_uses_all_classes_when_none_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeReturnParameters:
        liquid_class_names: tuple[str, str] = ("LC_1", "LC_2")

    class _FakeClasses:
        return_parameters: _FakeReturnParameters = _FakeReturnParameters()

    class _FakeStarClient:
        def __init__(self, *, simulate: bool, auto_connect: bool = True, logging_level: int | None = None) -> None:
            captured["simulate"] = simulate
            captured["auto_connect"] = auto_connect
            captured["logging_level"] = logging_level

        def __enter__(self) -> _FakeStarClient:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def get_liquid_classes(self) -> _FakeClasses:
            captured["get_called"] = True
            return _FakeClasses()

        def pull_liquid_classes(self, names: list[str]) -> None:
            captured["pulled"] = names

    monkeypatch.setattr("hamilton_venus.StarClient", _FakeStarClient)

    _pull_liquid_classes(logging_level=logging.DEBUG)

    assert captured["simulate"] is True
    assert captured["auto_connect"] is False
    assert captured["logging_level"] is logging.DEBUG
    assert captured["get_called"] is True
    assert captured["pulled"] == ["LC_1", "LC_2"]


class _FakeConnectedClient:
    """A stand-in for an already-connected StarClient/VantageClient, used to verify
    regenerate_catalog() reuses a given client instead of opening a second connection."""

    def __init__(self, names: tuple[str, ...] = ("LC_1",)) -> None:
        self._names = names
        self.get_called = False
        self.pulled: list[str] | None = None

    class _ReturnParameters:
        def __init__(self, names: tuple[str, ...]) -> None:
            self.liquid_class_names = names

    class _Classes:
        def __init__(self, names: tuple[str, ...]) -> None:
            self.return_parameters = _FakeConnectedClient._ReturnParameters(names)

    def get_liquid_classes(self) -> _Classes:
        self.get_called = True
        return _FakeConnectedClient._Classes(self._names)

    def pull_liquid_classes(self, names: list[str]) -> None:
        self.pulled = names


def test_regenerate_catalog_reuses_a_given_client_instead_of_opening_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail_if_constructed(*args: object, **kwargs: object) -> None:
        raise AssertionError("regenerate_catalog should not construct its own StarClient when given one")

    monkeypatch.setattr("hamilton_venus.StarClient", _fail_if_constructed)

    labware_root = tmp_path / "Labware"
    (labware_root / "Carriers").mkdir(parents=True)
    (labware_root / "Carriers" / "PLT_CAR_L5MD_A00.json").write_text("{}", encoding="utf-8")
    liquid_root = tmp_path / "Liquid Class"
    (liquid_root / "STAR").mkdir(parents=True)
    output_dir = tmp_path / "out"

    fake_client = _FakeConnectedClient(names=("LC_1", "LC_2"))
    changed = regenerate_catalog(
        fake_client,
        labware_path=labware_root,
        liquid_class_path=liquid_root,
        output_dir=output_dir,
    )

    assert fake_client.get_called is True
    assert fake_client.pulled == ["LC_1", "LC_2"]
    assert changed["labware.py"] is True
    assert (output_dir / "labware.py").exists()


def test_regenerate_catalog_builds_its_own_star_client_when_none_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class _FakeStarClient(_FakeConnectedClient):
        def __init__(self, *, simulate: bool, auto_connect: bool = True, logging_level: int | None = None) -> None:
            super().__init__()
            captured["simulate"] = simulate
            captured["auto_connect"] = auto_connect

        def __enter__(self) -> _FakeStarClient:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    monkeypatch.setattr("hamilton_venus.StarClient", _FakeStarClient)

    labware_root = tmp_path / "Labware"
    (labware_root / "Carriers").mkdir(parents=True)
    (labware_root / "Carriers" / "PLT_CAR_L5MD_A00.json").write_text("{}", encoding="utf-8")
    liquid_root = tmp_path / "Liquid Class"
    (liquid_root / "STAR").mkdir(parents=True)
    output_dir = tmp_path / "out"

    regenerate_catalog(None, labware_path=labware_root, liquid_class_path=liquid_root, output_dir=output_dir)

    assert captured["simulate"] is True
    assert captured["auto_connect"] is False


def test_generate_catalog_main_instrument_vantage_uses_vantage_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class _FakeVantageClient(_FakeConnectedClient):
        def __init__(self, *, simulate: bool, auto_connect: bool = True, logging_level: int | None = None) -> None:
            super().__init__()
            captured["simulate"] = simulate
            captured["auto_connect"] = auto_connect
            captured["constructed"] = True

        def __enter__(self) -> _FakeVantageClient:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    def _fail_if_star_constructed(*args: object, **kwargs: object) -> None:
        raise AssertionError("--instrument vantage should not construct a StarClient")

    monkeypatch.setattr("hamilton_venus.VantageClient", _FakeVantageClient)
    monkeypatch.setattr("hamilton_venus.StarClient", _fail_if_star_constructed)

    labware_root = tmp_path / "Labware"
    (labware_root / "Carriers").mkdir(parents=True)
    (labware_root / "Carriers" / "PLT_CAR_L5MD_A00.json").write_text("{}", encoding="utf-8")
    liquid_root = tmp_path / "Liquid Class"
    (liquid_root / "STAR").mkdir(parents=True)
    output_dir = tmp_path / "out"

    rc = generate_catalog_main(
        [
            "--instrument",
            "vantage",
            "--labware-path",
            str(labware_root),
            "--liquid-class-path",
            str(liquid_root),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert rc == 0
    assert captured["constructed"] is True
    assert captured["simulate"] is True
    assert captured["auto_connect"] is False


@pytest.mark.parametrize(
    ("detected", "client_attr", "other_attr"),
    [
        ("vantage", "hamilton_venus.VantageClient", "hamilton_venus.StarClient"),
        ("star", "hamilton_venus.StarClient", "hamilton_venus.VantageClient"),
    ],
)
def test_generate_catalog_main_auto_detects_instrument_from_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, detected: str, client_attr: str, other_attr: str
) -> None:
    captured: dict[str, object] = {}

    class _FakeClient(_FakeConnectedClient):
        def __init__(self, *, simulate: bool, auto_connect: bool = True, logging_level: int | None = None) -> None:
            super().__init__()
            captured["simulate"] = simulate
            captured["auto_connect"] = auto_connect

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"auto-detect resolved to {detected!r}; the other client must not be constructed")

    monkeypatch.setattr(
        "hamilton_venus.tools.generate_catalog.detect_instrument_type", lambda: detected
    )
    monkeypatch.setattr(
        "hamilton_venus.tools.generate_catalog.read_instrument_cfg_name",
        lambda: "VStar.cfg" if detected == "vantage" else "ML_STAR.cfg",
    )
    monkeypatch.setattr(client_attr, _FakeClient)
    monkeypatch.setattr(other_attr, _fail)

    labware_root = tmp_path / "Labware"
    (labware_root / "Carriers").mkdir(parents=True)
    (labware_root / "Carriers" / "PLT_CAR_L5MD_A00.json").write_text("{}", encoding="utf-8")
    liquid_root = tmp_path / "Liquid Class"
    (liquid_root / "STAR").mkdir(parents=True)
    output_dir = tmp_path / "out"

    rc = generate_catalog_main(
        [
            "--labware-path",
            str(labware_root),
            "--liquid-class-path",
            str(liquid_root),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert rc == 0
    assert captured["auto_connect"] is False


# -- _load_existing_liquid_tree / cross-instrument merge --------------------------------


def test_load_existing_liquid_tree_returns_empty_dict_when_file_missing(tmp_path: Path) -> None:
    assert _load_existing_liquid_tree(tmp_path / "does_not_exist.py") == {}


def test_load_existing_liquid_tree_round_trips_a_generated_catalog(tmp_path: Path) -> None:
    tree = {
        "STAR": {
            "System": {
                "Channels_1000ul": {
                    "Tip_300ul": {
                        "Water": {
                            "Jet_Empty": ["Water_DispenseJet_Empty"],
                        },
                    },
                },
            },
        },
    }
    content = _render_liquid_class_module("doc", "LIQUID_CLASSES", tree)
    output_path = tmp_path / "liquid_classes.py"
    output_path.write_text(content, encoding="utf-8")

    loaded = _load_existing_liquid_tree(output_path)

    # Re-rendering the round-tripped tree must reproduce byte-identical source --
    # this is the property regenerate_catalog's merge actually relies on to carry
    # another instrument's branch through unchanged.
    assert _render_liquid_class_module("doc", "LIQUID_CLASSES", loaded) == content


def test_load_existing_liquid_tree_warns_and_returns_empty_on_import_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad_path = tmp_path / "liquid_classes.py"
    bad_path.write_text("this is not valid python(((", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        result = _load_existing_liquid_tree(bad_path)

    assert result == {}
    assert "Could not load the existing liquid class catalog" in caplog.text


def test_regenerate_catalog_merges_new_instrument_into_existing_liquid_catalog(tmp_path: Path) -> None:
    """Regenerating on a Vantage-only machine (no STAR folder on disk) must not wipe
    out STAR entries a previous, STAR-only machine's run already committed."""
    labware_root = tmp_path / "Labware"
    (labware_root / "Carriers").mkdir(parents=True)
    (labware_root / "Carriers" / "PLT_CAR_L5MD_A00.json").write_text("{}", encoding="utf-8")
    output_dir = tmp_path / "out"

    star_liquid_root = tmp_path / "star_liquids"
    (star_liquid_root / "STAR").mkdir(parents=True)
    (star_liquid_root / "STAR" / "Water_DispenseJet_Empty.liq").write_text("", encoding="utf-8")
    regenerate_catalog(
        _FakeConnectedClient(names=("Water_DispenseJet_Empty",)),
        labware_path=labware_root,
        liquid_class_path=star_liquid_root,
        output_dir=output_dir,
    )

    vantage_liquid_root = tmp_path / "vantage_liquids"
    (vantage_liquid_root / "VANTAGE").mkdir(parents=True)
    (vantage_liquid_root / "VANTAGE" / "750MC-300Tip-B-Water-W.liq").write_text("", encoding="utf-8")
    regenerate_catalog(
        _FakeConnectedClient(names=("750MC-300Tip-B-Water-W",)),
        labware_path=labware_root,
        liquid_class_path=vantage_liquid_root,
        output_dir=output_dir,
        skip_labware=True,
    )

    content = (output_dir / "liquid_classes.py").read_text(encoding="utf-8")
    assert "STAR" in content
    assert "VANTAGE" in content
    assert "WATER_DISPENSEJET_EMPTY" in content
    assert "750MC_300TIP_B_WATER_W" in content


def test_regenerate_catalog_refreshes_same_instrument_subtree_on_rerun(tmp_path: Path) -> None:
    """The merge must still fully refresh the instrument type being regenerated --
    a class removed on disk since the last run must not linger forever."""
    labware_root = tmp_path / "Labware"
    (labware_root / "Carriers").mkdir(parents=True)
    (labware_root / "Carriers" / "PLT_CAR_L5MD_A00.json").write_text("{}", encoding="utf-8")
    output_dir = tmp_path / "out"
    liquid_root = tmp_path / "liquids"

    (liquid_root / "STAR").mkdir(parents=True)
    (liquid_root / "STAR" / "Old_Class.liq").write_text("", encoding="utf-8")
    regenerate_catalog(
        _FakeConnectedClient(names=("Old_Class",)),
        labware_path=labware_root,
        liquid_class_path=liquid_root,
        output_dir=output_dir,
    )

    (liquid_root / "STAR" / "Old_Class.liq").unlink()
    (liquid_root / "STAR" / "New_Class.liq").write_text("", encoding="utf-8")
    regenerate_catalog(
        _FakeConnectedClient(names=("New_Class",)),
        labware_path=labware_root,
        liquid_class_path=liquid_root,
        output_dir=output_dir,
        skip_labware=True,
    )

    content = (output_dir / "liquid_classes.py").read_text(encoding="utf-8")
    assert "NEW_CLASS" in content
    assert "OLD_CLASS" not in content

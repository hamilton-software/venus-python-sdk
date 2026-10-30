"""Imported labware: the .x / .hxx models a VENUS definition refers to are converted to glTF in
the SDK's Labware\\Models, and the definition is pointed at the .gltf (hamilton_venus.labware_models)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hamilton_venus import labware_models
from hamilton_venus.labware_models import convert_definition_models, find_model_converter, model_references

DEFINITION = {
    "customAttributes": {"hamilton:container_visual": {"modelRef": "Carrier.X"}},
    "containerGrids": {"default": {"containerDefinition": {"customAttributes": {
        "hamilton:container_visual": {"modelRef": "eppendorf_2ml.hxx"}}}}},
    "lid": {"modelRef": "Lid.gltf"},
    "other": [{"modelRef": "eppendorf_2ml.hxx"}],
}


def _fake_convert(source: Path, models_dir: Path, converter: Path) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / f"{source.stem}.bin").write_bytes(b"bin")
    gltf = models_dir / f"{source.stem}.gltf"
    gltf.write_text("{}", encoding="utf-8")
    return gltf


def test_model_references_are_the_venus_formats_only() -> None:
    assert model_references(DEFINITION) == ["Carrier.X", "eppendorf_2ml.hxx"]
    assert model_references({"modelRef": "a.gltf"}) == []


def test_models_are_converted_and_the_definition_points_at_the_gltf(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "venus"
    (source_dir / "deeper").mkdir(parents=True)
    (source_dir / "Carrier.X").write_text("x", encoding="utf-8")
    # Found anywhere below, extension in any case (the stem keeps its case: the converter names the output after it).
    (source_dir / "deeper" / "eppendorf_2ml.HXX").write_text("hxx", encoding="utf-8")
    monkeypatch.setattr(labware_models, "convert_model", _fake_convert)
    models = tmp_path / "Models"

    updated, report = convert_definition_models(
        DEFINITION, source_file=source_dir / "Rack.rck", models_dir=models, converter=Path("conv.exe"),
        search_dirs=[source_dir])

    assert report.converted == ["Carrier.X", "eppendorf_2ml.hxx"]
    assert (models / "Carrier.gltf").is_file() and (models / "eppendorf_2ml.bin").is_file()
    assert updated["customAttributes"]["hamilton:container_visual"]["modelRef"] == "Carrier.gltf"
    assert updated["customAttributes"]["hamilton:container_visual"]["modelFormat"] == "gltf"
    assert updated["other"][0]["modelRef"] == "eppendorf_2ml.gltf"
    assert updated["lid"]["modelRef"] == "Lid.gltf"
    assert "modelFormat" not in updated["lid"]  # a reference that wasn't converted is left alone
    assert DEFINITION["customAttributes"]["hamilton:container_visual"]["modelRef"] == "Carrier.X"  # input untouched

    # Converted already: not converted again.
    _, again = convert_definition_models(DEFINITION, models_dir=models, converter=Path("conv.exe"),
                                         search_dirs=[source_dir])
    assert again.already_present == ["Carrier.X", "eppendorf_2ml.hxx"] and again.converted == []


def test_missing_models_and_a_missing_converter_are_reported(tmp_path, monkeypatch) -> None:
    (tmp_path / "Carrier.X").write_text("x", encoding="utf-8")
    monkeypatch.setattr(labware_models, "find_model_converter", lambda: None)
    updated, report = convert_definition_models(DEFINITION, models_dir=tmp_path / "Models", search_dirs=[tmp_path])
    assert report.missing == ["eppendorf_2ml.hxx"]
    assert "model converter" in report.failed[0]
    assert updated == DEFINITION  # nothing could be converted: references left as they were


def test_converter_may_run_on_a_newer_dotnet(tmp_path, monkeypatch) -> None:
    # Built for .NET 8; VENUS installs .NET 10, which .NET only uses when told it may.
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs["env"])
        _fake_convert(Path(args[1]), Path(args[2]), Path(args[0]))
        return type("Done", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(labware_models.subprocess, "run", fake_run)
    labware_models.convert_model(tmp_path / "Rack.hxx", tmp_path / "Models", Path("conv.exe"))
    assert seen["DOTNET_ROLL_FORWARD"] == "Major"


@pytest.mark.skipif(find_model_converter() is None or not labware_models.venus_labware_path().is_dir(),
                    reason="needs the Labware Converter and a VENUS install")
def test_real_converter_turns_a_venus_model_into_gltf(tmp_path) -> None:
    source = next(labware_models.venus_labware_path().rglob("*.hxx"), None)
    if source is None:
        pytest.skip("no .hxx model in the VENUS Labware folder")
    gltf = labware_models.convert_model(source, tmp_path, find_model_converter())
    assert gltf.is_file() and gltf.with_suffix(".bin").is_file()

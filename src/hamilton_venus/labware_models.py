"""3D models of imported labware: convert VENUS's ``.x`` / ``.hxx`` models to glTF.

A definition imported from a VENUS ``.rck`` file (``labware.importLabwareDefinition``) keeps
its model references as VENUS has them, e.g. ``"modelRef": "eppendorf_2ml.hxx"``. The SDK's own
definitions refer to glTF models (``.gltf`` + ``.bin``) kept in ``<SDK>\\Labware\\Models``, the
registered SDK folder's ``Labware\\Models``. This module finds each referenced ``.x`` / ``.hxx``
file (next to the imported file, else anywhere under VENUS's own Labware folder), converts it
there with the LabwareConverter's model converter (``Hamilton.ModelConversion.Cli.exe``, Assimp)
and points the reference at the ``.gltf``.
"""

from __future__ import annotations

import copy
import logging
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from hamilton_venus._internal._sdk_paths import get_sdk_labware_path
from hamilton_venus.models.command_types import ModelConversionReport

_logger = logging.getLogger(__name__)

MODEL_EXTENSIONS = (".x", ".hxx")
MODEL_REF_KEY = "modelRef"
MODEL_FORMAT_KEY = "modelFormat"
CONVERTER_EXE = "Hamilton.ModelConversion.Cli.exe"
CONVERTER_ENV = "HAMILTON_MODEL_CONVERTER"
VENUS_LABWARE_REGISTRY_KEY = r"SOFTWARE\WOW6432Node\Phoenix\Directories\Labware"
DEFAULT_VENUS_LABWARE_PATH = Path(r"C:\Program Files (x86)\HAMILTON\Labware")
CONVERT_TIMEOUT_S = 180


def sdk_models_path() -> Path:
    """``<registered SDK folder>\\Labware\\Models``."""
    return get_sdk_labware_path() / "Models"


def venus_labware_path() -> Path:
    """VENUS's own Labware folder (registry ``Phoenix\\Directories\\Labware``)."""
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, VENUS_LABWARE_REGISTRY_KEY) as key:
                value, _ = winreg.QueryValueEx(key, "")
            if isinstance(value, str) and value.strip():
                return Path(value.strip())
        except (ImportError, OSError, ValueError):
            pass
    return DEFAULT_VENUS_LABWARE_PATH


def find_model_converter() -> Path | None:
    """The LabwareConverter's model converter: ``HAMILTON_MODEL_CONVERTER``, else the
    ``LabwareConverter\\ModelConverter`` folder the installer puts next to the SDK's ``src``."""
    configured = os.environ.get(CONVERTER_ENV, "").strip()
    candidates = [Path(configured)] if configured else []
    root = Path(__file__).resolve().parents[2]  # <SDK root>\src\hamilton_venus\labware_models.py
    candidates.append(root / "LabwareConverter" / "ModelConverter" / CONVERTER_EXE)
    return next((c for c in candidates if c.is_file()), None)


def _walk(node: Any, found: list[tuple[dict[str, Any], str]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == MODEL_REF_KEY and isinstance(value, str) and value.lower().endswith(MODEL_EXTENSIONS):
                found.append((node, key))
            else:
                _walk(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk(item, found)


def model_references(definition: dict[str, Any]) -> list[str]:
    """Every ``.x`` / ``.hxx`` model a definition refers to (each once)."""
    found: list[tuple[dict[str, Any], str]] = []
    _walk(definition, found)
    return list(dict.fromkeys(node[key] for node, key in found))


@lru_cache(maxsize=8)
def _model_index(root: str) -> dict[str, str]:
    """Model files under *root*, by lower-case file name."""
    index: dict[str, str] = {}
    base = Path(root)
    if base.is_dir():
        for path in base.rglob("*"):
            if path.suffix.lower() in MODEL_EXTENSIONS:
                index.setdefault(path.name.lower(), str(path))
    return index


def find_model_file(reference: str, search_dirs: list[Path]) -> Path | None:
    """The file *reference* names: as given if it is a path, then in each of *search_dirs*
    directly, then anywhere under them."""
    ref = Path(reference)
    if ref.is_absolute() and ref.is_file():
        return ref
    for directory in search_dirs:
        direct = directory / ref
        if direct.is_file():
            return direct
    for directory in search_dirs:
        hit = _model_index(str(directory)).get(ref.name.lower())
        if hit:
            return Path(hit)
    return None


def convert_model(source: Path, models_dir: Path, converter: Path) -> Path:
    """Convert one model to ``<models_dir>\\<name>.gltf`` (+ ``.bin``); returns the ``.gltf``."""
    models_dir.mkdir(parents=True, exist_ok=True)
    # The converter targets .NET 8; VENUS installs .NET 10. Roll forward to the next major
    # runtime when 8 isn't there (by default .NET only rolls forward within the same major).
    env = {**os.environ, "DOTNET_ROLL_FORWARD": "Major"}
    result = subprocess.run(
        [str(converter), str(source), str(models_dir)],
        capture_output=True, text=True, timeout=CONVERT_TIMEOUT_S, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    gltf = models_dir / f"{source.stem}.gltf"
    if result.returncode != 0 or not gltf.is_file():
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else f"exit code {result.returncode}")
    return gltf


def convert_definition_models(
    definition: dict[str, Any],
    *,
    source_file: str | Path | None = None,
    models_dir: Path | None = None,
    converter: Path | None = None,
    search_dirs: list[Path] | None = None,
    overwrite: bool = False,
) -> tuple[dict[str, Any], ModelConversionReport]:
    """Convert the ``.x`` / ``.hxx`` models *definition* refers to and return (a copy of the
    definition referring to the ``.gltf`` models, the report). A reference whose model could
    not be found or converted is left as it was."""
    models_dir = models_dir or sdk_models_path()
    report = ModelConversionReport(models_path=str(models_dir))
    updated = copy.deepcopy(definition)
    found: list[tuple[dict[str, Any], str]] = []
    _walk(updated, found)
    if not found:
        return updated, report
    converter = converter or find_model_converter()
    dirs = list(search_dirs or [])
    if source_file:
        dirs.insert(0, Path(source_file).parent)
    if not search_dirs:
        dirs.append(venus_labware_path())
    done: dict[str, str | None] = {}  # reference -> new .gltf name (None: left as it was)
    for node, key in found:
        reference = node[key]
        if reference not in done:
            done[reference] = _convert_one(reference, dirs, models_dir, converter, overwrite, report)
        if done[reference]:
            node[key] = done[reference]
            node[MODEL_FORMAT_KEY] = "gltf"  # as the SDK's own definitions have it, next to modelRef
    return updated, report


def _convert_one(reference: str, dirs: list[Path], models_dir: Path, converter: Path | None,
                 overwrite: bool, report: ModelConversionReport) -> str | None:
    gltf_name = f"{Path(reference).stem}.gltf"
    if not overwrite and (models_dir / gltf_name).is_file() and (models_dir / f"{Path(reference).stem}.bin").is_file():
        report.already_present.append(reference)
        return gltf_name
    source = find_model_file(reference, dirs)
    if source is None:
        report.missing.append(reference)
        return None
    if converter is None:
        report.failed.append(f"{reference}: the model converter ({CONVERTER_EXE}) was not found; "
                             f"install the Labware Converter or set {CONVERTER_ENV}")
        return None
    try:
        convert_model(source, models_dir, converter)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        report.failed.append(f"{reference}: {exc}")
        return None
    _logger.info("Converted model %s -> %s", source, models_dir / gltf_name)
    report.converted.append(reference)
    return gltf_name

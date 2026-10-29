from __future__ import annotations

import argparse
import importlib.util
import keyword
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from hamilton_venus._internal._sdk_paths import (
    detect_instrument_type,
    get_sdk_labware_path,
    get_sdk_liquid_class_path,
    read_instrument_cfg_name,
)
from hamilton_venus.catalog._base import _FolderNamespace

if TYPE_CHECKING:
    from hamilton_venus.models import CommandResponse, LiquidClassesResponse

logger = logging.getLogger(__name__)


class _LiquidClassSource(Protocol):
    """Minimal interface for pulling liquid classes from a connected instrument client.

    Satisfied structurally by both ``StarClient`` and ``VantageClient``.
    """

    def get_liquid_classes(self) -> LiquidClassesResponse: ...

    def pull_liquid_classes(self, names: list[str]) -> CommandResponse: ...


def _default_labware_path() -> Path:
    return get_sdk_labware_path()


def _default_liquid_class_path() -> Path:
    return get_sdk_liquid_class_path()


def _default_output_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "catalog"


def _sanitize_identifier(value: str) -> str:
    result = re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_").upper()
    result = re.sub(r"_+", "_", result)
    if not result:
        raise ValueError(f"Cannot create Python identifier from {value!r}")
    if result[0].isdigit():
        result = f"N_{result}"
    if keyword.iskeyword(result.lower()):
        result = f"{result}_"
    return result


def _collect_labware(labware_root: Path) -> dict[str, list[str]]:
    if not labware_root.exists():
        raise FileNotFoundError(f"Labware path not found: {labware_root}")
    logger.debug(f"Scanning labware path: {labware_root}")
    categories: dict[str, set[str]] = {}
    for file_path in sorted(labware_root.rglob("*.json")):
        rel = file_path.relative_to(labware_root)
        if len(rel.parts) < 2:
            logger.debug(f"Skipping uncategorized labware file: {rel}")
            continue
        # VENUS stores labware as <scope>/<category>/<name>.json, so the immediate
        # parent is the category and System/User scopes share one namespace.
        category = rel.parts[-2]
        categories.setdefault(category, set()).add(file_path.stem)
    result = {k: sorted(v, key=str.casefold) for k, v in sorted(categories.items(), key=lambda x: x[0].casefold())}
    total_labware = sum(len(items) for items in result.values())
    logger.debug(f"Found {len(result)} labware categories with {total_labware} total items")
    return result


def _collect_liquid_classes(liquid_root: Path) -> dict[str, Any]:
    """Collect liquid classes into a nested folder tree.

    The new ML_API folder layout organises classes as::

        <instrument>/<pipettingDevice>/<tipType>/<liquid>/<dispenseMode>/<ClassName>.json

    This produces a recursive ``dict`` where interior nodes are
    ``dict[str, ...]`` and leaves are ``list[str]`` (sorted file stems).
    Files sitting directly in the root (no sub-folder) are grouped under
    a synthetic ``"STAR"`` key for backward compatibility.
    """
    if not liquid_root.exists():
        raise FileNotFoundError(f"Liquid class path not found: {liquid_root}")
    logger.debug(f"Scanning liquid classes path: {liquid_root}")

    root: dict[str, Any] = {}
    for path in sorted(liquid_root.rglob("*"), key=lambda p: str(p).casefold()):
        if not path.is_file() or path.suffix.lower() in {".tmp", ".bak"}:
            continue
        rel = path.relative_to(liquid_root)
        folder_parts = rel.parts[:-1]
        stem = path.stem

        if not folder_parts:
            root.setdefault("__files__", []).append(stem)
            continue

        node = root
        for part in folder_parts:
            node = node.setdefault(part, {})
        node.setdefault("__files__", []).append(stem)

    def _finalize(node: dict[str, Any]) -> dict[str, Any] | list[str]:
        files: list[str] = sorted(node.pop("__files__", []), key=str.casefold)
        children = {k: _finalize(v) for k, v in sorted(node.items(), key=lambda x: x[0].casefold())}
        if not children:
            return files
        if files:
            children["__files__"] = files
        return children

    tree = _finalize(root)

    def _count_leaves(node: dict[str, Any] | list[str]) -> int:
        if isinstance(node, list):
            return len(node)
        return sum(_count_leaves(v) for v in node.values())

    total = _count_leaves(tree) if isinstance(tree, dict) else len(tree)
    logger.debug(f"Found {total} liquid classes in nested folder tree")
    return tree if isinstance(tree, dict) else {"STAR": tree}


def _load_existing_liquid_tree(path: Path) -> dict[str, Any]:
    """Reconstruct the nested folder tree from an already-generated ``liquid_classes.py``.

    Each machine's local VENUS install only ever has one instrument type's ``Liquid
    Class`` folder populated (a STAR install has no ``VANTAGE`` folder and vice versa --
    see ``_collect_liquid_classes``'s ``<instrument>/...`` layout), so a fresh scan on
    any one machine can only ever produce ONE top-level instrument key. Without this,
    ``regenerate_catalog`` would overwrite the whole file with just that one instrument's
    entries every time, silently dropping whichever other instrument type's classes a
    *different* machine had previously captured into the committed catalog. This is
    reconstructed by importing the existing file and walking its already-built
    ``_FolderNamespace`` tree back into the same ``dict[str, Any]`` shape
    ``_collect_liquid_classes`` produces, keyed by the (already-sanitized) class
    attribute names rather than the original on-disk folder names -- round-trip safe
    for any branch the caller merges back in unchanged, because ``_sanitize_identifier``
    is idempotent on its own output (re-sanitizing an already-sanitized identifier is a
    no-op), so re-rendering that branch reproduces the exact same source text.

    Returns ``{}`` if *path* doesn't exist yet (first-ever generation) or can't be
    imported (logged as a warning -- the merge then falls back to "start fresh" for
    every instrument type, same as the old always-overwrite behavior, rather than
    raising and blocking catalog generation over a stale/corrupted file).
    """
    if not path.exists():
        return {}
    try:
        spec = importlib.util.spec_from_file_location("_existing_liquid_classes_catalog", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not build a module spec for {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        root = module.LIQUID_CLASSES
    except Exception as exc:
        logger.warning(
            f"Could not load the existing liquid class catalog at {path} to merge with it ({exc}) -- "
            "regenerating from this machine's scan only. This will drop any liquid classes that are "
            "only present in the existing file (e.g. from a different instrument type)."
        )
        return {}

    def _walk(namespace: _FolderNamespace) -> dict[str, Any] | list[str]:
        names = sorted(n for n in vars(type(namespace)) if not n.startswith("_"))
        values = [getattr(namespace, n) for n in names]
        if all(isinstance(v, str) for v in values):
            return list(values)
        return {name: _walk(value) for name, value in zip(names, values, strict=True)}

    tree = _walk(root)
    return tree if isinstance(tree, dict) else {}


def _assert_no_collisions(scope: str, names: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name in names:
        identifier = _sanitize_identifier(name)
        existing = mapping.get(identifier)
        if existing is not None and existing != name:
            raise ValueError(
                f"Identifier collision in {scope}: {existing!r} and {name!r} both map to {identifier!r}"
            )
        mapping[identifier] = name
    return mapping


def _build_lookup(scope: str, entries: dict[str, str]) -> dict[str, str]:
    """Build a casefolded, case-insensitive lookup table.

    *entries* maps Python identifiers to their canonical raw names. Each
    identifier and canonical value is added as a casefolded key. Raises if
    two different canonical values would casefold to the same key, which
    would otherwise be silently and ambiguously shadowed at lookup time.
    """
    lookup: dict[str, str] = {}
    for identifier, raw_name in entries.items():
        for key in (identifier, raw_name):
            folded = key.casefold()
            existing = lookup.get(folded)
            if existing is not None and existing != raw_name:
                raise ValueError(
                    f"Case-insensitive lookup collision in {scope}: {folded!r} maps to both "
                    f"{existing!r} and {raw_name!r}"
                )
            lookup[folded] = raw_name
    return lookup


def _merge_lookups(scope: str, lookups: list[dict[str, str]]) -> dict[str, str]:
    """Merge already-casefolded lookup tables, raising on ambiguous collisions."""
    merged: dict[str, str] = {}
    for lookup in lookups:
        for folded, raw_name in lookup.items():
            existing = merged.get(folded)
            if existing is not None and existing != raw_name:
                raise ValueError(
                    f"Case-insensitive lookup collision in {scope}: {folded!r} maps to both "
                    f"{existing!r} and {raw_name!r}"
                )
            merged[folded] = raw_name
    return merged


def _render_lookup(indent: str, lookup: dict[str, str]) -> list[str]:
    if not lookup:
        return [f"{indent}_LOOKUP: ClassVar[dict[str, str]] = {{}}"]
    lines = [f"{indent}_LOOKUP: ClassVar[dict[str, str]] = {{"]
    for folded, raw_name in sorted(lookup.items()):
        lines.append(f"{indent}    {folded!r}: {raw_name!r},")
    lines.append(f"{indent}}}")
    return lines


def _to_class_name(identifier: str) -> str:
    """Convert a sanitized identifier (or an underscore-joined path of them, for a nested
    tree's accumulated prefix) into a private class name.

    Underscore boundaries between parts are preserved rather than concatenated away: joining
    "GLYCERIN80" (one part) and "GLYCERIN_80" (two parts, i.e. two sibling folders "Glycerin80"
    and "Glycerin_80%" a few levels up) without a separator both produce "Glycerin80", so two
    genuinely different tree nodes would render the same Python class name and one would
    silently shadow the other at module-exec time -- keeping the separator makes this
    injective with respect to the sequence of per-level identifiers.
    """
    return "_" + "_".join(part[:1] + part[1:].lower() for part in identifier.split("_") if part)


def _render_module(module_doc: str, root_object_name: str, groups: dict[str, list[str]]) -> str:
    group_identifier_map = _assert_no_collisions(f"{root_object_name}.groups", list(groups.keys()))
    lines: list[str] = [
        f'"""{module_doc}"""',
        "",
        "from typing import ClassVar",
        "",
        "from hamilton_venus.catalog._base import _CatalogNamespace",
        "",
        "",
    ]

    rendered_groups: list[tuple[str, str, str]] = []
    group_lookups: list[dict[str, str]] = []
    for group_name in sorted(groups, key=str.casefold):
        group_identifier = _sanitize_identifier(group_name)
        constants = groups[group_name]
        constant_map = _assert_no_collisions(f"{root_object_name}.{group_name}", constants)
        group_lookup = _build_lookup(f"{root_object_name}.{group_name}", constant_map)
        group_lookups.append(group_lookup)
        class_name = _to_class_name(group_identifier)
        rendered_groups.append((group_identifier, class_name, group_name))
        lines.append(f"class {class_name}(_CatalogNamespace):")
        if not constant_map:
            lines.append("    pass")
        else:
            for identifier, raw_name in sorted(constant_map.items(), key=lambda x: x[0].casefold()):
                lines.append(f"    {identifier}: str = {raw_name!r}")
            lines.append("")
            lines.extend(_render_lookup("    ", group_lookup))
        lines.append("")

    root_lookup = _merge_lookups(root_object_name, group_lookups)
    root_class_name = _to_class_name(root_object_name)
    lines.append(f"class {root_class_name}(_CatalogNamespace):")
    for group_identifier, class_name, _ in sorted(rendered_groups, key=lambda x: x[0].casefold()):
        lines.append(f"    {group_identifier}: {class_name} = {class_name}()")
    if not rendered_groups:
        lines.append("    pass")
    else:
        lines.append("")
        lines.extend(_render_lookup("    ", root_lookup))
    lines.append("")
    lines.append(f"{root_object_name}: {root_class_name} = {root_class_name}()")
    lines.append("")
    lines.append(f"__all__ = [{root_object_name!r}]")
    lines.append("")
    group_exports = [group for group, _, _ in sorted(rendered_groups, key=lambda x: x[0].casefold())]
    if set(group_identifier_map) != set(group_exports):
        raise RuntimeError("Internal rendering error")
    return "\n".join(lines)


def _render_liquid_class_module(module_doc: str, root_object_name: str, tree: dict[str, Any]) -> str:
    """Render a liquid class catalog module from a nested folder tree.

    Supports the ML_API folder hierarchy::

        <instrument>/<pipettingDevice>/<tipType>/<liquid>/<dispenseMode>/<name>

    Each level becomes a nested ``_FolderNamespace`` sub-class with direct
    string and sub-namespace attributes -- no lookup dict, deliberately (see
    ``catalog/_base.py``'s module docstring for why liquid classes don't get
    the same flat, name-only lookup ``LABWARE`` does: tip type, pipetting
    device, and dispense mode are load-bearing parts of a liquid class's
    identity, and a flat lookup would silently discard them). Callers
    navigate purely via dot access::

        LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL_FILTER.WATER.SURFACE_EMPTY.MY_CLASS

    Collision detection on each folder level's own leaf names is applied at
    generation time (``_assert_no_collisions``) so ambiguous names (two files
    that differ only by case) are caught early. Sibling *folder* names that
    sanitize to the same identifier (e.g. two real, different folders named
    "Glycerin80" and "Glycerin_80%") are disambiguated with a numeric suffix
    (logged as a warning) rather than one silently shadowing the other --
    unlike a leaf-name collision, there's no single obviously-correct raw
    name to prefer, so this doesn't raise.
    """
    lines: list[str] = [
        f'"""{module_doc}"""',
        "",
        "from hamilton_venus.catalog._base import _FolderNamespace",
        "",
        "",
    ]
    class_blocks: list[str] = []

    def _visit(node: dict[str, Any] | list[str], prefix: str, scope: str) -> str:
        """DFS visitor. Returns the generated class name."""
        class_name = _to_class_name(prefix) if prefix else _to_class_name(root_object_name)
        block: list[str] = [f"class {class_name}(_FolderNamespace):"]

        if isinstance(node, list):
            constant_map = _assert_no_collisions(scope, node)
            for ident, raw in sorted(constant_map.items(), key=lambda x: x[0].casefold()):
                block.append(f"    {ident}: str = {raw!r}")
        else:
            child_specs: list[tuple[str, str]] = []
            seen_identifiers: set[str] = set()
            for key, child in sorted(node.items(), key=lambda x: x[0].casefold()):
                identifier = _sanitize_identifier(key)
                if identifier.casefold() in seen_identifiers:
                    # Two sibling folders that are genuinely different on disk (e.g. "Glycerin80"
                    # vs "Glycerin_80%") can sanitize to the same identifier -- silently colliding
                    # would make one folder's whole subtree unreachable (or worse, make the
                    # colliding attribute resolve to the WRONG folder's classes with no error at
                    # all). Disambiguate with a numeric suffix instead of losing/misrouting a
                    # real, distinct folder.
                    suffix = 2
                    while f"{identifier}_{suffix}".casefold() in seen_identifiers:
                        suffix += 1
                    logger.warning(
                        f"Sibling identifier collision in {scope}: {key!r} sanitizes to "
                        f"{identifier!r}, already used by another folder at this level -- "
                        f"renamed to {identifier}_{suffix!r}"
                    )
                    identifier = f"{identifier}_{suffix}"
                seen_identifiers.add(identifier.casefold())
                child_prefix = f"{prefix}_{identifier}" if prefix else identifier
                child_class_name = _visit(child, child_prefix, f"{scope}.{key}")
                child_specs.append((identifier, child_class_name))
            for ident, child_cls in sorted(child_specs, key=lambda x: x[0].casefold()):
                block.append(f"    {ident}: {child_cls} = {child_cls}()")

        if len(block) == 1:
            block.append("    pass")

        class_blocks.append("\n".join(block))
        return class_name

    root_class_name = _visit(tree, "", root_object_name)

    for block in class_blocks:
        lines.append(block)
        lines.append("")
    lines.append(f"{root_object_name}: {root_class_name} = {root_class_name}()")
    lines.append("")
    lines.append(f"__all__ = [{root_object_name!r}]")
    lines.append("")
    return "\n".join(lines)


def _render_catalog_init() -> str:
    return "\n".join(
        [
            '"""Static catalog exports for labware and liquid classes."""',
            "",
            "from hamilton_venus.catalog.labware import LABWARE",
            "from hamilton_venus.catalog.liquid_classes import LIQUID_CLASSES",
            "",
            '__all__ = ["LABWARE", "LIQUID_CLASSES"]',
            "",
        ]
    )


def _write_or_verify(path: Path, content: str, verify: bool) -> bool:
    normalized_content = content.replace("\r\n", "\n")
    current = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None
    if current == normalized_content:
        logger.debug(f"Catalog file is up to date: {path}")
        return False
    if verify:
        raise SystemExit(f"Catalog file is out of date: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized_content, encoding="utf-8")
    logger.debug(f"Wrote catalog file: {path}")
    return True


def _pull_liquid_classes_via(client: _LiquidClassSource) -> None:
    names_to_pull = list(client.get_liquid_classes().return_parameters.liquid_class_names)
    if not names_to_pull:
        logger.debug("No liquid classes to pull")
        return
    logger.debug(f"Pulling {len(names_to_pull)} liquid classes")
    client.pull_liquid_classes(names_to_pull)
    logger.debug(f"Successfully pulled {len(names_to_pull)} liquid classes")


def _pull_liquid_classes(client: _LiquidClassSource | None = None, *, logging_level: int | None = None) -> None:
    logger.debug("Pulling liquid classes from VENUS")
    if client is not None:
        _pull_liquid_classes_via(client)
        return
    from hamilton_venus import StarClient

    # No hardware needed -- ``liquidClass.*`` are ``System``-category commands that
    # only need the VENUS runtime, so this never connects to an instrument.
    with StarClient(simulate=True, auto_connect=False, logging_level=logging_level) as star:
        _pull_liquid_classes_via(star)


def _make_catalog_client(instrument: str, logging_level: int | None) -> Any:
    """A throwaway simulated client used only to pull liquid classes for catalog
    generation.

    ``instrument`` is ``"star"`` or ``"vantage"``: STAR -> :class:`StarClient`,
    Vantage -> :class:`VantageClient`. It never connects to an instrument
    (``auto_connect=False``) -- pulling liquid classes is a ``System``-category
    command that needs the VENUS runtime, not hardware.
    """
    if instrument == "vantage":
        from hamilton_venus import VantageClient

        return VantageClient(simulate=True, auto_connect=False, logging_level=logging_level)
    from hamilton_venus import StarClient

    return StarClient(simulate=True, auto_connect=False, logging_level=logging_level)


def regenerate_catalog(
    client: _LiquidClassSource | None = None,
    *,
    labware_path: Path | None = None,
    liquid_class_path: Path | None = None,
    output_dir: Path | None = None,
    skip_labware: bool = False,
    skip_liquid_classes: bool = False,
    verify: bool = False,
) -> dict[str, bool]:
    """Regenerate ``catalog/labware.py``/``liquid_classes.py``/``__init__.py`` from this
    machine's local VENUS install (``get_sdk_labware_path()``/``get_sdk_liquid_class_path()``).

    When *client* is an already-connected :class:`~hamilton_venus.StarClient` or
    :class:`~hamilton_venus.VantageClient`, it's reused to pull liquid classes instead of
    opening a second, redundant VENUS connection -- e.g. an MCP session's or a demo app's
    already-running client. When *client* is ``None`` (the CLI's default), a throwaway
    simulated ``StarClient`` is created and torn down just for the pull.

    Liquid classes are collected into a nested folder tree (the ML_API layout,
    ``<instrument>/<pipettingDevice>/<tipType>/<liquid>/<dispenseMode>/<name>``) and
    rendered as nested ``_FolderNamespace`` sub-classes -- see ``_render_liquid_class_module``.
    This machine's scan only ever covers ONE top-level instrument key (a STAR install has
    no ``VANTAGE`` folder on disk and vice versa), so it's merged on top of whatever the
    existing ``liquid_classes.py`` already has via :func:`_load_existing_liquid_tree`
    rather than overwriting the file outright -- that instrument's own branch is fully
    refreshed (anything no longer on disk is dropped), while any other instrument type's
    branch, only ever captured by a *different* machine, is carried over unchanged.

    Returns which of the three output files actually changed, keyed by filename.
    """
    resolved_labware_path = labware_path or _default_labware_path()
    resolved_liquid_class_path = liquid_class_path or _default_liquid_class_path()
    resolved_output_dir = (output_dir or _default_output_dir()).resolve()

    if not skip_liquid_classes:
        _pull_liquid_classes(client)

    changed: dict[str, bool] = {}

    if not skip_labware:
        labware_groups = _collect_labware(resolved_labware_path.resolve())
        labware_content = _render_module("Generated static labware catalog.", "LABWARE", labware_groups)
        changed["labware.py"] = _write_or_verify(resolved_output_dir / "labware.py", labware_content, verify)

    if not skip_liquid_classes:
        liquid_classes_path = resolved_output_dir / "liquid_classes.py"
        scanned_tree = _collect_liquid_classes(resolved_liquid_class_path.resolve())
        existing_tree = _load_existing_liquid_tree(liquid_classes_path)
        # Top-level-only merge: each key is an instrument type (STAR/VANTAGE), so this
        # instrument's branch is fully replaced by this run's fresh scan while every
        # other instrument's branch -- absent from scanned_tree entirely, since this
        # machine has no folder for it -- passes through from existing_tree untouched.
        merged_tree = {**existing_tree, **scanned_tree}
        liquid_content = _render_liquid_class_module(
            "Generated static liquid class catalog.", "LIQUID_CLASSES", merged_tree
        )
        changed["liquid_classes.py"] = _write_or_verify(liquid_classes_path, liquid_content, verify)

    changed["__init__.py"] = _write_or_verify(resolved_output_dir / "__init__.py", _render_catalog_init(), verify)
    return changed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate static labware and liquid class catalogs")
    parser.add_argument("--labware-path", type=Path, default=_default_labware_path())
    parser.add_argument("--liquid-class-path", type=Path, default=_default_liquid_class_path())
    parser.add_argument("--output-dir", type=Path, default=_default_output_dir())
    parser.add_argument("--skip-labware", action="store_true")
    parser.add_argument("--skip-liquid-classes", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging when pulling liquid classes")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument(
        "--instrument",
        choices=["star", "vantage"],
        default=None,
        help=(
            "Which instrument client to use when pulling liquid classes. "
            "Default: auto-detect from the VENUS instrument-config registry "
            "(InstCfgFile=VStar.cfg -> vantage, anything else -> star)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")

    logger.debug("Catalog generation started")
    logger.debug(f"  Labware path: {args.labware_path}")
    logger.debug(f"  Liquid class path: {args.liquid_class_path}")
    logger.debug(f"  Output directory: {args.output_dir}")
    logger.debug(f"  Skip labware: {args.skip_labware}")
    logger.debug(f"  Skip liquid classes: {args.skip_liquid_classes}")
    logger.debug(f"  Instrument: {args.instrument}")

    logging_level = logging.DEBUG if args.debug else None
    kwargs: dict[str, Any] = {
        "labware_path": args.labware_path,
        "liquid_class_path": args.liquid_class_path,
        "output_dir": args.output_dir,
        "skip_labware": args.skip_labware,
        "skip_liquid_classes": args.skip_liquid_classes,
        "verify": args.verify,
    }

    if args.skip_liquid_classes:
        # Labware is read straight off disk -- no VENUS client needed.
        changed = regenerate_catalog(None, **kwargs)
    else:
        instrument = args.instrument
        if instrument is None:
            cfg_name = read_instrument_cfg_name()
            instrument = detect_instrument_type()
            if cfg_name:
                logger.info(
                    "Auto-detected instrument type %r from the VENUS registry (InstCfgFile=%r)",
                    instrument,
                    cfg_name,
                )
            else:
                logger.info(
                    "No VENUS instrument config found in the registry; assuming instrument type %r",
                    instrument,
                )
        else:
            logger.debug("Using instrument type %r (from --instrument)", instrument)
        with _make_catalog_client(instrument, logging_level) as client:
            changed = regenerate_catalog(client, **kwargs)

    if any(changed.values()):
        print(f"Catalog generated in {args.output_dir.resolve()}")
    else:
        print("Catalog is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

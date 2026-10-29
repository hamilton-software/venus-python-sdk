from __future__ import annotations

import re
from pathlib import Path

import pytest

from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
from hamilton_venus.catalog._base import _CatalogNamespace, _FolderNamespace

_CANONICAL_LABWARE = "SMP_CAR_24_15x75"

# A real liquid class present in the committed catalog. Sibling-folder collision handling
# (e.g. "Glycerin80" vs "Glycerin_80%") is covered by tests/unit/tools/test_generate_catalog.py.
_CANONICAL_LIQUID_PATH = ("STAR", "SYSTEM", "CHANNELS_1000UL", "TIP_300UL", "GLYCERIN_80", "SURFACE_EMPTY")
_CANONICAL_LIQUID_LEAF = "X1_300TIP_B_GLYCERIN80_S_E"
_CANONICAL_LIQUID_VALUE = "X1-300Tip-B-Glycerin80-S-E"


class TestCatalogCaseInsensitiveLookup:
    """LABWARE only -- it's the one catalog namespace with a name-only, case-insensitive
    ``_CatalogNamespace`` lookup. LIQUID_CLASSES deliberately doesn't have one; see
    TestLiquidClassFolderNamespace below and catalog/_base.py's module docstring for why.
    """

    @pytest.mark.parametrize(
        "key",
        [
            "SMP_CAR_24_15x75",
            "SMP_CAR_24_15X75",
            "smp_car_24_15x75",
            "sMp_CaR_24_15X75",
        ],
    )
    def test_labware_getitem_is_case_insensitive(self, key: str) -> None:
        assert LABWARE[key] == _CANONICAL_LABWARE

    def test_lookup_by_attribute_identifier(self) -> None:
        # The Python identifier (uppercase 'X') also resolves to the canonical value.
        assert LABWARE["SMP_CAR_24_15X75"] == _CANONICAL_LABWARE

    def test_category_level_lookup(self) -> None:
        assert LABWARE.TUBE_RACK["smp_car_24_15x75"] == _CANONICAL_LABWARE

    def test_contains_is_case_insensitive(self) -> None:
        assert "smp_car_24_15x75" in LABWARE
        assert 123 not in LABWARE
        assert "does-not-exist" not in LABWARE

    def test_get_returns_default_when_missing(self) -> None:
        assert LABWARE.get("does-not-exist") is None
        assert LABWARE.get("does-not-exist", "fallback") == "fallback"
        assert LABWARE.get(123, "fallback") == "fallback"

    def test_get_resolves_case_insensitively(self) -> None:
        assert LABWARE.get("smp_car_24_15X75") == _CANONICAL_LABWARE

    def test_getitem_raises_keyerror_for_unknown(self) -> None:
        with pytest.raises(KeyError):
            LABWARE["does-not-exist"]

    def test_getitem_raises_keyerror_for_non_string(self) -> None:
        with pytest.raises(KeyError):
            LABWARE[123]  # type: ignore[index]

    def test_iter_yields_canonical_values(self) -> None:
        values = list(LABWARE)
        assert _CANONICAL_LABWARE in values
        assert all(isinstance(v, str) for v in values)
        # Iteration should not yield duplicates.
        assert len(values) == len(set(values))

    def test_catalog_objects_are_namespaces(self) -> None:
        assert isinstance(LABWARE, _CatalogNamespace)
        assert isinstance(LABWARE.TUBE_RACK, _CatalogNamespace)


class TestLiquidClassFolderNamespace:
    """LIQUID_CLASSES uses _FolderNamespace: pure dot access mirroring the ML_API folder
    tree, no bracket/name-only lookup -- see catalog/_base.py's module docstring for why."""

    def test_full_path_resolves(self) -> None:
        node = LIQUID_CLASSES
        for part in _CANONICAL_LIQUID_PATH:
            node = getattr(node, part)
        assert getattr(node, _CANONICAL_LIQUID_LEAF) == _CANONICAL_LIQUID_VALUE

    def test_leading_type_folder_is_bypassable(self) -> None:
        # Skipping "STAR" resolves the same way.
        node = LIQUID_CLASSES
        for part in _CANONICAL_LIQUID_PATH[1:]:
            node = getattr(node, part)
        assert getattr(node, _CANONICAL_LIQUID_LEAF) == _CANONICAL_LIQUID_VALUE

    def test_leaf_name_is_reachable_directly_off_root(self) -> None:
        assert getattr(LIQUID_CLASSES, _CANONICAL_LIQUID_LEAF) == _CANONICAL_LIQUID_VALUE

    def test_unknown_attribute_raises(self) -> None:
        with pytest.raises(AttributeError):
            _ = LIQUID_CLASSES.DOES_NOT_EXIST_ANYWHERE_IN_THIS_TREE

    def test_iter_and_contains(self) -> None:
        # __iter__/__contains__ only yield this namespace's own direct string attrs, not
        # nested sub-namespaces -- exercise them at the level that actually holds the leaf.
        surface_empty = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.GLYCERIN_80.SURFACE_EMPTY
        assert _CANONICAL_LIQUID_VALUE in surface_empty
        assert _CANONICAL_LIQUID_VALUE in list(surface_empty)

    def test_all_values_recurses_into_sub_namespaces(self) -> None:
        glycerin80 = LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL.GLYCERIN_80
        assert _CANONICAL_LIQUID_VALUE in glycerin80.all_values()

    def test_catalog_object_is_a_folder_namespace(self) -> None:
        assert isinstance(LIQUID_CLASSES, _FolderNamespace)
        assert not isinstance(LIQUID_CLASSES, _CatalogNamespace)


def _declared_constants(namespace: _CatalogNamespace) -> dict[str, str]:
    """Collect every leaf string constant reachable from *namespace*, recursing into
    nested ``_CatalogNamespace`` children."""
    constants: dict[str, str] = {}
    for klass in reversed(type(namespace).__mro__):
        for attr, value in vars(klass).items():
            if attr.startswith("_"):
                continue
            if isinstance(value, str):
                constants[attr] = value
            elif isinstance(value, _CatalogNamespace):
                constants.update(_declared_constants(value))
    return constants


def _groups(root: _CatalogNamespace) -> dict[str, _CatalogNamespace]:
    groups: dict[str, _CatalogNamespace] = {}
    for attr, value in vars(type(root)).items():
        if not attr.startswith("_") and isinstance(value, _CatalogNamespace):
            groups[attr] = value
    return groups


class TestCommittedCatalogConsistency:
    """Guards the checked-in generated modules against hand-edits or partial
    regeneration, without needing a real Hamilton SDK install."""

    def test_labware_group_lookup_matches_declared_constants(self) -> None:
        # Every constant actually reachable via attribute access must resolve correctly
        # through _LOOKUP too -- this is what catches hand-edits or partial regeneration.
        # LABWARE only: LIQUID_CLASSES has no _LOOKUP (see TestLiquidClassFolderNamespace).
        groups = _groups(LABWARE)
        assert groups, "expected at least one catalog group"
        for name, group in groups.items():
            expected: dict[str, str] = {}
            for identifier, value in _declared_constants(group).items():
                expected[identifier.casefold()] = value
                expected[value.casefold()] = value
            missing_or_stale = {k: v for k, v in expected.items() if group._LOOKUP.get(k) != v}
            assert not missing_or_stale, f"stale _LOOKUP for group {name}: {missing_or_stale}"

    def test_labware_root_lookup_is_merge_of_groups(self) -> None:
        merged: dict[str, str] = {}
        for group in _groups(LABWARE).values():
            merged.update(group._LOOKUP)
        assert merged == LABWARE._LOOKUP

    def test_liquid_classes_source_has_no_duplicate_class_names(self) -> None:
        # Guards the exact bug tools/generate_catalog.py's _to_class_name docstring
        # describes: two different tree nodes (e.g. sibling folders "Glycerin80" and
        # "Glycerin_80%") rendering the *same* class name, so the second definition
        # silently shadows the first at module-exec time and the first folder's whole
        # subtree becomes unreachable (or worse, misattributed) with no error at all.
        # A static text check here means this is caught without needing a live VENUS
        # connection to regenerate and re-diff the file.
        import hamilton_venus.catalog.liquid_classes as liquid_classes_module

        source = Path(liquid_classes_module.__file__)
        class_names = re.findall(r"^class (\S+)\(", source.read_text(encoding="utf-8"), re.MULTILINE)
        duplicates = {name for name in class_names if class_names.count(name) > 1}
        assert not duplicates, f"duplicate class names in {source}: {duplicates}"

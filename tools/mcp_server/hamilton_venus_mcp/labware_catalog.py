"""Reflection-based catalog of ``hamilton_venus.catalog.LABWARE``, the SDK's static
labware-*type* catalog (carriers, plates, tip racks, ...).

Built the same way ``catalog.py`` builds its SDK-command catalog: read straight off
the generated ``LABWARE`` namespace classes at import time, so it never drifts from
whatever ``hamilton-venus-sdk`` version is actually installed, with no hand-maintained
list to keep in sync as the vendor labware catalog grows.

Not to be confused with ``get_labware_spec(labware_id)`` (an SDK command, see
``catalog.py``'s ``_EXCLUDED_METHODS``): that looks up a labware *instance* already
placed on the active deck, keyed by its deck instance name. This module is the SDK's
built-in catalog of labware *type* names/ids to reference when authoring a deck layout
or an SDK call that takes one -- the two are not interchangeable lookups.
"""

from __future__ import annotations

from dataclasses import dataclass

from hamilton_venus.catalog import LABWARE
from hamilton_venus.catalog._base import _CatalogNamespace


@dataclass(frozen=True)
class LabwareEntry:
    name: str
    category: str
    labware_id: str
    access_path: str


def _build_labware_catalog() -> list[LabwareEntry]:
    entries: list[LabwareEntry] = []
    for category_attr, namespace in vars(type(LABWARE)).items():
        if category_attr.startswith("_") or not isinstance(namespace, _CatalogNamespace):
            continue
        for const_name, value in vars(type(namespace)).items():
            if const_name.startswith("_") or not isinstance(value, str):
                continue
            entries.append(
                LabwareEntry(
                    name=const_name,
                    category=category_attr,
                    labware_id=value,
                    access_path=f"LABWARE.{category_attr}.{const_name}",
                )
            )
    return sorted(entries, key=lambda e: (e.category, e.name))


LABWARE_CATALOG: list[LabwareEntry] = _build_labware_catalog()

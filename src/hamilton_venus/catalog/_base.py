"""Base classes for the generated static catalogs.

This module is hand-written (not generated). Two different lookup strategies
are used by the two generated catalogs, deliberately:

- ``LABWARE`` uses :class:`_CatalogNamespace` — case-insensitive, dict-style
  lookup (``LABWARE["Nun_96_Fl_Hb"]``) backed by a ``_LOOKUP`` table each
  generated class builds at *generation* time. Labware names are unique
  regardless of which scope/category folder they're filed under on disk, so a
  flat, name-only lookup is unambiguous.
- ``LIQUID_CLASSES`` uses :class:`_FolderNamespace` — pure dot-access
  navigation that mirrors the ML_API folder structure a liquid class is
  defined under, e.g.::

        LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL_FILTER.WATER.SURFACE_EMPTY.MY_CLASS

  This one deliberately has **no** bracket/dict-style lookup. An earlier
  version of this catalog gave ``LIQUID_CLASSES`` the same flat, name-only
  lookup as ``LABWARE`` (via ``_CatalogNamespace``) -- that was a bug, not a
  convenience: unlike labware, a liquid class's tip type, pipetting device,
  and dispense mode are load-bearing parts of its identity, and a flat lookup
  silently discarded them, so a script could resolve a bare class name to
  whichever same-named file the generator happened to encounter, without the
  caller ever specifying which tip/device/mode variant they actually meant.
  Forcing (or at minimum offering) the full folder path via dot-access makes
  that context explicit at the call site instead of hidden inside the catalog.
  ``__getattr__`` still transparently searches child namespaces so
  intermediate folder levels (most usefully the leading type folder, e.g.
  ``STAR`` or ``SYSTEM``) can be skipped when they're not meaningfully
  ambiguous, down to referencing the leaf name directly off the root --  but
  every call site in this repo spells out the full path, matching this
  catalog's own generated examples, rather than relying on that shortcut.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar


class _CatalogNamespace:
    """Dict-style, case-insensitive lookup over a generated ``_LOOKUP`` table.

    Used by ``LABWARE`` -- see the module docstring for why ``LIQUID_CLASSES``
    uses :class:`_FolderNamespace` instead.
    """

    _LOOKUP: ClassVar[dict[str, str]] = {}

    def __getitem__(self, key: object) -> str:
        if isinstance(key, str):
            value = self._LOOKUP.get(key.casefold())
            if value is not None:
                return value
        raise KeyError(key)

    def get(self, key: object, default: str | None = None) -> str | None:
        """Case-insensitively resolve *key* to its canonical value.

        Returns *default* when *key* is not a string or is not found.
        """
        if isinstance(key, str):
            return self._LOOKUP.get(key.casefold(), default)
        return default

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.casefold() in self._LOOKUP

    def __iter__(self) -> Iterator[str]:
        return iter(dict.fromkeys(self._LOOKUP.values()))


class _FolderNamespace:
    """Dot-access namespace for generated folder-structured catalogs.

    Used by ``LIQUID_CLASSES`` -- see the module docstring for why this one
    has no bracket/dict-style lookup, unlike ``LABWARE``'s ``_CatalogNamespace``.

    Each folder level becomes a nested ``_FolderNamespace`` subclass, and
    each leaf item name is stored as a plain ``str`` class attribute. There
    is no lookup dict — navigation is purely via attribute access::

        LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_300UL_FILTER.WATER.SURFACE_EMPTY.MY_CLASS

    Iteration yields all string-valued attributes on the instance, allowing::

        list(LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL)
    """

    def __iter__(self) -> Iterator[str]:
        """Yield all leaf item names (``str`` attrs) on this namespace."""
        for name in vars(type(self)):
            if not name.startswith("_"):
                value = getattr(self, name)
                if isinstance(value, str):
                    yield value

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, str):
            return False
        return any(v == item for v in self)

    def __getattr__(self, name: str) -> str:
        """Search child namespaces when ``name`` is not a direct attribute.

        Allows callers to skip intermediate folder levels -- most usefully the
        leading type folder (``STAR``, ``VANTAGE``, ``SYSTEM``, ``USER``, ...),
        which is resolved automatically::

            # both are equivalent -- the STAR level is bypassed
            LIQUID_CLASSES.STAR.SYSTEM.CHANNELS_1000UL.TIP_1000UL.WATER.JET_EMPTY.HIGHVOLUME_WATER_DISPENSEJET_EMPTY
            LIQUID_CLASSES.SYSTEM.CHANNELS_1000UL.TIP_1000UL.WATER.JET_EMPTY.HIGHVOLUME_WATER_DISPENSEJET_EMPTY

            # any other intermediate level, or the leaf name directly, also works
            LIQUID_CLASSES.HIGHVOLUME_WATER_DISPENSEJET_EMPTY

        This repo's own call sites always spell out the full path rather than
        relying on this bypass -- see the module docstring for why.
        """
        for attr in vars(type(self)):
            if attr.startswith("_"):
                continue
            child = getattr(type(self), attr)
            if isinstance(child, _FolderNamespace):
                try:
                    value: str = getattr(child, name)
                except AttributeError:
                    continue
                return value
        raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")

    def all_values(self) -> list[str]:
        """Return all leaf item names reachable from this namespace."""
        results: list[str] = []
        for name in vars(type(self)):
            if name.startswith("_"):
                continue
            value = getattr(self, name)
            if isinstance(value, str):
                results.append(value)
            elif isinstance(value, _FolderNamespace):
                results.extend(value.all_values())
        return results

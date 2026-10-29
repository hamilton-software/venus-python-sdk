"""Taught-location registration commands for the synchronous instrument clients.

Thin wrappers over :mod:`hamilton_venus.taught_locations`. These read and write
``<SDK install>\\Active Layout\\TaughtLocations.json`` directly -- they do not
talk to the instrument or the VENUS runtime, so they work with no connection and
regardless of ``auto_connect`` / ``instrument_init()``. Enforcing the recorded
corrections at runtime is a separate VENUS-side concern.

Method names carry a ``taught`` stem so they sit apart from the deck-layout query
commands (e.g. ``get_labware_positions``, ``get_labware_location``).

Set :attr:`TaughtLocationCommandsMixin._taught_locations_path` on a client
instance (or subclass) to redirect the file, e.g. for tests.
"""

from __future__ import annotations

from pathlib import Path

from hamilton_venus import taught_locations
from hamilton_venus.taught_locations import CarrierSiteOffset, LabwarePosition, TaughtLocationsFile


class TaughtLocationCommandsMixin:
    """Record operator taught locations into the Active Layout directory."""

    _taught_locations_path: str | Path | None = None

    def register_taught_offset(
        self,
        carrier: str,
        site: str | int,
        *,
        dx: float,
        dy: float,
        dz: float,
        d_angle: float = 0.0,
        note: str | None = None,
    ) -> CarrierSiteOffset:
        """Record an X/Y/Z (+ angle) offset for a carrier/site, replacing any prior one."""
        return taught_locations.register_taught_offset(
            carrier,
            site,
            dx=dx,
            dy=dy,
            dz=dz,
            d_angle=d_angle,
            note=note,
            path=self._taught_locations_path,
        )

    def register_taught_position(
        self,
        labware: str,
        carrier: str,
        site: str | int,
        *,
        x: float,
        y: float,
        z: float,
        angle: float = 0.0,
        note: str | None = None,
    ) -> LabwarePosition:
        """Record absolute coordinates for a labware item at a carrier/site, replacing any prior one."""
        return taught_locations.register_taught_position(
            labware,
            carrier,
            site,
            x=x,
            y=y,
            z=z,
            angle=angle,
            note=note,
            path=self._taught_locations_path,
        )

    def get_taught_locations(self) -> TaughtLocationsFile:
        """Return the whole taught-locations file (an empty model when it does not exist)."""
        return taught_locations.get_taught_locations(path=self._taught_locations_path)

    def get_taught_offset(self, carrier: str, site: str | int) -> CarrierSiteOffset | None:
        """Return the offset recorded for a carrier/site, or ``None``."""
        return taught_locations.get_taught_offset(carrier, site, path=self._taught_locations_path)

    def get_taught_positions(self, labware: str) -> dict[str, LabwarePosition]:
        """Return every taught position for a labware item, keyed by ``"<carrier>/<site>"`` (``{}`` if none)."""
        return taught_locations.get_taught_positions(labware, path=self._taught_locations_path)

    def get_taught_position(
        self,
        labware: str,
        carrier: str,
        site: str | int,
    ) -> LabwarePosition | None:
        """Return the position recorded for a labware item at a carrier/site, or ``None``."""
        return taught_locations.get_taught_position(
            labware, carrier, site, path=self._taught_locations_path
        )

    def resolve_taught_location(
        self,
        labware: str,
        carrier: str,
        site: str | int,
    ) -> LabwarePosition | CarrierSiteOffset | None:
        """Resolve a teach point the way VENUS is expected to: labware at
        carrier/site first, then the carrier/site offset."""
        return taught_locations.resolve_taught_location(
            labware, carrier, site, path=self._taught_locations_path
        )

    def remove_taught_offset(self, carrier: str, site: str | int) -> bool:
        """Delete the offset for a carrier/site. Returns ``True`` if one was present."""
        return taught_locations.remove_taught_offset(
            carrier, site, path=self._taught_locations_path
        )

    def remove_taught_position(
        self,
        labware: str,
        carrier: str | None = None,
        site: str | int | None = None,
    ) -> bool:
        """Delete taught positions for a labware item.

        Pass ``carrier`` and ``site`` together to delete just that combination;
        omit both to delete every taught position for the labware. Returns
        ``True`` if anything was removed.
        """
        return taught_locations.remove_taught_position(
            labware, carrier, site, path=self._taught_locations_path
        )

    def clear_taught_locations(self) -> None:
        """Empty both maps, leaving a canonical empty file in place."""
        taught_locations.clear_taught_locations(path=self._taught_locations_path)

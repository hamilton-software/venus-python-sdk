from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile
    from hamilton_venus.models.compound_results import CopyPlateResult
    from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings


class CopyPlateCommand:
    """Mixin that exposes the :meth:`copy_plate` compound command on :class:`StarClient`."""

    if TYPE_CHECKING:

        def _liquid_classes_for_command(self, *liquid_classes: Any) -> AbstractContextManager[None]: ...

    def copy_plate(
        self,
        source_plate_id: str,
        dest_plate_id: str | list[str],
        *,
        volume: float,
        liquid_class: str | list[str],
        channels: list[int] | None = None,
        tip_pool: str,
        reuse_tips: bool = False,
        aspirate_settings: AspirateSettings | None = None,
        dispense_settings: DispenseSettings | None = None,
        error_profile: ErrorProfile | None = None,
    ) -> CopyPlateResult:
        """Copy liquid from every well on a source plate to one or more destination plates.

        See :func:`~hamilton_venus.compound_commands.copy_plate.execute_copy_plate`
        for the full parameter and behaviour documentation.
        """
        from hamilton_venus.compound_commands.copy_plate import execute_copy_plate

        with self._liquid_classes_for_command(liquid_class):
            return execute_copy_plate(
                cast("InstrumentClient", self),
                source_plate_id,
                dest_plate_id,
                volume=volume,
                liquid_class=liquid_class,
                channels=channels,
                tip_pool=tip_pool,
                reuse_tips=reuse_tips,
                aspirate_settings=aspirate_settings,
                dispense_settings=dispense_settings,
                error_profile=error_profile,
            )

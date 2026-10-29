from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from hamilton_venus.models.enums import WellOrder

# Real import, not TYPE_CHECKING-guarded -- see add_reagent_command.py's identical
# import for why: pool_samples's own signature below needs Position resolvable at
# runtime for hamilton_venus_mcp's reflection-based catalog to build a working
# pydantic TypeAdapter for it.
from hamilton_venus.models.position import Position

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile
    from hamilton_venus.models.compound_results import PoolSamplesResult
    from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings


class PoolSamplesCommand:
    """Mixin that exposes the :meth:`pool_samples` compound command on :class:`StarClient`."""

    if TYPE_CHECKING:

        def _liquid_classes_for_command(self, *liquid_classes: Any) -> AbstractContextManager[None]: ...

    def pool_samples(
        self,
        *,
        source_plate: str | list[str] | Position | list[Position],
        dest_plate: str | list[str] | Position | list[Position],
        pool_size: int,
        volume_per_source: float,
        liquid_class: str | list[str],
        tip_pool: str,
        channels: list[int] | None = None,
        source_order: WellOrder = WellOrder.COL_ASC,
        dest_order: WellOrder = WellOrder.COL_ASC,
        mix_after_pool: bool = True,
        reuse_tips_within_pool: bool = False,
        optimized_tip_pickup: bool = True,
        aspirate_settings: AspirateSettings | None = None,
        dispense_settings: DispenseSettings | None = None,
        error_profile: ErrorProfile | None = None,
    ) -> PoolSamplesResult:
        """Combine ``N`` source wells into one destination well, one pool at a time.

        See :func:`hamilton_venus.compound_commands.pool_samples.execute_pool_samples`
        for the full parameter reference.
        """
        from hamilton_venus.compound_commands.pool_samples import execute_pool_samples

        with self._liquid_classes_for_command(liquid_class):
            return execute_pool_samples(
                cast("InstrumentClient", self),
                source_plate=source_plate,
                dest_plate=dest_plate,
                pool_size=pool_size,
                volume_per_source=volume_per_source,
                liquid_class=liquid_class,
                tip_pool=tip_pool,
                channels=channels,
                source_order=source_order,
                dest_order=dest_order,
                mix_after_pool=mix_after_pool,
                reuse_tips_within_pool=reuse_tips_within_pool,
                optimized_tip_pickup=optimized_tip_pickup,
                aspirate_settings=aspirate_settings,
                dispense_settings=dispense_settings,
                error_profile=error_profile,
            )

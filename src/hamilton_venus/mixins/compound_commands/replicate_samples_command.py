from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from hamilton_venus.models.enums import PreAliquotDisposal, WellOrder

# Real import, not TYPE_CHECKING-guarded -- see add_reagent_command.py's identical
# import for why: replicate_samples's own signature below needs Position resolvable
# at runtime for hamilton_venus_mcp's reflection-based catalog to build a working
# pydantic TypeAdapter for it.
from hamilton_venus.models.position import Position

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile
    from hamilton_venus.models.compound_results import ReplicateSamplesResult
    from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings


class ReplicateSamplesCommand:
    """Mixin that exposes the :meth:`replicate_samples` compound command on :class:`StarClient`."""

    if TYPE_CHECKING:

        def _liquid_classes_for_command(self, *liquid_classes: Any) -> AbstractContextManager[None]: ...

    def replicate_samples(
        self,
        *,
        source_plate: str | list[str] | Position | list[Position],
        dest_plate: str | list[str] | Position | list[Position],
        replicates_per_source: int,
        volume_per_replicate: float,
        liquid_class: str | list[str],
        tip_pool: str,
        channels: list[int] | None = None,
        source_order: WellOrder = WellOrder.COL_ASC,
        dest_order: WellOrder = WellOrder.COL_ASC,
        multi_dispense: bool = True,
        pre_aliquot_volume: float = 0.0,
        pre_aliquot_disposal: PreAliquotDisposal = PreAliquotDisposal.SOURCE,
        post_aliquot_volume: float = 0.0,
        post_aliquot_height: float = 5.0,
        optimized_tip_pickup: bool = True,
        aspirate_settings: AspirateSettings | None = None,
        dispense_settings: DispenseSettings | None = None,
        error_profile: ErrorProfile | None = None,
    ) -> ReplicateSamplesResult:
        """Replicate every source well into ``replicates_per_source`` destination wells.

        See :func:`hamilton_venus.compound_commands.replicate_samples.execute_replicate_samples`
        for the full parameter reference.
        """
        from hamilton_venus.compound_commands.replicate_samples import execute_replicate_samples

        with self._liquid_classes_for_command(liquid_class):
            return execute_replicate_samples(
                cast("InstrumentClient", self),
                source_plate=source_plate,
                dest_plate=dest_plate,
                replicates_per_source=replicates_per_source,
                volume_per_replicate=volume_per_replicate,
                liquid_class=liquid_class,
                tip_pool=tip_pool,
                channels=channels,
                source_order=source_order,
                dest_order=dest_order,
                multi_dispense=multi_dispense,
                pre_aliquot_volume=pre_aliquot_volume,
                pre_aliquot_disposal=pre_aliquot_disposal,
                post_aliquot_volume=post_aliquot_volume,
                post_aliquot_height=post_aliquot_height,
                optimized_tip_pickup=optimized_tip_pickup,
                aspirate_settings=aspirate_settings,
                dispense_settings=dispense_settings,
                error_profile=error_profile,
            )

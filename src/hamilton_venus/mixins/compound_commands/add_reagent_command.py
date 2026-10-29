from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from hamilton_venus.models.enums import PreAliquotDisposal

# Real import, not TYPE_CHECKING-guarded like the rest of this module's annotations:
# add_reagent's own signature below uses Position as a real runtime type, resolved
# by hamilton_venus_mcp's reflection-based catalog (get_type_hints on this method) to
# build a pydantic TypeAdapter for argument coercion. A TYPE_CHECKING-only import
# leaves Position out of this module's runtime globals entirely, so that resolution
# falls back to the bare annotation string, which pydantic can only partially resolve
# and later fails with "not fully defined" on the first real call, regardless of the
# value passed.
from hamilton_venus.models.position import Position

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile
    from hamilton_venus.models.compound_results import AddReagentResult
    from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings


class AddReagentCommand:
    """Mixin that exposes the :meth:`add_reagent` compound command on :class:`StarClient`."""

    if TYPE_CHECKING:

        def _liquid_classes_for_command(self, *liquid_classes: Any) -> AbstractContextManager[None]: ...

    def add_reagent(
        self,
        *,
        reagent_source: str | list[str] | Position | list[Position],
        dest_plate: str | list[str] | Position | list[Position],
        volume: float,
        tip_pool: str,
        liquid_class: str | list[str],
        multi_dispense: bool = False,
        pre_aliquot_volume: float = 0.0,
        pre_aliquot_disposal: PreAliquotDisposal = PreAliquotDisposal.SOURCE,
        post_aliquot_volume: float = 0.0,
        post_aliquot_height: float = 5.0,
        channels: list[int] | None = None,
        optimized_tip_pickup: bool = True,
        reuse_tips: bool = False,
        aspirate_settings: AspirateSettings | None = None,
        dispense_settings: DispenseSettings | None = None,
        error_profile: ErrorProfile | None = None,
        transfer_csv: str | None = None,
        follow_csv_order: bool = False,
    ) -> AddReagentResult:
        """Transfer reagent from a source location to multiple destination wells.

        See :func:`~hamilton_venus.compound_commands.add_reagent.execute_add_reagent`
        for full parameter documentation.
        """
        from hamilton_venus.compound_commands.add_reagent import execute_add_reagent

        with self._liquid_classes_for_command(liquid_class):
            return execute_add_reagent(
                cast("InstrumentClient", self),
                reagent_source=reagent_source,
                dest_plate=dest_plate,
                volume=volume,
                tip_pool=tip_pool,
                liquid_class=liquid_class,
                multi_dispense=multi_dispense,
                pre_aliquot_volume=pre_aliquot_volume,
                pre_aliquot_disposal=pre_aliquot_disposal,
                post_aliquot_volume=post_aliquot_volume,
                post_aliquot_height=post_aliquot_height,
                channels=channels,
                optimized_tip_pickup=optimized_tip_pickup,
                reuse_tips=reuse_tips,
                aspirate_settings=aspirate_settings,
                dispense_settings=dispense_settings,
                error_profile=error_profile,
                transfer_csv=transfer_csv,
                follow_csv_order=follow_csv_order,
            )

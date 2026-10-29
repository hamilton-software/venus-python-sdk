from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile
    from hamilton_venus.models.compound_results import HitPickingResult
    from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings


class HitPickingCommand:
    """Mixin that exposes the :meth:`hit_picking` compound command on :class:`StarClient`."""

    if TYPE_CHECKING:

        def _liquid_classes_for_command(self, *liquid_classes: Any) -> AbstractContextManager[None]: ...

    def hit_picking(
        self,
        *,
        transfer_csv: str | os.PathLike[str],
        liquid_class: str | list[str],
        tip_pool: str,
        channels: list[int] | None = None,
        optimized_tip_pickup: bool = True,
        change_tips: bool = True,
        minimize_tips: bool = False,
        follow_csv_order: bool = False,
        aspirate_settings: AspirateSettings | None = None,
        dispense_settings: DispenseSettings | None = None,
        error_profile: ErrorProfile | None = None,
    ) -> HitPickingResult:
        """Transfer samples between arbitrary source and destination wells from a CSV worklist.

        See :func:`~hamilton_venus.compound_commands.hit_picking.execute_hit_picking`
        for full parameter documentation.
        """
        from hamilton_venus.compound_commands.hit_picking import execute_hit_picking

        with self._liquid_classes_for_command(liquid_class):
            return execute_hit_picking(
                cast("InstrumentClient", self),
                transfer_csv=transfer_csv,
                liquid_class=liquid_class,
                tip_pool=tip_pool,
                channels=channels,
                optimized_tip_pickup=optimized_tip_pickup,
                change_tips=change_tips,
                minimize_tips=minimize_tips,
                follow_csv_order=follow_csv_order,
                aspirate_settings=aspirate_settings,
                dispense_settings=dispense_settings,
                error_profile=error_profile,
            )

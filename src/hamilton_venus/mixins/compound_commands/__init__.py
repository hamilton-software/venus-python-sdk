from __future__ import annotations

from hamilton_venus.mixins.compound_commands.add_reagent_command import AddReagentCommand
from hamilton_venus.mixins.compound_commands.copy_plate_command import CopyPlateCommand
from hamilton_venus.mixins.compound_commands.hit_picking_command import HitPickingCommand
from hamilton_venus.mixins.compound_commands.pool_samples_command import PoolSamplesCommand
from hamilton_venus.mixins.compound_commands.replicate_samples_command import ReplicateSamplesCommand
from hamilton_venus.mixins.compound_commands.serial_dilution_command import SerialDilutionCommand


class CompoundCommandsMixin(
    AddReagentCommand,
    CopyPlateCommand,
    HitPickingCommand,
    PoolSamplesCommand,
    ReplicateSamplesCommand,
    SerialDilutionCommand,
):
    """Aggregates all compound-command mixins into a single mixin for :class:`StarClient` and :class:`VantageClient`."""

    pass


__all__ = ["CompoundCommandsMixin"]

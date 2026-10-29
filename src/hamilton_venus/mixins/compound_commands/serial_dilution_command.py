from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from hamilton_venus.models.enums import LastDilutionWaste

# Real import, not TYPE_CHECKING-guarded -- see add_reagent_command.py's identical
# import for why: these commands' own signatures below need Position resolvable at
# runtime for hamilton_venus_mcp's reflection-based catalog to build a working
# pydantic TypeAdapter for it.
from hamilton_venus.models.position import Position

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from hamilton_venus.compound_commands._helpers._protocol import InstrumentClient
    from hamilton_venus.error_handling.profile import ErrorProfile
    from hamilton_venus.models.compound_results import SerialDilutionResult
    from hamilton_venus.models.liquid_handling_settings import AspirateSettings, DispenseSettings


class SerialDilutionCommand:
    """Mixin exposing the serial-dilution compound commands on :class:`StarClient`.

    Provides two peer methods that differ only in how the per-well diluent
    volume is determined: :meth:`serial_dilution_by_volume` takes an explicit
    ``diluent_volume`` while :meth:`serial_dilution_by_dilution_factor` derives
    it from a target fold ``dilution_factor``.
    """

    if TYPE_CHECKING:

        def _liquid_classes_for_command(self, *liquid_classes: Any) -> AbstractContextManager[None]: ...

    def serial_dilution_by_volume(
        self,
        *,
        plate_id: str | list[str] | Position | list[Position],
        start_column: int,
        num_dilutions: int,
        transfer_volume: float,
        diluent_volume: float,
        diluent_source: str | list[str],
        diluent_liquid_class: str | list[str] = "HighVolume_Water_DispenseJet_Empty",
        diluent_tip_pool: str = "",
        transfer_liquid_class: str | list[str] = "HighVolume_Water_DispenseJet_Empty",
        transfer_tip_pool: str,
        channels: list[int] | None = None,
        exclude_columns: list[int] | None = None,
        exclude_rows: list[int | str] | None = None,
        mix_after_dispense: bool = True,
        diluent_multi_dispense: bool = True,
        reuse_tips: bool = False,
        discard_last_excess: LastDilutionWaste = LastDilutionWaste.NONE,
        waste_location: str | None = None,
        optimized_tip_pickup: bool = True,
        diluent_asp_settings: AspirateSettings | None = None,
        diluent_disp_settings: DispenseSettings | None = None,
        transfer_asp_settings: AspirateSettings | None = None,
        transfer_disp_settings: DispenseSettings | None = None,
        diluent_error_profile: ErrorProfile | None = None,
        transfer_error_profile: ErrorProfile | None = None,
    ) -> SerialDilutionResult:
        """Serial-dilute across plate columns using an explicit per-well diluent volume.

        See
        :func:`hamilton_venus.compound_commands.serial_dilution.execute_serial_dilution_by_volume`
        for the full parameter reference.
        """
        from hamilton_venus.compound_commands.serial_dilution import execute_serial_dilution_by_volume

        with self._liquid_classes_for_command(diluent_liquid_class, transfer_liquid_class):
            return execute_serial_dilution_by_volume(
                cast("InstrumentClient", self),
                plate_id=plate_id,
                start_column=start_column,
                num_dilutions=num_dilutions,
                transfer_volume=transfer_volume,
                diluent_volume=diluent_volume,
                diluent_source=diluent_source,
                diluent_liquid_class=diluent_liquid_class,
                diluent_tip_pool=diluent_tip_pool,
                transfer_liquid_class=transfer_liquid_class,
                transfer_tip_pool=transfer_tip_pool,
                channels=channels,
                exclude_columns=exclude_columns,
                exclude_rows=exclude_rows,
                mix_after_dispense=mix_after_dispense,
                diluent_multi_dispense=diluent_multi_dispense,
                reuse_tips=reuse_tips,
                discard_last_excess=discard_last_excess,
                waste_location=waste_location,
                optimized_tip_pickup=optimized_tip_pickup,
                diluent_asp_settings=diluent_asp_settings,
                diluent_disp_settings=diluent_disp_settings,
                transfer_asp_settings=transfer_asp_settings,
                transfer_disp_settings=transfer_disp_settings,
                diluent_error_profile=diluent_error_profile,
                transfer_error_profile=transfer_error_profile,
            )

    def serial_dilution_by_dilution_factor(
        self,
        *,
        plate_id: str | list[str] | Position | list[Position],
        start_column: int,
        num_dilutions: int,
        transfer_volume: float,
        dilution_factor: float,
        diluent_source: str | list[str],
        diluent_liquid_class: str | list[str] = "HighVolume_Water_DispenseJet_Empty",
        diluent_tip_pool: str = "",
        transfer_liquid_class: str | list[str] = "HighVolume_Water_DispenseJet_Empty",
        transfer_tip_pool: str,
        channels: list[int] | None = None,
        exclude_columns: list[int] | None = None,
        exclude_rows: list[int | str] | None = None,
        mix_after_dispense: bool = True,
        diluent_multi_dispense: bool = True,
        reuse_tips: bool = False,
        discard_last_excess: LastDilutionWaste = LastDilutionWaste.NONE,
        waste_location: str | None = None,
        optimized_tip_pickup: bool = True,
        diluent_asp_settings: AspirateSettings | None = None,
        diluent_disp_settings: DispenseSettings | None = None,
        transfer_asp_settings: AspirateSettings | None = None,
        transfer_disp_settings: DispenseSettings | None = None,
        diluent_error_profile: ErrorProfile | None = None,
        transfer_error_profile: ErrorProfile | None = None,
    ) -> SerialDilutionResult:
        """Serial-dilute across plate columns using a target fold ``dilution_factor``.

        See
        :func:`hamilton_venus.compound_commands.serial_dilution.execute_serial_dilution_by_dilution_factor`
        for the full parameter reference.
        """
        from hamilton_venus.compound_commands.serial_dilution import execute_serial_dilution_by_dilution_factor

        with self._liquid_classes_for_command(diluent_liquid_class, transfer_liquid_class):
            return execute_serial_dilution_by_dilution_factor(
                cast("InstrumentClient", self),
                plate_id=plate_id,
                start_column=start_column,
                num_dilutions=num_dilutions,
                transfer_volume=transfer_volume,
                dilution_factor=dilution_factor,
                diluent_source=diluent_source,
                diluent_liquid_class=diluent_liquid_class,
                diluent_tip_pool=diluent_tip_pool,
                transfer_liquid_class=transfer_liquid_class,
                transfer_tip_pool=transfer_tip_pool,
                channels=channels,
                exclude_columns=exclude_columns,
                exclude_rows=exclude_rows,
                mix_after_dispense=mix_after_dispense,
                diluent_multi_dispense=diluent_multi_dispense,
                reuse_tips=reuse_tips,
                discard_last_excess=discard_last_excess,
                waste_location=waste_location,
                optimized_tip_pickup=optimized_tip_pickup,
                diluent_asp_settings=diluent_asp_settings,
                diluent_disp_settings=diluent_disp_settings,
                transfer_asp_settings=transfer_asp_settings,
                transfer_disp_settings=transfer_disp_settings,
                diluent_error_profile=diluent_error_profile,
                transfer_error_profile=transfer_error_profile,
            )

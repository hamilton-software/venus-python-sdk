"""Command mixins for the synchronous instrument clients organized by category."""
# Mixins shared by the synchronous instrument clients (StarClient, VantageClient).
# Instrument-specific mixins (e.g. Vantage-only command groups) live alongside these.

from __future__ import annotations

from hamilton_venus.mixins.autoload_commands import AutoloadCommandsMixin
from hamilton_venus.mixins.channel_commands import ChannelCommandsMixin, Channels5mLCommandsMixin
from hamilton_venus.mixins.compound_commands import CompoundCommandsMixin
from hamilton_venus.mixins.configuration_commands import ConfigurationCommandsMixin
from hamilton_venus.mixins.deck_commands import DeckCommandsMixin
from hamilton_venus.mixins.deck_labware_commands import DeckLabwareCommandsMixin
from hamilton_venus.mixins.deck_status_commands import DeckStatusCommandsMixin
from hamilton_venus.mixins.error_simulator_commands import ErrorSimulatorCommandsMixin
from hamilton_venus.mixins.firmware_commands import FirmwareCommandsMixin
from hamilton_venus.mixins.front_cover_commands import FrontCoverCommandsMixin
from hamilton_venus.mixins.heater_shaker_commands import HeaterShakerCommandsMixin
from hamilton_venus.mixins.labware_commands import LabwareCommandsMixin
from hamilton_venus.mixins.labware_definition_commands import LabwareDefinitionCommandsMixin
from hamilton_venus.mixins.liquid_class_commands import LiquidClassCommandsMixin
from hamilton_venus.mixins.load_tray_commands import LoadTrayCommandsMixin
from hamilton_venus.mixins.magpip_commands import ChannelsMagPipCommandsMixin
from hamilton_venus.mixins.maintenance_commands import MaintenanceCommandsMixin
from hamilton_venus.mixins.mph96_commands import MPH96CommandsMixin
from hamilton_venus.mixins.pipetting_arm_commands import PipettingArmCommandsMixin
from hamilton_venus.mixins.sample_tracking_commands import SampleTrackingCommandsMixin
from hamilton_venus.mixins.split_well_commands import SplitWellCommandsMixin
from hamilton_venus.mixins.status_commands import StatusCommandsMixin
from hamilton_venus.mixins.status_light_commands import StatusLightCommandsMixin
from hamilton_venus.mixins.taught_location_commands import TaughtLocationCommandsMixin
from hamilton_venus.mixins.teaching_commands import TeachingCommandsMixin
from hamilton_venus.mixins.tip_pool_commands import TipPoolCommandsMixin
from hamilton_venus.mixins.transport_commands import TransportCommandsMixin

__all__ = [
    "AutoloadCommandsMixin",
    "ChannelCommandsMixin",
    "Channels5mLCommandsMixin",
    "ChannelsMagPipCommandsMixin",
    "CompoundCommandsMixin",
    "ConfigurationCommandsMixin",
    "DeckCommandsMixin",
    "DeckLabwareCommandsMixin",
    "DeckStatusCommandsMixin",
    "ErrorSimulatorCommandsMixin",
    "FirmwareCommandsMixin",
    "FrontCoverCommandsMixin",
    "HeaterShakerCommandsMixin",
    "LabwareCommandsMixin",
    "LabwareDefinitionCommandsMixin",
    "LiquidClassCommandsMixin",
    "LoadTrayCommandsMixin",
    "MPH96CommandsMixin",
    "MaintenanceCommandsMixin",
    "PipettingArmCommandsMixin",
    "SampleTrackingCommandsMixin",
    "SplitWellCommandsMixin",
    "StatusCommandsMixin",
    "StatusLightCommandsMixin",
    "TaughtLocationCommandsMixin",
    "TeachingCommandsMixin",
    "TipPoolCommandsMixin",
    "TransportCommandsMixin",
]

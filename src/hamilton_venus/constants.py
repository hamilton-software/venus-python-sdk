"""Star instrument hardware constants."""

CHANNEL_PITCH_MM_1ML: float = 9.0
CHANNEL_PITCH_MM_5ML: float = 18.0

# Upper bound on the number of pipetting channels a system can be configured with.
# The actual count depends on the instrument configuration (commonly 8, up to 16);
# the SDK only enforces this ceiling and the instrument rejects channels it lacks.
MAX_CHANNELS: int = 16

# ``ChannelInfo.type`` values the instrument configuration reports for a channel module.
# The two cannot be mixed on one instrument: Fluid Motion channels use the 4-channel QCG
# gripper, Legacy channels the 2-channel CO-RE gripper.
FLUID_MOTION_CHANNEL_TYPE: str = "Fluid Motion"
LEGACY_CHANNEL_TYPE: str = "Legacy"

# The literal value VENUS requires for ``safety_bypass_token`` to waive its safety
# checks. It is not a passphrase or arbitrary flag -- any other string is rejected
# (or, for the movement commands, silently ignored and the safety check still runs).
OVERRIDE_SAFETY_CHECKS: str = "OVERRIDE_SAFETY_CHECKS"

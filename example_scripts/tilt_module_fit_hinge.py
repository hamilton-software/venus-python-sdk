"""Calibrate a tilt module: the plate's real angle and the hinge, from four probe readings.

A tilt module commanded to 10 degrees may hold the plate at a slightly different angle, and
its hinge is a pin under the plate rather than the plate's lower-left corner that
``tilt_labware`` assumes by default. This script turns probe readings into the
``tilt_labware`` arguments for one module.

How to take the readings (VENUS "Move Probe - Key Control" on the instrument):

1. Put a plate on the module, flat (0 degrees). Pick two points far apart along X, e.g. where
   the LEFT wall of a well meets its floor in the leftmost and the rightmost column of one row.
   Read their deck X and Z.
2. Tilt the module to the angle you will command (``COMMANDED_DEGREES``) and read the same
   two points again.
3. Read the plate's left edge X and base Z when flat from the deck layout (or
   ``get_labware_coordinates``), and fill in everything below.

Needs no instrument: it only does the maths. The numbers below are the readings taken on one
STARlet with an MFX Tilt Module on 2026-10-16.
"""

from __future__ import annotations

from hamilton_venus.tilt_calibration import fit_tilt_hinge

# Deck (X, Z) of the probed points, mm.
FLAT = {"B1": (424.7, 203.0), "B3": (504.9, 203.0)}  # module at 0 degrees
TILTED = {"B1": (423.0, 203.4), "B3": (502.1, 218.5)}  # module at COMMANDED_DEGREES
COMMANDED_DEGREES = 10

# The plate when flat: its left edge X and its base Z.
PLATE_LEFT_EDGE_X = 418.9
PLATE_BASE_Z = 199.65

fit = fit_tilt_hinge(
    FLAT,
    TILTED,
    commanded_degrees=COMMANDED_DEGREES,
    plate_left_edge_x=PLATE_LEFT_EDGE_X,
    plate_base_z=PLATE_BASE_Z,
)

# The points are this many columns apart; their flat span checks the labware definition's pitch.
COLUMNS_APART = 2
print(
    f"Flat span {fit.flat_span_mm:.2f} mm: a column pitch of {fit.flat_span_mm / COLUMNS_APART:.2f} mm "
    "(compare with the plate's labware definition)."
)
print(f"The span changed by {fit.span_change_mm:+.2f} mm from flat to tilted (a rigid plate keeps it).")
if abs(fit.span_change_mm) > 0.5:
    print("  More than the reading noise: take the readings again before trusting the fit.")

best, commanded = fit.best, fit.at_commanded
print(
    f"Best fit: the plate sits at {best.angle_degrees:.2f} degrees, hinge X {best.hinge_x:.1f} Z {best.hinge_z:.1f}, "
    f"rms {best.rms_mm:.2f} mm"
)
print(
    f"At exactly {COMMANDED_DEGREES} degrees: hinge X {commanded.hinge_x:.1f} Z {commanded.hinge_z:.1f}, "
    f"rms {commanded.rms_mm:.2f} mm"
)
print("\nPass to tilt_labware (keep these with this module):")
print(f"  with the measured angle: {fit.tilt_labware_kwargs()}")
print(f"  commanded angle only:    {fit.tilt_labware_kwargs(use_measured_angle=False)}")

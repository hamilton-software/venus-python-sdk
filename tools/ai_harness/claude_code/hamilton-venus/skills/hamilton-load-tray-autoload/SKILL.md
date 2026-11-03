---
name: hamilton-load-tray-autoload
description: 'Loading and unloading carriers with the Hamilton Autoload (STAR) / IDL (Vantage) and using the load tray. Use when a script or session loads or unloads carriers, scans labware, lowers or raises the load tray (Vantage only; the STAR''s is fixed), reloads a carrier that may already be pushed in, or parks the autoload; also for the differences between STAR and Vantage unloading.'
---

# Autoload and load tray

## Naming

STAR calls it the **Autoload**, Vantage the **IDL**. The Python commands call both `autoload_*`; the user may use either name.

## Load tray (Vantage only)

Only the Vantage can move its load tray up and down. The STAR's load tray is fixed, so it makes no movements and has no lower / raise commands to call: skip these rules there.

- Loading several labware: call the **lower** load tray first, so it does not go up and down repeatedly.
- **Raise** the load tray only after all loading has finished.
- While the load tray is down and/or the door is unlocked, the arm moves at **slow speed**. Once both are fixed it returns to normal speed.

## Autoload

- **Always park the autoload to the right** (`autoload_park_right`) after scanning all labware, so it is not in the way of other carriers and the user can pull carriers out by hand.
- **STAR**: can safely unload and reload carriers. Before a load, check carrier presence (`autoload_get_carrier_sensor_status`); if the carrier is already pushed in, unload it first. Otherwise VENUS raises a warning the user must acknowledge. Example: `example_scripts/load_unload_dwp_carrier.py`.
- **Vantage**: cannot safely unload a carrier, because it does not have the locking mechanism that keeps carriers on the load tray. The load commands handle unload and load automatically. **Discourage calling unload on a Vantage.**

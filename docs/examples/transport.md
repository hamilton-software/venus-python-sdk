# Transport and Gripper Tools

Examples for transporting plates using both CO-RE grippers and iSWAP tools.

> **Note:** The `grip_width` and `grip_open` parameters are optional. If not specified, they will be automatically calculated by the server based on the labware being transported. This makes examples cleaner and easier to read while maintaining full control when needed.

> **Tilted plates:** every transport command that takes a `labware_name` (CO-RE / QCG, 5 mL CO-RE, iSWAP / IPG) raises `LabwareTiltedError` for a plate that [`tilt_labware()`](deck-and-layout.md#tilt-labware) has left tilted, without sending anything to VENUS. Call `tilt_labware(labware_name, 0)` (and level the tilt module) first.

> **Split wells:** wells split with [`split_wells()`](deck-and-layout.md#split-wells) follow the plate. A transport removes the plate's slot racks and rebuilds them at the destination once it succeeds. A plate held by `*_present_and_scan` or `iswap_get_labware` gets them back on `*_return_plate` or `iswap_put_labware`. The to-waste transports remove them.

---

## CO-RE Transport

### Gripper and Transport Tools

The gripper tool must match the instrument's channel type. On a STAR, Fluid Motion channels take the QCG (`add_qcg()`) and Legacy channels take the CO-RE gripper (`add_1ml_core_grip()`); the SDK rejects the other one using the instrument configuration. The gripper `front_channel` parameter must be at least 2 for the CO-RE gripper and at least 4 for the QCG (Vantage, or Fluid Motion channels), and no more than the channel total. See [Connect-Time Validation](advanced/instrument_configuration.md#connect-time-validation-from-the-instrument-configuration).

Add and manage CO-RE gripper tools in the layout:

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import CoreGripType, QCGType

with StarClient() as star:
    star.instrument_init()
    # Add grippers to layout
    star.add_1ml_core_grip(grip_type=CoreGripType.STANDARD)
    star.add_5ml_core_grip()
    star.add_qcg(qcg_type=QCGType.QCG)

    # Get available transport tools
    tool_ids = star.get_transport_tool_ids()
    print(f"Available tools: {tool_ids}")

    # Get specific tool
    tool_info = star.get_transport_tool(tool_id=1)
```

### Plate Transport and Gripper Control

Transport plates using CO-RE grippers and check gripper status:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    star.core_transport(
        labware_name="MyPlate",
        carrier="PlateCarrier1",
        site="2",
        grip_height_above_bottom=8.0,
    )

    holding_result = star.core_transport_is_holding_labware()
    print(f"Gripper holding labware: {holding_result.return_parameters.is_holding_labware}")

    star.core_transport_return_plate(mode="return")

    star.core_transport_to_waste(
        labware_name="MyPlate",
        grip_height_above_bottom=8.0,
    )
```

### Barcode Scanning with CO-RE

> **STAR only.** Present-and-scan is not available on a Vantage; the SDK raises `VenusCommandUnsupportedError` there.

Transport plates to a barcode scanner position and capture the scanned barcode.

#### `core_present_and_scan()` — Transport and Scan Labware

Transport labware to a barcode scanner position and return the scanned barcode.

**Signature:**
```python
def core_present_and_scan(
    self,
    labware_name: str,
    carrier: str,
    site: str,
    grip_height_above_bottom: float,
    track: int,
    z_minimal_position: float,
    grip_width: float | None = None,
    grip_open: float | None = None,
    grip_force: int | None = None,
    x_acceleration: int | None = None,
    grip_close_speed: float | None = None,
    grip_z_speed: float | None = None,
    eject_grip: bool | None = None,
    check_presence: dict[str, bool] | None = None,
) -> TransportPresentAndScanResponse:
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `labware_name` | `str` | ✓ | Name of the labware to scan |
| `carrier` | `str` | ✓ | Carrier identifier containing the labware |
| `site` | `str` | ✓ | Site position on the carrier |
| `grip_height_above_bottom` | `float` | ✓ | Grip height above labware bottom (mm) |
| `track` | `int` | ✓ | Deck track ID for scan position |
| `z_minimal_position` | `float` | ✓ | Minimal Z position for scan (coordinates) |
| `grip_width` | `float \| None` | — | Grip width for the labware (mm). Auto-calculated if not provided. |
| `grip_open` | `float \| None` | — | Grip opening width (mm). Auto-calculated if not provided. |
| `grip_force` | `int \| None` | — | Grip force (optional) |
| `x_acceleration` | `int \| None` | — | X-axis acceleration (optional) |
| `grip_close_speed` | `float \| None` | — | Grip close speed (optional) |
| `grip_z_speed` | `float \| None` | — | Grip Z-axis speed (optional) |
| `eject_grip` | `bool \| None` | — | Whether to eject grip after operation (optional) |
| `check_presence` | `dict[str, bool] \| None` | — | Presence checks: `{"get": bool, "put": bool}` (optional) |

**Returns:** `TransportPresentAndScanResponse` with fields:
- `message: str` — Operation status message
- `barcode: str` — The scanned barcode value

**Example:**

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()

    # Transport a plate to the barcode scanner and capture the barcode
    result = star.core_present_and_scan(
        labware_name="plate_1",
        carrier="deep well carrier",
        site="3",
        grip_height_above_bottom=7.25,
        track=54,
        z_minimal_position=219,
        grip_force=5,
        x_acceleration=4,
        grip_close_speed=277.8,
        grip_z_speed=128.7,
        eject_grip=True,
        check_presence={"get": True, "put": True},
    )

    print(f"Status: {result.return_parameters.message}")
    print(f"Barcode: {result.return_parameters.barcode}")
```

### Complete CO-RE Transport Workflow

A comprehensive example combining deck setup, plate movement, and cleanup:

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LABWARE
from hamilton_venus.models.enums import CoreGripType

with StarClient() as star:
    star.instrument_init()

    # Set up deck with plates and grippers
    star.add_carrier(
        labware_definition=LABWARE.CARRIER.PLT_CAR_L5MD,
        left_track=1,
        labware_id="SourceCarrier",
    )

    star.add_plate(
        labware_definition=LABWARE.PLATE.COS_96_RD,
        carrier_id="SourceCarrier",
        site="1",
        plate_id="SourcePlate",
    )

    # Add gripper for transport
    star.add_1ml_core_grip(grip_type=CoreGripType.STANDARD)

    # Transport source plate to destination
    star.core_transport(
        labware_name="SourcePlate",
        carrier="DestinationCarrier",
        site="1",
        grip_height_above_bottom=7.5,
    )

    # Check if gripper is still holding the labware
    if star.core_transport_is_holding_labware().return_parameters.is_holding_labware:
        # Return it to original position
        star.core_transport_return_plate(mode="return")

    print("Transport workflow completed")
```

---

## 5 mL CO-RE Transport

The 5 mL channel arm has its own CO-RE gripper. Each `core_transport*` command has a
`core_5ml_transport*` counterpart that drives the 5 mL gripper. The parameters are identical
to the 1 mL commands (the underlying gripper is a single fixed tool, so `tool_id` is normally
omitted).

### Gripper Setup and Plate Transport

Add the 5 mL grip tool, then move plates and check gripper status:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()

    # Add the 5 mL CO-RE grip tool to the layout
    star.add_5ml_core_grip()

    star.core_5ml_transport(
        labware_name="MyPlate",
        carrier="PlateCarrier1",
        site="2",
        grip_height_above_bottom=8.0,
    )

    holding_result = star.core_5ml_transport_is_holding_labware()
    print(f"Gripper holding labware: {holding_result.return_parameters.is_holding_labware}")

    # Return the plate to its original position
    star.core_5ml_transport_return_plate(mode="return")

    # Or discard it to waste
    star.core_5ml_transport_to_waste(
        labware_name="MyPlate",
        grip_height_above_bottom=8.0,
    )
```

### Barcode Scanning with the 5 mL Gripper

Present labware to the scanner and capture the barcode, then eject the grips:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    star.add_5ml_core_grip()

    result = star.core_5ml_present_and_scan(
        labware_name="MyPlate",
        carrier="PlateCarrier1",
        site="3",
        grip_height_above_bottom=7.25,
        track=54,
        z_minimal_position=219,
    )
    print(f"Scanned barcode: {result.return_parameters.barcode}")

    # Grip and hold a lid with the 5 mL tool
    star.core_5ml_hold_lid(
        labware_name="MyPlate_lid",
        grip_height_from_top=5.0,
    )

    # Clear tracking state and release the grips when finished
    star.core_5ml_transport_tracking_clear()
    star.core_5ml_eject_grips()
```

### Available 5 mL Transport Commands

| Method | Action | Description |
| --- | --- | --- |
| `core_5ml_transport()` | `transport.5mL.moveLabware` | Move a plate to a carrier site |
| `core_5ml_present_and_scan()` | `transport.5mL.presentAndScan` | Present labware to the scanner and return its barcode |
| `core_5ml_transport_is_holding_labware()` | `transport.5mL.isHoldingLabware` | Report whether the gripper is holding a plate |
| `core_5ml_transport_tracking_clear()` | `transport.5mL.clearHeldLabware` | Reset the transport tracking state |
| `core_5ml_eject_grips()` | `transport.5mL.ejectGrips` | Eject the 5 mL grips |
| `core_5ml_transport_return_plate()` | `transport.5mL.returnLabware` | Return a held plate (`mode="return"` or `mode="new"`) |
| `core_5ml_transport_to_waste()` | `transport.5mL.moveToWaste` | Move a plate to the waste position |
| `core_5ml_hold_lid()` | `transport.5mL.holdLid` | Grip and hold a lid |

---

## iSWAP Transport

### Basic Plate Transport with iSWAP

Move a plate from one carrier site to another using iSWAP:

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import GripInverse, PlaceRotation

with StarClient() as star:
    star.instrument_init()
    # Transport a plate from source to destination carrier
    star.iswap_transport(
        labware_name="MyPlate",
        carrier="PlateCarrier1",
        site="1",
        grip_height_above_bottom=8.0,
        place_rotation=PlaceRotation.DEGREES_0,
        grip_inverse=GripInverse.GRIP_FROM_RIGHT,
    )
    print("Plate transported successfully")
```

**Parameters explained:**
- `labware_name`: Identifier of the plate to transport (must exist in layout)
- `carrier`: Destination carrier ID where plate will be placed
- `site`: Destination site on the carrier (typically `1`, `2`, `3`, etc.)
- `grip_height_above_bottom`: Height above plate bottom for gripper grip (mm)
- `place_rotation`: Rotation applied when placing labware — use `PlaceRotation` enum
- `grip_inverse`: Which side the gripper approaches from — use `GripInverse` enum

### PlaceRotation and GripInverse Enums

iSWAP-specific parameters that control placement orientation and grip direction accept
purpose-built enums that make intent clear:

#### `PlaceRotation` — Labware Orientation on Placement

| Enum member | API value | Description |
|---|---|---|
| `PlaceRotation.DEGREES_0` | `1` | No rotation |
| `PlaceRotation.DEGREES_90` | `2` | 90° clockwise |
| `PlaceRotation.DEGREES_180` | `3` | 180° (inverted) |
| `PlaceRotation.DEGREES_270` | `4` | 270° clockwise |

#### `GripInverse` — Gripper Approach Side

| Enum member | API value | Description |
|---|---|---|
| `GripInverse.GRIP_FROM_LEFT` | `True` | Gripper approaches from the left side |
| `GripInverse.GRIP_FROM_RIGHT` | `False` | Gripper approaches from the right side |

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import GripInverse, PlaceRotation

with StarClient() as star:
    star.instrument_init()

    # Place plate rotated 90° with gripper approaching from the left
    star.iswap_transport(
        labware_name="MyPlate",
        carrier="PlateCarrier1",
        site="1",
        grip_height_above_bottom=8.0,
        place_rotation=PlaceRotation.DEGREES_90,
        grip_inverse=GripInverse.GRIP_FROM_LEFT,
    )
```

Both enums are available on any iSWAP command that supports the corresponding parameter:
`iswap_transport`, `iswap_transport_to_waste`, `iswap_present_and_scan` (STAR only), `iswap_get_labware`,
and `iswap_put_labware`.

### Grip Width: Narrow or Wide Grip

`grip_width` and `grip_inverse` pick how the iSWAP holds the labware, in every plain iSWAP move
(`iswap_transport`, `iswap_transport_to_waste`, `iswap_present_and_scan`, `iswap_get_labware`); no complex
movement needed. For labware at rotation 0:

| `grip_width` | Grip | `GRIP_FROM_RIGHT` (default): the iSWAP faces | `GRIP_FROM_LEFT`: the iSWAP faces |
|---|---|---|---|
| below 100 mm, e.g. `80.0` (open `85.0`) | narrow, across the plate's 85.5 mm width | left | right |
| 100 mm or more, e.g. `124.0` (open `127.0`) | wide, across the plate's 127.8 mm length | the back | the front |

Left out, `grip_width` is calculated from the labware definition.

```python
# Wide grip from the rear: the iSWAP faces the front of the instrument
star.iswap_get_labware(
    labware_name="AssayPlate",
    grip_height_above_bottom=7.6,
    grip_width=124.0,
    grip_open=127.0,
    grip_inverse=GripInverse.GRIP_FROM_LEFT,
)
```

### The iSWAP Get/Put Workflow

One of the unique features of iSWAP is the ability to separate the **get** (pickup) and **put** (placement) operations. This allows for more complex workflows:

#### Pick Up Labware Without Placing

Pick up a labware item without immediately placing it:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()

    # Pick up plate without placing it yet
    star.iswap_get_labware(
        labware_name="SourcePlate",
        grip_height_above_bottom=8.0,
    )
    print("Plate picked up - ready for processing")

    # Do some work or decisions here...
    print("Processing or analysis step...")

    # Now place it at destination
    star.iswap_put_labware(
        carrier="DestinationCarrier",
        site="1",
    )
    print("Plate placed at destination")
```

This workflow is useful for:
- Conditional placement based on analysis results
- Complex routing logic
- Integration with external systems
- Multi-step workflows

#### Hotels: Complex Movement

To get from or put into a hotel, use the complex-movement variants. `orientation` is the direction the iSWAP
faces, toward the hotel; it reaches `retract_distance` mm into the hotel and lifts or lowers the plate by
`lift_height` mm. Get and put can be mixed: get from a carrier site with `iswap_get_labware`, then put into a
hotel with `iswap_put_labware_complex_movement`.

The plate turns with the iSWAP. After a plain get the iSWAP faces as in
[Grip Width](#grip-width-narrow-or-wide-grip); after a complex get, its `orientation`. A put facing another
way needs the matching place rotation, or VENUS fails with "Complex movement for iSWAP not possible. The labware
orientation doesn't match the iSWAP's grip direction":

| Gripped facing | Put `orientation` | Place rotation |
|---|---|---|
| the same way | same | 0° |
| the opposite way (e.g. back, then front) | opposite | 180° |
| a quarter turn (e.g. left, then front) | 90° away | 90° or 270° |

`iswap_put_labware_complex_movement` sends that rotation itself when `place_rotation` is left out and the get
before it (from the same client) either set `grip_width` or used complex movement. Pass `place_rotation` to
override it. A quarter turn also needs a site that fits the plate turned 90°: from a landscape carrier (`PLT_CAR_L5…`)
into a portrait one (`PLT_CAR_P3…`), or the other way round. Put into a site of the same kind, VENUS fails
with "Invalid placement of labware".
The hotel must also be reachable from that side; if not, VENUS reports "Cannot reach the defined position".

```python
from hamilton_venus import StarClient
from hamilton_venus.models.enums import CMOrientation, GripInverse

with StarClient() as star:
    star.instrument_init()

    # From a carrier site into a front hotel without turning the plate: a wide grip
    # from the rear faces the front, so the put needs no rotation (0° is sent)
    star.iswap_get_labware(
        labware_name="AssayPlate",
        grip_height_above_bottom=7.6,
        grip_width=124.0,
        grip_open=127.0,
        grip_inverse=GripInverse.GRIP_FROM_LEFT,
    )
    star.iswap_put_labware_complex_movement(
        carrier="FrontHotel",
        site="1",
        retract_distance=139.0,
        lift_height=35.0,
        orientation=CMOrientation.FRONT,
    )

    # And back out of the hotel onto the carrier
    star.iswap_get_labware_complex_movement(
        labware_name="AssayPlate",
        grip_height_above_bottom=7.6,
        grip_width=124.0,
        grip_open=127.0,
        retract_distance=139.0,
        lift_height=35.0,
        orientation=CMOrientation.FRONT,
    )
    star.iswap_put_labware(carrier="PlateCarrier", site="1")
```

### Checking iSWAP Gripper State

Check current iSWAP gripper status before attempting transport:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    holding_result = star.iswap_is_holding_labware()

    if holding_result.return_parameters.is_holding_labware:
        print("Gripper already has labware - clear it first")
        star.iswap_park()
        star.iswap_tracking_clear()
    else:
        print("Gripper is empty - ready for next plate")
        # Proceed with transport...
```

### iSWAP Transport Modes

#### Transport to Waste

Move the currently-held plate to waste collection:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()

    star.iswap_transport_to_waste(
        labware_name="MyPlate",
        grip_height_above_bottom=8.0,
    )
    print("Plate moved to waste")
```

### Barcode Scanning with iSWAP

> **STAR only.** Present-and-scan is not available on a Vantage; the SDK raises `VenusCommandUnsupportedError` there.

Transport labware to a barcode scanner position and capture the scanned barcode:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()

    # Transport to scanner and capture barcode
    result = star.iswap_present_and_scan(
        labware_name="plate_1",
        carrier="deep well carrier",
        site="3",
        grip_height_above_bottom=7.25,
        track=54,
        z_minimal_position=219,
    )

    print(f"Status: {result.return_parameters.message}")
    print(f"Barcode: {result.return_parameters.barcode}")
```

### Managing iSWAP Gripper State

#### Park the iSWAP

Return the iSWAP to its parked position:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    star.iswap_park()
    print("iSWAP parked and ready")
```

#### Clear iSWAP Tracking

Eject gripper and reset transport tracking:

```python
from hamilton_venus import StarClient

with StarClient() as star:
    star.instrument_init()
    star.iswap_tracking_clear()
    print("iSWAP tracking reset")
```

---

## See Also

- [Advanced Transport and Gripper Workflows](./advanced/transport_workflows.md) — Advanced patterns for both CO-RE and iSWAP
- [Gripper Setup and Layout Management](./advanced/gripper_operations.md) — Gripper configuration and deck layout
- [API Reference](../star-commands.md) — Full API reference


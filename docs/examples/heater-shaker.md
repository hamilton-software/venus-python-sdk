# Heater Shaker (HHS)

Guide for controlling Hamilton Heater Shaker (HHS) devices — plate locking, shaking, and temperature control.

---

## Overview

This guide covers:
- Registering HHS devices connected via STAR node or USB
- Locking and unlocking plates
- Starting, stopping, and waiting on the shaker
- Starting, stopping, and waiting on temperature control
- Reading device status and terminating the connection

---

## Fundamental Concepts

Before issuing any control command, an HHS device must be registered so the runtime knows how it is connected:

- `hhs_create_star_device(node)` — for an HHS wired through a STAR node (`node` 1-2).
- `hhs_create_usb_device(node)` — for an HHS connected via USB (`node` 1-8).

Each registration returns a `device_id`. Control commands accept an optional `device_id`; when omitted, the command applies to **all** registered devices.

---

## Basic Operations

### Register a Device

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	created = star.hhs_create_usb_device(node=1)
	device_id = created.return_parameters.device_id
	print(f"Registered HHS device {device_id}")
```

### Lock and Unlock the Plate

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	star.hhs_set_plate_lock(lock=True, device_id=1)
	print("Plate locked")

	star.hhs_set_plate_lock(lock=False, device_id=1)
	print("Plate unlocked")
```

### Shake for a Fixed Duration

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	# Shake at 1000 RPM for 30 seconds
	star.hhs_start_shaker(speed=1000, time=30, device_id=1)

	# Block until the shaker has stopped
	result = star.hhs_wait_for_shaker(device_id=1)
	print(f"Shaking stopped at {result.return_parameters.shaking_stopped}")
```

### Shake Indefinitely and Stop Manually

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	# time=0 shakes indefinitely
	star.hhs_start_shaker(speed=800, time=0, device_id=1)

	# ... perform other work ...

	stopped = star.hhs_stop_shaker(device_id=1)
	print(f"Shaking stopped at {stopped.return_parameters.shaking_stopped}")
```

### Control Temperature

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	star.hhs_start_temp_control(temperature=37.0, device_id=1)

	# Block until temperature control ends
	star.hhs_wait_for_temp_control(device_id=1)

	star.hhs_stop_temp_control(device_id=1)
```

---

## Querying State

### List Registered Devices

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	devices = star.hhs_get_device_ids()
	for device in devices.return_parameters.device_ids:
		print(
			f"Device {device.device_id}: node={device.node}, "
			f"usb={device.connect_usb}, sn={device.serial_number}, "
			f"fw={device.firmware_version}"
		)
```

### Read Shaking and Temperature Status

```python
from hamilton_venus import StarClient

with StarClient() as star:
	star.instrument_init()

	status = star.hhs_get_status()
	for device in status.return_parameters.device_ids:
		print(
			f"Device {device.device_id}: {device.shaking_speed} RPM, "
			f"{device.temperature} °C — {device.temp_control_status}"
		)
```

---

## Production Pattern: Incubate While Shaking

Lock the plate, run a timed shake at a controlled temperature, then release:

```python
import logging
from hamilton_venus import StarClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def incubate_with_shaking(
	star: StarClient,
	device_id: int,
	speed: int,
	seconds: int,
	temperature: float,
) -> None:
	"""Lock, temperature-control, shake for a fixed time, then unlock."""
	star.hhs_set_plate_lock(lock=True, device_id=device_id)
	star.hhs_start_temp_control(temperature=temperature, device_id=device_id)
	logger.info("Shaking device %d at %d RPM for %d s", device_id, speed, seconds)
	star.hhs_start_shaker(speed=speed, time=seconds, device_id=device_id)
	star.hhs_wait_for_shaker(device_id=device_id)
	star.hhs_stop_temp_control(device_id=device_id)
	star.hhs_set_plate_lock(lock=False, device_id=device_id)
	logger.info("Incubation complete for device %d", device_id)


with StarClient() as star:
	star.instrument_init()

	created = star.hhs_create_usb_device(node=1)
	incubate_with_shaking(
		star,
		device_id=created.return_parameters.device_id,
		speed=1000,
		seconds=300,
		temperature=37.0,
	)

	star.hhs_terminate()
```

---

## Heater Shaker API Reference

| Method | Returns | Description |
|--------|---------|-------------|
| `hhs_create_star_device(node)` | `HHSCreateDeviceResponse` | Register an HHS on a STAR node (1-2) |
| `hhs_create_usb_device(node)` | `HHSCreateDeviceResponse` | Register a USB-connected HHS (node 1-8) |
| `hhs_get_device_ids()` | `HHSDeviceIdsResponse` | List registered devices and metadata |
| `hhs_get_status()` | `HHSStatusResponse` | Read shaking speed and temperature status |
| `hhs_set_plate_lock(lock, device_id=None)` | `HHSPlateLockResponse` | Lock/unlock the plate |
| `hhs_start_shaker(speed, time=0, device_id=None)` | `HHSShakingStartedResponse` | Start shaking (30-2500 RPM, 0 s = indefinite) |
| `hhs_stop_shaker(device_id=None)` | `HHSShakingStoppedResponse` | Stop shaking |
| `hhs_wait_for_shaker(device_id=None)` | `HHSShakingStoppedResponse` | Block until shaking stops |
| `hhs_start_temp_control(temperature, device_id=None)` | `HHSTempControlStartedResponse` | Start temperature control (°C) |
| `hhs_stop_temp_control(device_id=None)` | `HHSTempControlStoppedResponse` | Stop temperature control |
| `hhs_wait_for_temp_control(device_id=None)` | `HHSTempControlStoppedResponse` | Block until temperature control stops |
| `hhs_terminate()` | `MessageResponse` | Disconnect all HHS devices |

`device_id` is optional on all control commands; when omitted the command applies to every registered device.

---

## See Also

- [`../star-commands.md`](../star-commands.md) — Full API reference

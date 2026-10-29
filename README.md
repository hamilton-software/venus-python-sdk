# Hamilton VENUS Python SDK

Provides a Python interface for programming Hamilton automated-liquid-handling instruments through the VENUS software platform.

## Installation

> **Not available from PyPI yet.** The command below is a placeholder for when `hamilton-venus-sdk` is published. Until then, clone this repository and install locally using the development instructions below.

```bash
pip install hamilton-venus-sdk
```

### Development Installation

```bash
pip install -e ".[dev]"
```

### Setup Helpers

After installing, run the helper CLI to set up the additional files required by the SDK.

It is recommended to run all `setup-venus-sdk` commands from an elevated Administrator terminal (Run as Administrator).

Start with --help to see all available options and defaults:

```bash
setup-venus-sdk --help
```

Common commands:

```bash
# Full setup — runs prerequisite installers, copies SDK_MethodStructure to Program Files,
# and generates liquid class catalog from VENUS
setup-venus-sdk

# Show interactive prompts for all options instead of using defaults
setup-venus-sdk --prompt

# Prerequisites only
setup-venus-sdk --skip-structure

# SDK structure copy only
setup-venus-sdk --skip-prereqs

# Skip liquid class catalog generation
setup-venus-sdk --skip-catalog

# Download and install the private 32-bit Python + pywin32 runtime (Heater/Cooler,
# Inheco TEC and ODTC drivers on 64-bit Python)
setup-venus-sdk --install-py32

# Same, from a local folder with the pinned files instead of downloading (offline PC)
setup-venus-sdk --install-py32 --py32-from D:\py32-offline

# Preview what would happen without making any changes
setup-venus-sdk --dry-run

# Force overwrite existing files
setup-venus-sdk --force
```

### Uninstalling

`uninstall-venus-sdk` is a console script provided by this package, so it stops being available
once the package itself is removed. Run it *before* uninstalling the package, in this order:

1. `uninstall-venus-sdk` (with whichever options you need) to remove the SDK folder structure,
   registry registration, and prerequisites.
2. `pip uninstall hamilton-venus-sdk` to remove the package itself.

To remove the SDK folder structure and registry registration created by `setup-venus-sdk`, run:

```bash
uninstall-venus-sdk --help
```

Common commands:

```bash
# Remove SDK structure files and the SDK registry key
uninstall-venus-sdk

# Preview what would be removed without making any changes
uninstall-venus-sdk --dry-run

# Leave the SDK registry key in place
uninstall-venus-sdk --keep-registry

# Keep the prerequisite executables listed in the manifest (uninstalled by default)
uninstall-venus-sdk --keep-prereqs

# Keep the 32-bit COM runtime installed by --install-py32 (removed by default)
uninstall-venus-sdk --keep-py32

# Run prerequisite uninstallers silently
uninstall-venus-sdk --headless

# Show a confirmation prompt before making changes
uninstall-venus-sdk --prompt
```

When prerequisites are uninstalled interactively (i.e. without `--headless`), each uninstaller's
window is shown one at a time: the tool pauses and waits for you to press Enter after closing a
window before launching the next uninstaller, so their windows don't stack on top of each other.
Pass `--headless` to skip these windows and prompts entirely and uninstall prerequisites silently.

### Liquid Class Catalog Generation

The setup process automatically pulls liquid class definitions from the instrument database and generates the static catalog. To regenerate the catalog later (e.g., after adding new liquid classes to VENUS), use:

```bash
# Pull liquid classes from VENUS and regenerate catalog
venus-sdk generate-catalog

# With debug logging
venus-sdk generate-catalog --debug

# Skip labware catalog generation (only generate liquid classes)
venus-sdk generate-catalog --skip-labware
```

This command connects to VENUS in simulation mode, retrieves all available liquid class definitions, and generates the static catalog at `src/hamilton_venus/catalog/liquid_classes.py`.

## Quick Start

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog.liquid_classes import LIQUID_CLASSES

liquid_class = LIQUID_CLASSES["STANDARDVOLUME_WATER_DISPENSEJET_EMPTY"]

with StarClient(deck_name="example_deck") as star:

    star.instrument_init()

    star.tip_pickup(tip_pool="transfer_tips")
    star.aspirate(positions="source_plate@col:1", volumes=50.0, liquid_class=liquid_class)
    star.dispense(positions="dest_plate@col:1", volumes=50.0)
    star.tip_eject()
```

For reusable liquid-handling defaults, see [docs/examples/liquid-handling.md](docs/examples/liquid-handling.md) for complete examples.

## Documentation

| Guide | Description |
|-------|-------------|
| [Documentation Index](docs/README.md) | Full navigable index of all guides |
| [Authentication](docs/authentication.md) | Auth modes, credentials, TLS, and token lifecycle |
| [Configuration](docs/configuration.md) | TOML file, environment variables, and programmatic config |
| [Error Handling](docs/error_handling.md) | Error profiles, recovery actions, and operator escalation |
| [Static Catalogs](docs/static-catalogs.md) | Generated LABWARE/LIQUID_CLASSES constants and catalog regeneration |
| [Star Commands](docs/star-commands.md) | Full reference of all supported instrument commands |
| [Examples](docs/examples/) | Practical usage examples for common workflows |

### Configuration

The SDK loads configuration from a TOML file. Set the ``HAMILTON_VENUS_CONFIG``
environment variable or place a ``hamilton_venus.toml`` file in your working
directory:

```toml
[venus]
base_url = "http://localhost:42400"

[venus.timeouts]
command = 300.0 
```

See [docs/configuration.md](docs/configuration.md) for the full TOML reference,
environment variable overrides, and all config dataclass fields (timeouts,
network, auth, TLS, run log, and more).

### Authentication

The SDK auto-detects the VENUS authentication mode at connect time. No
configuration is needed for unauthenticated environments. For secure endpoints,
provide credentials via environment variables, TOML, or `AuthConfig`. See
[docs/authentication.md](docs/authentication.md) for the full setup guide,
TLS configuration, token lifecycle details, and troubleshooting.

## Build and Test

```bash
# Run tests
pytest

# Run linter
ruff check src/ tests/

# Run type checker
mypy src/
```

## Smoke Tests

Manual integration tests that run against a real Hamilton VENUS environment (not executed by CI).

```bash
python smoke_tests/star/test_star_sample_transfer.py
```

See [smoke_tests/README.md](smoke_tests/README.md) for more details.

## Requirements

- Python 3.11+
- VENUS WebAPI running on instrument PC (default: `http://localhost:42400`)

## Project Links

| Resource | Location |
|----------|----------|
| Source (GitHub) | [hamilton-venus-sdk](https://github.com/HamiltonCompany/hamilton-venus-sdk) |
| Package (PyPI) | [hamilton-venus-sdk](https://pypi.org/project/hamilton-venus-sdk/) |

## Contributing & Support
This SDK is open-source but it is not open-development. We do not currently accept pull requests or track bug reports in this repository.

For any issues or support requests, contact Hamilton.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

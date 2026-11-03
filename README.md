# Hamilton VENUS Python SDK

Provides a Python interface for programming Hamilton automated-liquid-handling instruments through the VENUS software platform.

## Requirements

- Windows machine with Hamilton VENUS installed. The SDK talks to the VENUS WebAPI.
- Python 3.12+ (the SDK alone runs on 3.11; the apps and the installer need 3.12)

## Installation

Install [Git LFS](https://git-lfs.com) first: the desktop apps and the installer are stored with it. Then clone this repository wherever you want the SDK to live, and run the installer from it:

```powershell
git lfs install
git clone <repository url> venus-python-sdk
cd venus-python-sdk
.\VenusPythonSdkInstaller.exe
```

That folder is the install: nothing is copied out of it. Choose what to install and, if you want, a different Python environment (the default is a `.venv` in the folder). The desktop apps are ready to open in `tools\Hamilton ...\`, each with its guide. To update, run `git pull` and re-run the installer.

**PyPI:** Coming soon.

### Development Installation

To work on the SDK itself without the installer, clone this repository (see [Project Links](#project-links)), then install it in editable mode from the repository root. Using a virtual environment is recommended:

```powershell
python -m venv .venv
.venv\Scripts\activate
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

# Print the setup plan and ask for confirmation before making changes
setup-venus-sdk --prompt

# Show the prerequisite installer windows instead of installing silently
setup-venus-sdk --interactive

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

### First Test Run (VENUS Simulation Mode)

After setup completes, a simulated run is a good way to check that the installation worked. VENUS simulation mode drives a simulated instrument, so no hardware or deck setup is needed:

```python
from hamilton_venus import StarClient

with StarClient(simulate=True) as star:
    star.instrument_init()
    print("Connected to VENUS in simulation mode")
```

Run the same script with `simulate=False` (or omit the flag) to drive a real instrument. On real hardware, `instrument_init()` moves the instrument, so make sure the deck is clear and safe first.

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

The setup process automatically pulls liquid class definitions from the instrument database and generates the static labware and liquid class catalogs. To regenerate the catalogs later (e.g., after adding new liquid classes or labware to VENUS), use:

```bash
# Pull liquid classes from VENUS and regenerate catalog
venus-sdk generate-catalog

# With debug logging
venus-sdk generate-catalog --debug

# Skip labware catalog generation (only generate liquid classes)
venus-sdk generate-catalog --skip-labware
```

This command connects to VENUS in simulation mode, retrieves all available liquid class definitions, and regenerates the catalog modules (`labware.py`, `liquid_classes.py`) in the installed package's `hamilton_venus/catalog/` folder (`src/hamilton_venus/catalog/` for a development install).

## Quick Start

This example loads a saved deck named `example_deck` that contains a tip pool named `transfer_tips` and plates named `source_plate` and `dest_plate`. Build and save that deck first (see [docs/examples/deck_and_layout.md](docs/examples/deck_and_layout.md) and `deck_save(...)`), or adjust the names to match your own saved deck.

```python
from hamilton_venus import StarClient
from hamilton_venus.catalog import LIQUID_CLASSES

liquid_class = LIQUID_CLASSES.STAR.STANDARDVOLUME_WATER_DISPENSEJET_EMPTY

with StarClient(deck_name="example_deck", simulate=True) as star:

    star.instrument_init()

    star.tip_pickup(tip_pool="transfer_tips")
    star.aspirate(positions="source_plate@col:1", volumes=50.0, liquid_class=liquid_class)
    star.dispense(positions="dest_plate@col:1", volumes=50.0)
    star.tip_eject()
```

For reusable liquid-handling defaults, see [docs/examples/liquid_handling.md](docs/examples/liquid_handling.md) for complete examples. New to the SDK? Start with [docs/examples/getting_started.md](docs/examples/getting_started.md), which covers the connection lifecycle and simulation mode.

## Documentation

| Guide | Description |
|-------|-------------|
| [Documentation Index](docs/README.md) | Full navigable index of all guides |
| [Getting Started](docs/examples/getting_started.md) | Connecting, initializing, and the basic workflow lifecycle |
| [Authentication](docs/authentication.md) | Auth modes, credentials, TLS, and token lifecycle |
| [Configuration](docs/configuration.md) | TOML file, environment variables, and programmatic config |
| [Error Handling](docs/error_handling.md) | Error profiles, recovery actions, and operator escalation |
| [Static Catalogs](docs/static_catalogs.md) | Generated LABWARE/LIQUID_CLASSES constants and catalog regeneration |
| [Star Commands](docs/star_commands.md) | Full reference of all supported instrument commands |
| [Vantage Commands](docs/vantage_commands.md) | Full reference of all supported Vantage commands |
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

Manual integration tests that run against a real Hamilton VENUS environment (not executed by CI). Start with the connect test for each client, then run broader examples as needed:

```bash
python smoke_tests/star/test_star_connect.py
python smoke_tests/vantage/test_vantage_connect.py
```

See [smoke_tests/README.md](smoke_tests/README.md) for prerequisites (e.g. a saved deck named `example_deck`) and the full list.

## Project Links

| Resource | Location |
|----------|----------|
| Source (GitHub) | [venus-python-sdk](https://github.com/hamilton-software/venus-python-sdk) |
| Package (PyPI) | Coming soon |

##  Support & Discussions

We do not accept public contributions, issues, or bug reports on this GitHub repository.

To report bugs, ask questions, or engage with the community, please join our official corporate discussion platform:

**[Join the Hamilton Robotics Discussion Platform](https://discourse.hamiltoncompany.com/c/our-software/python-sdk)**

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

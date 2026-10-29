# Smoke Tests

Manual integration tests that run against a real Hamilton VENUS installation.
These are **not** executed by CI — they require an installed VENUS environment.

The smoke tests are intentionally written as direct SDK usage examples. Each script shows a small, runnable flow that a user could adapt in their own code.

## Dual Purpose: Testing + Examples

Smoke tests serve **double duty**:

1. **Integration Testing** — Verify SDK works correctly with VENUS backend
2. **Usage Examples** — Demonstrate real-world workflows you can adapt

You can adapt any smoke test as a starting point for your own scripts.


## Prerequisites

- Windows machine with Hamilton VENUS installed
- The SDK installed (`pip install -e .` from the repo root)
- A saved deck named `example_deck` containing the labware referenced by many
  of the scripts.

## Structure

Tests are organized by instrument client:

```
smoke_tests/
  star/      — StarClient tests
  vantage/   — VantageClient tests
```

## Running

Each smoke test is a standalone script. Run them directly:

```
python smoke_tests/star/test_star_connect.py
python smoke_tests/vantage/test_vantage_connect.py
```

All scripts use the default SDK configuration (executor HSL path, base URL, etc.). To override settings, place a `hamilton_venus.toml` config file in the working directory or point the `HAMILTON_VENUS_CONFIG` environment variable at a custom config file. See the main SDK documentation for config file format.

Start with the `connect` test for each client for the fastest validation, then run the broader examples as needed.

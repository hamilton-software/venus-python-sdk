# Copilot Instructions

## Project Guidelines
- Prefer American English spelling conventions in code and identifiers, for example use 'normalized' instead of 'normalised'.
- Always ensure all code changes comply with the ruff linter before submitting. Run ruff checks on modified files to catch and fix any issues (import ordering, line length, style violations, etc.) proactively without requiring the user to ask for fixes afterward.
- Prefer smoke tests to read as direct user-facing SDK usage examples rather than using extra scenario abstractions (not applicable to unit tests).
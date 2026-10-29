"""Built-in error handling profiles for common use cases.

This module provides pre-configured ErrorProfile instances that represent
common error handling strategies. Each profile can be used as-is or extended
using the with_overrides() method to create customized profiles.

Profiles are loaded from JSON configuration files located in the profiles/
directory, making them discoverable and editable by non-programmers.

Standard lab run profile: full per-error-type recovery rules.
Per-error-type entries are defined for tip_pickup, aspirate, and dispense
operations. All other operations fall back to the top-level default.
Recovery actions are ordered by attempt preference: the first action is tried
first, and subsequent actions are attempted if the prior action is exhausted
or disabled. max_retries controls the number of times an action can be
attempted before moving to the next action or giving up.
"""

from pathlib import Path
from types import MappingProxyType

from hamilton_venus.error_handling.profile import ErrorProfile
from hamilton_venus.error_handling.profile_loaders import profile_from_json_file


def _load_profile(profile_name: str) -> ErrorProfile:
    """Load an error profile from JSON file.

    Parameters
    ----------
    profile_name : str
        Name of the profile without .json extension (e.g., 'standard').

    Returns
    -------
    ErrorProfile
        The loaded error profile.

    Raises
    ------
    RuntimeError
        If the profile file is not found or cannot be parsed.
    """
    profile_path = Path(__file__).parent / "profiles" / f"{profile_name}.json"
    if not profile_path.exists():
        raise RuntimeError(
            f"Profile '{profile_name}' not found at {profile_path}. "
            f"Available profiles are in: {profile_path.parent}"
        )
    try:
        return profile_from_json_file(str(profile_path))
    except Exception as e:
        raise RuntimeError(
            f"Failed to load profile '{profile_name}' from {profile_path}: {e}"
        ) from e


STANDARD_PROFILE = _load_profile("standard")
BUILTIN_ERROR_PROFILES: MappingProxyType[str, ErrorProfile] = MappingProxyType({
    "standard": STANDARD_PROFILE,
})
BUILTIN_ERROR_PROFILE_NAMES: frozenset[str] = frozenset(BUILTIN_ERROR_PROFILES)

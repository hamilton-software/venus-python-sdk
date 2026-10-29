from __future__ import annotations

import os
from pathlib import Path


def find_sdk_root() -> Path:
    configured_root = os.environ.get("HAMILTON_VENUS_SDK_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()

    package_root = Path(__file__).resolve().parents[2]
    cwd = Path.cwd().resolve()

    candidates = [cwd, *cwd.parents, package_root, *package_root.parents]
    seen: set[Path] = set()
    for root in candidates:
        if root in seen:
            continue
        seen.add(root)
        if (root / "prerequisites").exists() and (root / "sdk_method_structure").exists():
            return root

    return package_root

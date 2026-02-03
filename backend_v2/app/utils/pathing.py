from __future__ import annotations

from pathlib import Path


def safe_join(root: Path, *parts: str) -> Path:
    candidate = root.joinpath(*parts).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Path traversal detected")
    return candidate

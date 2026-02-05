from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.models.base import VarSpec, normalize_selectors


def test_normalize_selectors_mapping() -> None:
    selectors = normalize_selectors({"typeOfLevel": "surface"})
    assert selectors.filter_by_keys == {"typeOfLevel": "surface"}
    assert selectors.search == []


def test_varspec_normalizes_selectors() -> None:
    spec = VarSpec(id="t2m", name="2m Temperature", selectors={"level": "2"})
    assert spec.selectors.filter_by_keys["level"] == "2"

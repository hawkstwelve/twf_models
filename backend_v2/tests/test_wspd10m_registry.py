from __future__ import annotations

from app.services.colormaps_v2 import VAR_SPECS
from app.services.variable_registry import herbie_search_for, normalize_api_variable


def test_wspd10m_var_specs_present() -> None:
    assert "wspd10m" in VAR_SPECS
    spec = VAR_SPECS["wspd10m"]
    assert spec["type"] == "continuous"
    assert spec["units"] == "mph"


def test_wspd10m_variable_registry_mapping() -> None:
    assert normalize_api_variable("wspd10m") == "10si"
    assert herbie_search_for("wspd10m") is not None

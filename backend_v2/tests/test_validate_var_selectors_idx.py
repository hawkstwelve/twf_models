from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.models import get_model
from scripts import validate_var_selectors_idx as validator


def test_parse_run_datetime_accepts_scheduler_run_id() -> None:
    run_dt = validator._parse_run_datetime("20260206_06z")
    assert isinstance(run_dt, datetime)
    assert run_dt.strftime("%Y%m%d%H") == "2026020606"


def test_selector_patterns_fallback_splits_pipe() -> None:
    class _Spec:
        class selectors:
            search: list[str] = []

    patterns = validator._selector_patterns_for_var("gfs", "wspd10m", _Spec())
    assert ":UGRD:10 m above ground:" in patterns
    assert ":VGRD:10 m above ground:" in patterns


def test_selector_patterns_fallback_without_varspec() -> None:
    patterns = validator._selector_patterns_for_var("hrrr", "10u", None)
    assert patterns == [":UGRD:10 m above ground:"]


def test_component_vars_for_derived_wspd10m() -> None:
    plugin = get_model("gfs")
    spec = plugin.get_var("wspd10m")
    assert spec is not None
    assert validator._component_vars_for_derived(spec) == ("10u", "10v")


def test_component_vars_for_derived_radar_ptype_combo() -> None:
    plugin = get_model("hrrr")
    spec = plugin.get_var("radar_ptype")
    assert spec is not None
    assert validator._component_vars_for_derived(spec) == (
        "refc",
        "crain",
        "csnow",
        "cicep",
        "cfrzr",
    )


def test_filter_inventory_df_applies_level_and_type_hint() -> None:
    df = pd.DataFrame(
        [
            {"level": "10 m above ground"},
            {"level": "2 m above ground"},
            {"level": "surface"},
        ]
    )
    filtered = validator._filter_inventory_df(
        df,
        {
            "typeOfLevel": "heightAboveGround",
            "level": "10",
        },
    )
    assert len(filtered.index) == 1
    assert filtered.iloc[0]["level"] == "10 m above ground"

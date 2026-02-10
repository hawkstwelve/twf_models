from __future__ import annotations

from pathlib import Path

import pytest

from app.models import get_model
from app.services.model_scheduler_v2 import (
    ConfigError,
    _build_script_path_for_model,
    _promotion_fhs_for_cycle,
    _resolve_regions_for_cli,
    _scheduled_targets_for_cycle,
)


def test_build_script_path_for_model() -> None:
    gfs_script = _build_script_path_for_model("gfs")
    hrrr_script = _build_script_path_for_model("hrrr")

    assert gfs_script.name == "build_cog.py"
    assert hrrr_script.name == "build_cog.py"


def test_resolve_regions_for_cli_accepts_explicit_region_without_existing_root(tmp_path: Path) -> None:
    out_root = tmp_path / "data"
    resolved = _resolve_regions_for_cli("gfs", out_root, "pnw")
    assert resolved == ["pnw"]


def test_resolve_regions_for_cli_requires_region_when_root_missing(tmp_path: Path) -> None:
    out_root = tmp_path / "data"
    with pytest.raises(ConfigError):
        _resolve_regions_for_cli("gfs", out_root, None)


def test_promotion_fhs_follow_model_policy() -> None:
    gfs = get_model("gfs")
    hrrr = get_model("hrrr")

    assert _promotion_fhs_for_cycle(gfs, 6) == [0, 6, 12]
    assert _promotion_fhs_for_cycle(hrrr, 18) == [0, 1, 2]


def test_scheduled_targets_skip_gfs_qpf6h_fh0() -> None:
    gfs = get_model("gfs")

    targets = _scheduled_targets_for_cycle(gfs, ["tmp2m", "qpf6h"], 6)

    assert ("tmp2m", 0) in targets
    assert ("qpf6h", 0) not in targets
    assert ("qpf6h", 6) in targets


def test_scheduled_targets_filter_unsupported_radar_ptype_for_gfs_but_keep_hrrr() -> None:
    gfs = get_model("gfs")
    hrrr = get_model("hrrr")
    shared_vars = ["tmp2m", "wspd10m", "refc", "qpf6h", "precip_ptype", "radar_ptype"]

    gfs_targets = _scheduled_targets_for_cycle(gfs, shared_vars, 6)
    gfs_vars = {var for var, _fh in gfs_targets}
    assert "radar_ptype" not in gfs_vars
    assert {"tmp2m", "wspd10m", "refc", "qpf6h", "precip_ptype"} <= gfs_vars

    hrrr_targets = _scheduled_targets_for_cycle(hrrr, shared_vars, 6)
    hrrr_vars = {var for var, _fh in hrrr_targets}
    assert "radar_ptype" in hrrr_vars

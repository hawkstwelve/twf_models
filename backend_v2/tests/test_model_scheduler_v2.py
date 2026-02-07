from __future__ import annotations

from pathlib import Path

import pytest

from app.models import get_model
from app.services.model_scheduler_v2 import (
    ConfigError,
    _build_script_path_for_model,
    _promotion_fhs_for_cycle,
    _resolve_regions_for_cli,
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

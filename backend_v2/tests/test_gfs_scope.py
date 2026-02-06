from __future__ import annotations

from app.models.gfs import GFS_INITIAL_FHS, GFS_INITIAL_ROLLOUT_REGIONS, GFS_REGIONS


def test_gfs_initial_regions_scope() -> None:
    assert "pnw" in GFS_REGIONS
    assert "conus" in GFS_REGIONS
    assert GFS_INITIAL_ROLLOUT_REGIONS == ("pnw",)


def test_gfs_initial_fhs_scope() -> None:
    assert GFS_INITIAL_FHS[0] == 0
    assert GFS_INITIAL_FHS[-1] == 120
    assert all(value % 6 == 0 for value in GFS_INITIAL_FHS)

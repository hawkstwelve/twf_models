from __future__ import annotations

from pathlib import Path

from app.services.hrrr_fetch import ensure_latest_cycles
from app.services.hrrr_runs import HRRRCacheConfig
from app.services.variable_registry import normalize_api_variable, select_dataarray

from .base import BaseModelPlugin, RegionSpec, VarSelectors, VarSpec


class HRRRPlugin(BaseModelPlugin):
    def target_fhs(self, cycle_hour: int) -> list[int]:
        if cycle_hour in {0, 6, 12, 18}:
            return list(range(0, 49))
        return list(range(0, 19))

    def normalize_var_id(self, var_id: str) -> str:
        normalized = normalize_api_variable(var_id)
        if normalized in {"t2m", "tmp2m", "2t"}:
            return "tmp2m"
        if normalized == "wspd10m":
            return "wspd10m"
        return normalized

    def select_dataarray(self, ds: object, var_id: str) -> object:
        return select_dataarray(ds, var_id)

    def ensure_latest_cycles(self, keep_cycles: int, *, cache_dir: Path | None = None) -> dict[str, int]:
        if cache_dir is None:
            return ensure_latest_cycles(keep_cycles=keep_cycles)
        cache_cfg = HRRRCacheConfig(base_dir=cache_dir, keep_runs=keep_cycles)
        return ensure_latest_cycles(keep_cycles=keep_cycles, cache_cfg=cache_cfg)


PNW_BBOX_WGS84 = (-125.5, 41.5, -111.0, 49.5)

HRRR_REGIONS: dict[str, RegionSpec] = {
    "pnw": RegionSpec(
        id="pnw",
        name="Pacific Northwest",
        bbox_wgs84=PNW_BBOX_WGS84,
        clip=True,
    ),
}

HRRR_VARS: dict[str, VarSpec] = {
    "tmp2m": VarSpec(
        id="tmp2m",
        name="2m Temp",
        selectors=VarSelectors(
            search=[":TMP:2 m above ground:"],
            filter_by_keys={
                "typeOfLevel": "heightAboveGround",
            },
            hints={
                "upstream_var": "t2m",
            },
        ),
        primary=True,
    ),
    "wspd10m": VarSpec(
        id="wspd10m",
        name="10m Wind Speed",
        selectors=VarSelectors(
            hints={
                "u_component": "10u",
                "v_component": "10v",
            }
        ),
        derived=True,
        derive="wspd10m",
    ),
}


HRRR_MODEL = HRRRPlugin(
    id="hrrr",
    name="HRRR",
    regions=HRRR_REGIONS,
    vars=HRRR_VARS,
    product="sfc",
)

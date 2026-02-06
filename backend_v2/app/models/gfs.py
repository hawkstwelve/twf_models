from __future__ import annotations

from .base import BaseModelPlugin, RegionSpec, VarSelectors, VarSpec


class GFSPlugin(BaseModelPlugin):
    pass


GFS_REGIONS: dict[str, RegionSpec] = {
    "conus": RegionSpec(
        id="conus",
        name="CONUS",
        bbox_wgs84=None,
        clip=False,
    ),
}

GFS_VARS: dict[str, VarSpec] = {
    "tmp2m": VarSpec(
        id="tmp2m",
        name="2m Temp",
        selectors=VarSelectors(
            search=[":TMP:2 m above ground:"],
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


GFS_MODEL = GFSPlugin(
    id="gfs",
    name="GFS",
    regions=GFS_REGIONS,
    vars=GFS_VARS,
    product="pgrb2.0p25",
)

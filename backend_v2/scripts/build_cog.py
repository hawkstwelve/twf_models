from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

import xarray as xr

# Add backend_v2 to path so app module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

from app.services import build_cog_pipeline as _pipeline
from app.services import gdal_util as _gdal_util
from app.services.encode import (
    _encode_precip_ptype_blend,
    _encode_radar_ptype_combo,
    _encode_with_nodata,
)
from app.services.gdal_util import (
    _band_min_max,
    _extract_raster_georef,
    _read_geotiff_band_float32,
    build_gdalwarp_3857_cmd,
    run_cmd,
    run_cmd_json,
    run_cmd_output,
    wgs84_bbox_to_3857,
)
from app.services.georef import (
    _infer_spacing,
    _latlon_axes_from_grib_attrs,
    _normalize_latlon_dataarray,
)
from app.services.grib_open import UpstreamNotReadyError, open_cfgrib_dataset

logger = logging.getLogger(__name__)

# Preserve existing CLI and orchestration utilities from the pipeline module.
parse_args = _pipeline.parse_args
assert_gdal_proj_version_pins = _pipeline.assert_gdal_proj_version_pins
fetch_grib = _pipeline.fetch_grib
resolve_target_grid_meters = _pipeline.resolve_target_grid_meters
_coerce_run_id = _pipeline._coerce_run_id
_resolve_radar_blend_component_paths = _pipeline._resolve_radar_blend_component_paths
_resolve_precip_ptype_component_paths = _pipeline._resolve_precip_ptype_component_paths
_is_discrete = _pipeline._is_discrete
_gdaladdo_supports_mask = _gdal_util._gdaladdo_supports_mask


def _open_cfgrib_dataset(grib_path: object, var_spec: Any):
    return open_cfgrib_dataset(
        grib_path,
        var_spec,
        strict=False,
        open_dataset=xr.open_dataset,
    )


def _open_cfgrib_dataset_strict(grib_path: object, var_spec: Any):
    return open_cfgrib_dataset(
        grib_path,
        var_spec,
        strict=True,
        open_dataset=xr.open_dataset,
    )


def require_gdal(cmd_name: str) -> None:
    _gdal_util.require_gdal(cmd_name)


def gdalinfo_json(path: Path) -> dict:
    require_gdal("gdalinfo")
    return run_cmd_json(["gdalinfo", "-json", str(path)])


def warp_to_3857(
    src_tif: Path,
    dst_tif: Path,
    clip_bounds_3857: tuple[float, float, float, float] | None = None,
    *,
    resampling: str = "bilinear",
    tr_meters: tuple[float, float] | None = None,
    tap: bool = True,
    with_alpha: bool = True,
) -> None:
    require_gdal("gdalwarp")
    dst_tif.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_gdalwarp_3857_cmd(
        src_tif,
        dst_tif,
        resampling=resampling,
        tr_meters=tr_meters,
        tap=tap,
        with_alpha=with_alpha,
        clip_bounds_3857=clip_bounds_3857,
    )
    if os.environ.get("TWF_GDAL_DEBUG", "0").strip() == "1":
        logger.info("GDAL cmd: %s", " ".join(cmd))
    run_cmd(cmd)


def _sync_gdal_util() -> None:
    _gdal_util.require_gdal = require_gdal
    _gdal_util.run_cmd = run_cmd
    _gdal_util.run_cmd_output = run_cmd_output
    _gdal_util.run_cmd_json = run_cmd_json
    _gdal_util.gdalinfo_json = gdalinfo_json
    _gdal_util._gdaladdo_supports_mask = _gdaladdo_supports_mask


def write_byte_geotiff_from_arrays(*args, **kwargs):
    _sync_gdal_util()
    return _gdal_util.write_byte_geotiff_from_arrays(*args, **kwargs)


def write_float_geotiff_from_array(*args, **kwargs):
    _sync_gdal_util()
    return _gdal_util.write_float_geotiff_from_array(*args, **kwargs)


def write_byte_geotiff_singleband_from_georef(*args, **kwargs):
    _sync_gdal_util()
    return _gdal_util.write_byte_geotiff_singleband_from_georef(*args, **kwargs)


def write_byte_geotiff_from_georef(*args, **kwargs):
    _sync_gdal_util()
    return _gdal_util.write_byte_geotiff_from_georef(*args, **kwargs)


def _is_copy_src_overviews_unsupported(exc: RuntimeError) -> bool:
    return _gdal_util._is_copy_src_overviews_unsupported(exc)


def run_gdaladdo_overviews(cog_path: Path, band1_resampling: str, band2_resampling: str) -> None:
    _sync_gdal_util()
    _gdal_util.run_gdaladdo_overviews(cog_path, band1_resampling, band2_resampling)


def assert_single_internal_overview_cog(path: Path) -> None:
    _sync_gdal_util()
    _gdal_util.assert_single_internal_overview_cog(path)


def assert_alpha_present(info: dict) -> int:
    return _gdal_util.assert_alpha_present(info)


def log_warped_info(path: Path, info: dict) -> None:
    _gdal_util.log_warped_info(path, info)


def _structured_print(*args, **kwargs) -> None:
    sep = kwargs.get("sep", " ")
    message = sep.join(str(item) for item in args)
    target = kwargs.get("file", None)
    if target is not None and target is sys.stderr:
        logger.error(message)
    else:
        logger.info(message)


def _configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    else:
        root.setLevel(level)


def _sync_pipeline_bindings() -> None:
    bindings = {
        "parse_args": parse_args,
        "assert_gdal_proj_version_pins": assert_gdal_proj_version_pins,
        "fetch_grib": fetch_grib,
        "_open_cfgrib_dataset": _open_cfgrib_dataset,
        "_open_cfgrib_dataset_strict": _open_cfgrib_dataset_strict,
        "_encode_with_nodata": _encode_with_nodata,
        "_encode_radar_ptype_combo": _encode_radar_ptype_combo,
        "_encode_precip_ptype_blend": _encode_precip_ptype_blend,
        "_infer_spacing": _infer_spacing,
        "_latlon_axes_from_grib_attrs": _latlon_axes_from_grib_attrs,
        "_normalize_latlon_dataarray": _normalize_latlon_dataarray,
        "require_gdal": require_gdal,
        "run_cmd": run_cmd,
        "run_cmd_output": run_cmd_output,
        "run_cmd_json": run_cmd_json,
        "gdalinfo_json": gdalinfo_json,
        "wgs84_bbox_to_3857": wgs84_bbox_to_3857,
        "warp_to_3857": warp_to_3857,
        "write_byte_geotiff_from_arrays": write_byte_geotiff_from_arrays,
        "write_float_geotiff_from_array": write_float_geotiff_from_array,
        "_read_geotiff_band_float32": _read_geotiff_band_float32,
        "_extract_raster_georef": _extract_raster_georef,
        "write_byte_geotiff_singleband_from_georef": write_byte_geotiff_singleband_from_georef,
        "write_byte_geotiff_from_georef": write_byte_geotiff_from_georef,
        "run_gdaladdo_overviews": run_gdaladdo_overviews,
        "assert_single_internal_overview_cog": assert_single_internal_overview_cog,
        "assert_alpha_present": assert_alpha_present,
        "log_warped_info": log_warped_info,
        "_band_min_max": _band_min_max,
        "UpstreamNotReadyError": UpstreamNotReadyError,
    }
    for key, value in bindings.items():
        setattr(_pipeline, key, value)


def main() -> int:
    parsed_args = parse_args()
    _configure_logging(bool(getattr(parsed_args, "debug", False)))
    _sync_pipeline_bindings()
    _pipeline.parse_args = lambda: parsed_args
    _pipeline.print = _structured_print
    return _pipeline.main()


def __getattr__(name: str):
    return getattr(_pipeline, name)


if __name__ == "__main__":
    raise SystemExit(main())

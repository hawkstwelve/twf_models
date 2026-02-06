from __future__ import annotations

import argparse
import re
import sys
import tempfile
import traceback
from pathlib import Path

# Add backend_v2 to path so app module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import numpy as np
import xarray as xr

from app.models import get_model
from app.services.fetch_engine import fetch_grib
from app.services.grid import detect_latlon_names

from build_cog_v2 import (
    _encode_radar_ptype_combo,
    _encode_with_nodata,
    _open_cfgrib_dataset,
    _write_sidecar_json,
    _write_vrt,
    assert_alpha_present,
    gdalinfo_json,
    log_warped_info,
    require_gdal,
    run_cmd,
    warp_to_3857,
    wgs84_bbox_to_3857,
)


RUN_RE = re.compile(r"^\d{8}_\d{2}z$")


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(item.strip()) for item in value.split(",")]
    if len(parts) != 4:
        raise ValueError("Expected 4 comma-separated values: min_lon,min_lat,max_lon,max_lat")
    return parts[0], parts[1], parts[2], parts[3]


def _normalize_lon_1d(lon: np.ndarray) -> np.ndarray:
    return ((lon + 180.0) % 360.0) - 180.0


def _infer_spacing(values: np.ndarray, *, axis_name: str) -> float:
    if values.ndim != 1 or values.size < 2:
        raise ValueError(f"{axis_name} must be 1D with at least 2 values")
    diffs = np.diff(values.astype(np.float64))
    abs_diffs = np.abs(diffs[np.isfinite(diffs)])
    if abs_diffs.size == 0:
        raise ValueError(f"Could not infer {axis_name} spacing")
    spacing = float(np.median(abs_diffs))
    if spacing <= 0:
        raise ValueError(f"Invalid non-positive {axis_name} spacing: {spacing}")
    return spacing


def _normalize_latlon_dataarray(da: xr.DataArray) -> tuple[xr.DataArray, str, str]:
    lat_name, lon_name = detect_latlon_names(da)

    lat = da.coords[lat_name].values
    lon = da.coords[lon_name].values
    if lat.ndim != 1 or lon.ndim != 1:
        raise ValueError("GFS builder currently expects 1D latitude/longitude coordinates")

    lon_wrapped = _normalize_lon_1d(lon)
    da = da.assign_coords({lon_name: (da.coords[lon_name].dims, lon_wrapped)})
    da = da.sortby(lon_name)

    lat_sorted = da.coords[lat_name].values
    if lat_sorted[0] < lat_sorted[-1]:
        da = da.sortby(lat_name, ascending=False)

    return da, lat_name, lon_name


def _write_byte_geotiff_latlon(
    *,
    da: xr.DataArray,
    byte_band: np.ndarray,
    alpha_band: np.ndarray,
    out_tif: Path,
) -> Path:
    lat_name, lon_name = detect_latlon_names(da)
    lat = np.asarray(da.coords[lat_name].values, dtype=np.float64)
    lon = np.asarray(da.coords[lon_name].values, dtype=np.float64)

    if byte_band.ndim != 2 or alpha_band.ndim != 2:
        raise ValueError("byte_band and alpha_band must be 2D arrays")
    if byte_band.shape != alpha_band.shape:
        raise ValueError("byte_band and alpha_band must have the same shape")
    if byte_band.shape != (lat.size, lon.size):
        raise ValueError(
            f"Band shape mismatch with coordinates: band={byte_band.shape} lat={lat.size} lon={lon.size}"
        )

    res_x = _infer_spacing(lon, axis_name="longitude")
    res_y = _infer_spacing(lat, axis_name="latitude")
    lon_min = float(np.min(lon))
    lat_max = float(np.max(lat))
    geotransform = (lon_min - (res_x / 2.0), res_x, 0.0, lat_max + (res_y / 2.0), 0.0, -res_y)
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    band1_path = out_tif.with_suffix(".band1.bin")
    band2_path = out_tif.with_suffix(".band2.bin")
    vrt_path = out_tif.with_suffix(".vrt")

    byte_band.astype(np.uint8).tofile(band1_path)
    alpha_band.astype(np.uint8).tofile(band2_path)

    _write_vrt(
        vrt_path,
        x_size=byte_band.shape[1],
        y_size=byte_band.shape[0],
        geotransform=geotransform,
        srs_wkt="EPSG:4326",
        band1_path=band1_path,
        band2_path=band2_path,
    )

    require_gdal("gdal_translate")
    run_cmd(
        [
            "gdal_translate",
            "-of",
            "GTiff",
            "-co",
            "TILED=YES",
            "-co",
            "COMPRESS=DEFLATE",
            str(vrt_path),
            str(out_tif),
        ]
    )

    for temp_path in (band1_path, band2_path, vrt_path):
        try:
            temp_path.unlink()
        except OSError:
            pass

    return out_tif


def _derive_run_id(path: Path) -> str:
    try:
        day = path.parent.parent.name
        hour = path.parent.name
    except Exception as exc:
        raise RuntimeError(f"Could not derive run_id from path: {path}") from exc
    run_id = f"{day}_{hour}z"
    if not RUN_RE.match(run_id):
        raise RuntimeError(f"Derived invalid run_id={run_id} from path={path}")
    return run_id


def _coerce_run_id(run_id: str | None, path: Path) -> str:
    if run_id and run_id != "unknown" and RUN_RE.match(run_id):
        return run_id
    return _derive_run_id(path)


def _resolve_radar_blend_component_paths(
    component_paths: dict[str, Path],
    *,
    refl_key: str,
    rain_key: str,
    snow_key: str,
    sleet_key: str,
    frzr_key: str,
) -> tuple[Path, Path, Path, Path, Path]:
    expected = [refl_key, rain_key, snow_key, sleet_key, frzr_key]
    resolved: list[Path] = []
    for key in expected:
        path = component_paths.get(key)
        if path is None:
            available = sorted(component_paths.keys())
            raise RuntimeError(
                f"Missing radar_ptype_combo component file: expected={key} have={available}"
            )
        resolved.append(path)
    return tuple(resolved)  # type: ignore[return-value]


def build_gfs_cog(
    *,
    run: str,
    fh: int,
    region: str,
    var: str,
    product: str = "pgrb2.0p25",
    out_root: Path | str = Path("/opt/twf_models/data/v2"),
    model: str = "gfs",
    cache_dir: Path | None = None,
    clip_bounds_3857: tuple[float, float, float, float] | None = None,
    allow_range_fallback: bool = False,
) -> Path:
    plugin = get_model(model)
    if product != plugin.product:
        raise RuntimeError(
            f"Unsupported product override for {model}: requested={product} default={plugin.product}"
        )
    region_spec = plugin.get_region(region)
    if region_spec is None:
        raise RuntimeError(f"Unknown region: {region}")

    normalized_var = plugin.normalize_var_id(var)
    var_spec = plugin.get_var(normalized_var)
    if var_spec is None:
        raise RuntimeError(f"Unknown variable: {var} (normalized={normalized_var})")

    fetch_result = fetch_grib(
        model=model,
        run=run,
        fh=fh,
        var=normalized_var,
        region=region,
        cache_dir=cache_dir,
    )
    if fetch_result.not_ready_reason:
        raise RuntimeError(f"Upstream not ready: {fetch_result.not_ready_reason}")

    ds_u: xr.Dataset | None = None
    ds_v: xr.Dataset | None = None
    ds_refl: xr.Dataset | None = None
    ds_rain: xr.Dataset | None = None
    ds_snow: xr.Dataset | None = None
    ds_sleet: xr.Dataset | None = None
    ds_frzr: xr.Dataset | None = None
    ds: xr.Dataset | None = None
    pre_encoded: tuple[np.ndarray, np.ndarray, dict] | None = None
    try:
        derive_kind = str(var_spec.derive or "") if var_spec.derived else ""
        if derive_kind == "wspd10m":
            if not fetch_result.component_paths:
                raise RuntimeError("Missing component paths for wspd10m")
            u_key = var_spec.selectors.hints.get("u_component", "10u")
            v_key = var_spec.selectors.hints.get("v_component", "10v")
            u_path = fetch_result.component_paths.get(u_key)
            v_path = fetch_result.component_paths.get(v_key)
            if u_path is None or v_path is None:
                raise RuntimeError(
                    f"Missing wspd10m component files; have={sorted(fetch_result.component_paths.keys())}"
                )
            u_spec = plugin.get_var(u_key)
            v_spec = plugin.get_var(v_key)
            try:
                ds_u = _open_cfgrib_dataset(u_path, u_spec)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed opening U-component GRIB with cfgrib: path={u_path} type={type(exc).__name__} repr={exc!r}"
                ) from exc
            try:
                ds_v = _open_cfgrib_dataset(v_path, v_spec)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed opening V-component GRIB with cfgrib: path={v_path} type={type(exc).__name__} repr={exc!r}"
                ) from exc
            source_path = u_path
            try:
                u_da = plugin.select_dataarray(ds_u, u_key)
                v_da = plugin.select_dataarray(ds_v, v_key)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed selecting wspd10m components: type={type(exc).__name__} repr={exc!r}"
                ) from exc

            if "time" in u_da.dims:
                u_da = u_da.isel(time=0)
            if "time" in v_da.dims:
                v_da = v_da.isel(time=0)
            u_da = u_da.squeeze()
            v_da = v_da.squeeze()
            if u_da.shape != v_da.shape:
                raise RuntimeError(
                    f"wspd10m component shape mismatch: u_shape={u_da.shape} v_shape={v_da.shape}"
                )
            u_vals = np.asarray(u_da.values, dtype=np.float32)
            v_vals = np.asarray(v_da.values, dtype=np.float32)
            speed_vals = np.hypot(u_vals, v_vals) * 2.23694
            coords = {dim: u_da.coords[dim] for dim in u_da.dims if dim in u_da.coords}
            da = xr.DataArray(
                speed_vals.astype(np.float32),
                dims=u_da.dims,
                coords=coords,
                name="wspd10m",
            )
            da.attrs = dict(u_da.attrs)
            da.attrs["GRIB_units"] = "mph"
        elif derive_kind == "radar_ptype_combo":
            if not fetch_result.component_paths:
                raise RuntimeError("Missing component paths for radar_ptype_combo")
            refl_component = str(var_spec.selectors.hints.get("refl_component", "refc"))
            rain_component = str(var_spec.selectors.hints.get("rain_component", "crain"))
            snow_component = str(var_spec.selectors.hints.get("snow_component", "csnow"))
            sleet_component = str(var_spec.selectors.hints.get("sleet_component", "cicep"))
            frzr_component = str(var_spec.selectors.hints.get("frzr_component", "cfrzr"))
            refl_path, rain_path, snow_path, sleet_path, frzr_path = _resolve_radar_blend_component_paths(
                fetch_result.component_paths,
                refl_key=refl_component,
                rain_key=rain_component,
                snow_key=snow_component,
                sleet_key=sleet_component,
                frzr_key=frzr_component,
            )
            source_path = refl_path

            ds_refl = _open_cfgrib_dataset(refl_path, plugin.get_var(refl_component))
            ds_rain = _open_cfgrib_dataset(rain_path, plugin.get_var(rain_component))
            ds_snow = _open_cfgrib_dataset(snow_path, plugin.get_var(snow_component))
            ds_sleet = _open_cfgrib_dataset(sleet_path, plugin.get_var(sleet_component))
            ds_frzr = _open_cfgrib_dataset(frzr_path, plugin.get_var(frzr_component))

            refl_da = plugin.select_dataarray(ds_refl, refl_component)
            rain_da = plugin.select_dataarray(ds_rain, rain_component)
            snow_da = plugin.select_dataarray(ds_snow, snow_component)
            sleet_da = plugin.select_dataarray(ds_sleet, sleet_component)
            frzr_da = plugin.select_dataarray(ds_frzr, frzr_component)

            arrays = [refl_da, rain_da, snow_da, sleet_da, frzr_da]
            arrays = [arr.isel(time=0) if "time" in arr.dims else arr for arr in arrays]
            refl_da, rain_da, snow_da, sleet_da, frzr_da = [arr.squeeze() for arr in arrays]
            da = refl_da
            pre_encoded = _encode_radar_ptype_combo(
                requested_var=var,
                normalized_var=normalized_var,
                refl_values=np.asarray(refl_da.values, dtype=np.float32),
                ptype_values={
                    "crain": np.asarray(rain_da.values, dtype=np.float32),
                    "csnow": np.asarray(snow_da.values, dtype=np.float32),
                    "cicep": np.asarray(sleet_da.values, dtype=np.float32),
                    "cfrzr": np.asarray(frzr_da.values, dtype=np.float32),
                },
            )
        else:
            if fetch_result.grib_path is None:
                raise RuntimeError("Missing GRIB path from fetch result")
            source_path = fetch_result.grib_path
            try:
                ds = _open_cfgrib_dataset(source_path, var_spec)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed opening GRIB with cfgrib: path={source_path} type={type(exc).__name__} repr={exc!r}"
                ) from exc

            da = plugin.select_dataarray(ds, normalized_var)
            if "time" in da.dims:
                da = da.isel(time=0)
            da = da.squeeze()
        if da.ndim != 2:
            raise RuntimeError(f"Expected 2D DataArray after squeeze, got dims={da.dims}")

        da, _, _ = _normalize_latlon_dataarray(da)
        values = np.asarray(da.values, dtype=np.float32)
        if pre_encoded is None:
            byte_band, alpha_band, meta, _, _, _ = _encode_with_nodata(
                values,
                requested_var=var,
                normalized_var=normalized_var,
                da=da,
                allow_range_fallback=allow_range_fallback,
            )
        else:
            byte_band, alpha_band, meta = pre_encoded

        run_id = _coerce_run_id(fetch_result.upstream_run_id, source_path)
        out_root_path = Path(out_root)
        out_dir = out_root_path / model / region / run_id / var
        out_dir.mkdir(parents=True, exist_ok=True)
        cog_path = out_dir / f"fh{fh:03d}.cog.tif"
        sidecar_path = out_dir / f"fh{fh:03d}.json"

        with tempfile.TemporaryDirectory(prefix="gfs_cog_") as temp_dir:
            temp_root = Path(temp_dir)
            src_tif = temp_root / f"{source_path.stem}.latlon.tif"
            warped_tif = temp_root / f"{source_path.stem}.3857.tif"

            _write_byte_geotiff_latlon(
                da=da,
                byte_band=byte_band,
                alpha_band=alpha_band,
                out_tif=src_tif,
            )

            warp_to_3857(src_tif, warped_tif, clip_bounds_3857=clip_bounds_3857)
            info = gdalinfo_json(warped_tif)
            assert_alpha_present(info)
            log_warped_info(warped_tif, info)

            require_gdal("gdal_translate")
            run_cmd(
                [
                    "gdal_translate",
                    "-of",
                    "COG",
                    "-co",
                    "COMPRESS=DEFLATE",
                    str(warped_tif),
                    str(cog_path),
                ]
            )

            require_gdal("gdaladdo")
            run_cmd(
                [
                    "gdaladdo",
                    str(cog_path),
                    "2",
                    "4",
                    "8",
                    "16",
                    "32",
                    "64",
                ]
            )

        _write_sidecar_json(
            sidecar_path,
            model=model,
            region=region,
            run=run_id,
            var=var,
            fh=fh,
            meta=meta,
        )
        return cog_path
    finally:
        if ds is not None:
            ds.close()
        if ds_u is not None:
            ds_u.close()
        if ds_v is not None:
            ds_v.close()
        if ds_refl is not None:
            ds_refl.close()
        if ds_rain is not None:
            ds_rain.close()
        if ds_snow is not None:
            ds_snow.close()
        if ds_sleet is not None:
            ds_sleet.close()
        if ds_frzr is not None:
            ds_frzr.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build GFS COG for a run/fh/variable.")
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--model", type=str, default="gfs")
    parser.add_argument("--region", type=str, default="pnw")
    parser.add_argument("--out-root", type=Path, default=Path("/opt/twf_models/data/v2"))
    parser.add_argument("--run", type=str, default="latest")
    parser.add_argument("--fh", type=int, required=True)
    parser.add_argument("--var", type=str, required=True)
    parser.add_argument("--product", type=str, default="pgrb2.0p25")
    parser.add_argument("--bbox", type=str, default=None)
    parser.add_argument("--no-clip", action="store_true")
    parser.add_argument("--allow-range-fallback", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    plugin = get_model(args.model)
    region_spec = plugin.get_region(args.region)
    if region_spec is None:
        print(f"ERROR: Unknown region: {args.region}", file=sys.stderr)
        return 1

    clip_bounds_3857: tuple[float, float, float, float] | None = None
    if args.no_clip:
        clip_bounds_3857 = None
    elif args.bbox:
        try:
            clip_bounds_3857 = wgs84_bbox_to_3857(_parse_bbox(args.bbox))
        except Exception as exc:
            print(f"ERROR: invalid --bbox: {exc}", file=sys.stderr)
            return 1
    elif region_spec.clip and region_spec.bbox_wgs84 is not None:
        clip_bounds_3857 = wgs84_bbox_to_3857(region_spec.bbox_wgs84)

    try:
        cog_path = build_gfs_cog(
            run=args.run,
            fh=args.fh,
            region=args.region,
            var=args.var,
            product=args.product,
            out_root=args.out_root,
            model=args.model,
            cache_dir=args.cache_dir,
            clip_bounds_3857=clip_bounds_3857,
            allow_range_fallback=bool(args.allow_range_fallback),
        )
    except Exception as exc:
        text = str(exc).lower()
        if "upstream not ready" in text or "index not ready" in text:
            print(f"UPSTREAM_NOT_READY: {exc}", file=sys.stderr)
            return 2
        message = str(exc).strip()
        if not message:
            message = f"{type(exc).__name__}: {exc!r}"
        print(f"ERROR: {message}", file=sys.stderr)
        if args.debug:
            traceback.print_exc()
        return 1

    print(f"COG built: {cog_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

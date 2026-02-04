from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import xarray as xr
from pyproj import CRS, Transformer

from app.services.colormaps_v2 import encode_to_byte_and_alpha
from app.services.grid import detect_latlon_names, normalize_latlon_coords
from app.services.hrrr_fetch import ensure_latest_cycles, fetch_hrrr_grib
from app.services.hrrr_runs import HRRRCacheConfig
from app.services.paths import default_hrrr_cache_dir
from app.services.variable_registry import normalize_api_variable, select_dataarray

EPS = 1e-9
logger = logging.getLogger(__name__)

# PNW bounding box: WA, OR, NW Idaho, Western MT
PNW_BBOX_WGS84 = (-125.5, 41.5, -111.0, 49.5)  # (min_lon, min_lat, max_lon, max_lat)


def require_gdal(cmd_name: str) -> None:
    if shutil.which(cmd_name) is None:
        raise RuntimeError(
            f"Missing '{cmd_name}'. Install GDAL (gdalwarp/gdal_translate) and ensure it is on PATH."
        )


def run_cmd(args: list[str]) -> None:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Command failed ({' '.join(args)}): {stderr or 'unknown error'}")


def run_cmd_json(args: list[str]) -> dict:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Command failed ({' '.join(args)}): {stderr or 'unknown error'}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse JSON from {' '.join(args)}") from exc


def wgs84_bbox_to_3857(bbox_wgs84: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = bbox_wgs84
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    minx, miny = transformer.transform(min_lon, min_lat)
    maxx, maxy = transformer.transform(max_lon, max_lat)
    return minx, miny, maxx, maxy


def _lambert_grid_from_attrs(da: xr.DataArray) -> dict:
    attrs = da.attrs
    try:
        nx = int(attrs.get("GRIB_Nx"))
        ny = int(attrs.get("GRIB_Ny"))
        dx = float(attrs.get("GRIB_DxInMetres"))
        dy = float(attrs.get("GRIB_DyInMetres"))
        lon_0 = float(attrs.get("GRIB_LoVInDegrees"))
        lat_1 = float(attrs.get("GRIB_Latin1InDegrees"))
        lat_2 = float(attrs.get("GRIB_Latin2InDegrees"))
        lat_0 = float(attrs.get("GRIB_LaDInDegrees"))
        lat_first = float(attrs.get("GRIB_latitudeOfFirstGridPointInDegrees"))
        lon_first = float(attrs.get("GRIB_longitudeOfFirstGridPointInDegrees"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Lambert attrs missing: {exc}") from exc
    if nx < 2 or ny < 2:
        raise ValueError(f"Lambert grid too small for transform: nx={nx} ny={ny}")

    lambert_crs = CRS.from_proj4(
        f"+proj=lcc +lat_1={lat_1} +lat_2={lat_2} +lat_0={lat_0} "
        f"+lon_0={lon_0} +datum=WGS84 +units=m +no_defs"
    )
    ll_to_lambert = Transformer.from_crs("EPSG:4326", lambert_crs, always_xy=True)
    x0, y0 = ll_to_lambert.transform(lon_first, lat_first)

    i_scans_neg = int(attrs.get("GRIB_iScansNegatively", 0)) == 1
    j_scans_pos = int(attrs.get("GRIB_jScansPositively", 1)) == 1

    x_coords = x0 + np.arange(nx) * dx
    y_coords = y0 + np.arange(ny) * dy

    return {
        "nx": nx,
        "ny": ny,
        "x_coords": x_coords,
        "y_coords": y_coords,
        "lambert_crs": lambert_crs,
        "i_scans_neg": i_scans_neg,
        "j_scans_pos": j_scans_pos,
    }


def _apply_scan_order(data: np.ndarray, grid: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    nx = grid["nx"]
    ny = grid["ny"]
    if data.shape != (ny, nx):
        raise ValueError(f"Values shape {data.shape} does not match GRIB grid {ny}x{nx}")

    x_coords = np.array(grid["x_coords"], copy=True)
    y_coords = np.array(grid["y_coords"], copy=True)

    if grid["i_scans_neg"]:
        x_coords = x_coords[::-1]
        data = data[:, ::-1]
    if not grid["j_scans_pos"]:
        y_coords = y_coords[::-1]
        data = data[::-1, :]

    if x_coords[1] < x_coords[0]:
        x_coords = x_coords[::-1]
        data = data[:, ::-1]
    if y_coords[1] > y_coords[0]:
        y_coords = y_coords[::-1]
        data = data[::-1, :]

    return data, x_coords, y_coords


def _write_vrt(
    vrt_path: Path,
    *,
    x_size: int,
    y_size: int,
    geotransform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
    band1_path: Path,
    band2_path: Path,
) -> None:
    srs_escaped = escape(srs_wkt)
    vrt = f"""
<VRTDataset rasterXSize=\"{x_size}\" rasterYSize=\"{y_size}\">
  <SRS>{srs_escaped}</SRS>
  <GeoTransform>{','.join(f'{v:.10f}' for v in geotransform)}</GeoTransform>
  <VRTRasterBand dataType=\"Byte\" band=\"1\" subClass=\"VRTRawRasterBand\">
    <Description>intensity</Description>
    <ColorInterp>Gray</ColorInterp>
    <SourceFilename relativeToVRT=\"0\">{band1_path}</SourceFilename>
    <ImageOffset>0</ImageOffset>
    <PixelOffset>1</PixelOffset>
    <LineOffset>{x_size}</LineOffset>
    <ByteOrder>LSB</ByteOrder>
  </VRTRasterBand>
  <VRTRasterBand dataType=\"Byte\" band=\"2\" subClass=\"VRTRawRasterBand\">
    <Description>alpha</Description>
    <ColorInterp>Alpha</ColorInterp>
    <SourceFilename relativeToVRT=\"0\">{band2_path}</SourceFilename>
    <ImageOffset>0</ImageOffset>
    <PixelOffset>1</PixelOffset>
    <LineOffset>{x_size}</LineOffset>
    <ByteOrder>LSB</ByteOrder>
  </VRTRasterBand>
</VRTDataset>
""".strip()
    vrt_path.write_text(vrt)


def write_byte_geotiff_from_arrays(
    da: xr.DataArray,
    byte_band: np.ndarray,
    alpha_band: np.ndarray,
    out_tif: Path,
) -> Path:
    grid = _lambert_grid_from_attrs(da)

    byte_data, x_coords, y_coords = _apply_scan_order(byte_band, grid)
    alpha_data, _, _ = _apply_scan_order(alpha_band, grid)

    dx = abs(x_coords[1] - x_coords[0]) if x_coords.size > 1 else 1.0
    dy = abs(y_coords[1] - y_coords[0]) if y_coords.size > 1 else 1.0
    x_min = float(np.min(x_coords))
    x_max = float(np.max(x_coords))
    y_min = float(np.min(y_coords))
    y_max = float(np.max(y_coords))
    geotransform = (x_min, dx, 0.0, y_max, 0.0, -dy)
    print(
        "Lambert grid transform: "
        f"dx={dx:.3f} dy={dy:.3f} "
        f"x=[{x_min:.2f},{x_max:.2f}] y=[{y_min:.2f},{y_max:.2f}]"
    )

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    band1_path = out_tif.with_suffix(".band1.bin")
    band2_path = out_tif.with_suffix(".band2.bin")
    vrt_path = out_tif.with_suffix(".vrt")

    byte_data.tofile(band1_path)
    alpha_data.tofile(band2_path)

    _write_vrt(
        vrt_path,
        x_size=byte_data.shape[1],
        y_size=byte_data.shape[0],
        geotransform=geotransform,
        srs_wkt=grid["lambert_crs"].to_wkt(),
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


def warp_to_3857(src_tif: Path, dst_tif: Path, clip_bounds_3857: tuple[float, float, float, float] | None = None) -> None:
    require_gdal("gdalwarp")
    dst_tif.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "gdalwarp",
        "-t_srs",
        "EPSG:3857",
        "-r",
        "bilinear",
        "-srcalpha",
        "-wo",
        "SRC_ALPHA=YES",
        "-co",
        "TILED=YES",
        "-co",
        "COMPRESS=DEFLATE",
        "-overwrite",
    ]

    if clip_bounds_3857 is not None:
        minx, miny, maxx, maxy = clip_bounds_3857
        cmd.extend([
            "-te",
            str(minx),
            str(miny),
            str(maxx),
            str(maxy),
            "-te_srs",
            "EPSG:3857",
        ])

    cmd.extend([str(src_tif), str(dst_tif)])
    run_cmd(cmd)


def gdalinfo_json(path: Path) -> dict:
    require_gdal("gdalinfo")
    return run_cmd_json(["gdalinfo", "-json", str(path)])


def assert_alpha_present(info: dict) -> int:
    bands = info.get("bands") or []
    if not bands:
        raise RuntimeError("GDAL info returned no bands")
    alpha_present = any(
        band.get("colorInterpretation") == "Alpha"
        or str(band.get("description", "")).lower() == "alpha"
        for band in bands
    )
    if not alpha_present or len(bands) < 2:
        raise RuntimeError("Warped GeoTIFF is missing alpha band (expected >= 2 bands)")
    return len(bands)


def log_warped_info(path: Path, info: dict) -> None:
    size = info.get("size") or [0, 0]
    corner = info.get("cornerCoordinates") or {}
    lower_left = corner.get("lowerLeft") or [0.0, 0.0]
    upper_right = corner.get("upperRight") or [0.0, 0.0]
    print(
        "Warped GeoTIFF info: "
        f"path={path} width={size[0]} height={size[1]} bands={len(info.get('bands') or [])} "
        f"bounds_3857=({lower_left[0]:.2f},{lower_left[1]:.2f},{upper_right[0]:.2f},{upper_right[1]:.2f})"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build HRRR COG for a run/fh/variable.")
    parser.add_argument("--cache-dir", type=str, default=None)
    parser.add_argument("--model", type=str, default="hrrr")
    parser.add_argument("--region", type=str, default="pnw")
    parser.add_argument("--out-root", type=str, default="/opt/twf_models/data/v2")
    parser.add_argument("--run", type=str, default="latest")
    parser.add_argument("--fh", type=int, required=True)
    parser.add_argument("--var", type=str, required=True)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--keep-cycles", type=int, default=None)
    parser.add_argument(
        "--bbox",
        type=str,
        default=None,
        help="Clip to custom WGS84 bbox: 'min_lon,min_lat,max_lon,max_lat' (default: PNW region)",
    )
    parser.add_argument(
        "--no-clip",
        action="store_true",
        help="Disable geographic clipping (generates tiles for full HRRR domain)",
    )
    return parser.parse_args()


def _resolve_run_id(grib_path: Path) -> str:
    cycle_dir = grib_path.parent
    day_dir = cycle_dir.parent
    return f"{day_dir.name}_{cycle_dir.name}z"


def _write_sidecar_json(
    path: Path,
    *,
    model: str,
    region: str,
    run: str,
    var: str,
    fh: int,
    meta: dict,
) -> None:
    payload = {
        "model": model,
        "region": region,
        "run": run,
        "var": var,
        "fh": fh,
        "meta": meta,
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    args = parse_args()
    cache_dir = Path(args.cache_dir) if args.cache_dir else default_hrrr_cache_dir()
    cfg = HRRRCacheConfig(base_dir=cache_dir, keep_runs=1)

    if args.no_clip:
        clip_bbox_wgs84 = None
        clip_bounds_3857 = None
        print("Clipping disabled: will generate tiles for full HRRR domain")
    elif args.bbox:
        try:
            parts = [float(x.strip()) for x in args.bbox.split(",")]
            if len(parts) != 4:
                raise ValueError("Expected 4 values")
            clip_bbox_wgs84 = tuple(parts)
            clip_bounds_3857 = wgs84_bbox_to_3857(clip_bbox_wgs84)
            print(f"Using custom clip bbox (WGS84): {clip_bbox_wgs84}")
        except Exception as exc:
            print(f"ERROR: Invalid --bbox format: {exc}", file=sys.stderr)
            return 1
    else:
        clip_bbox_wgs84 = PNW_BBOX_WGS84
        clip_bounds_3857 = wgs84_bbox_to_3857(PNW_BBOX_WGS84)
        print(f"Using default PNW clip bbox (WGS84): {clip_bbox_wgs84}")

    if clip_bounds_3857:
        print(
            f"Clip bounds (EPSG:3857): minx={clip_bounds_3857[0]:.2f} miny={clip_bounds_3857[1]:.2f} "
            f"maxx={clip_bounds_3857[2]:.2f} maxy={clip_bounds_3857[3]:.2f}"
        )

    normalized_var = normalize_api_variable(args.var)
    grib_path: Path | None = None
    u_path: Path | None = None
    v_path: Path | None = None

    if normalized_var == "wspd10m":
        try:
            u_path = fetch_hrrr_grib(
                run=args.run,
                fh=args.fh,
                variable="ugrd10m",
                cache_cfg=cfg,
            )
            v_path = fetch_hrrr_grib(
                run=args.run,
                fh=args.fh,
                variable="vgrd10m",
                cache_cfg=cfg,
            )
            grib_path = u_path
        except Exception as exc:
            logger.exception("Failed to fetch HRRR GRIB for wspd10m")
            return 2

        print(f"GRIB path (u10): {u_path}")
        print(f"GRIB path (v10): {v_path}")
    else:
        try:
            grib_path = fetch_hrrr_grib(
                run=args.run,
                fh=args.fh,
                variable=args.var,
                cache_cfg=cfg,
            )
        except Exception as exc:
            logger.exception("Failed to fetch HRRR GRIB")
            return 2

        print(f"GRIB path: {grib_path}")

    ds: xr.Dataset | None = None
    ds_u: xr.Dataset | None = None
    ds_v: xr.Dataset | None = None
    try:
        if normalized_var == "wspd10m":
            try:
                u_da: xr.DataArray | None = None
                v_da: xr.DataArray | None = None

                def log_debug(message: str) -> None:
                    if args.debug:
                        print(message)
                    else:
                        print(message)

                def summarize_da(name: str, da: xr.DataArray) -> str:
                    grib_keys = [key for key in da.attrs.keys() if key.startswith("GRIB_")]
                    return (
                        f"{name}: name={da.name} dims={da.dims} shape={da.shape} "
                        f"coords={list(da.coords.keys())} grib_keys={grib_keys}"
                    )

                def select_first(ds: xr.Dataset, candidates: list[str], label: str) -> tuple[xr.DataArray, str]:
                    errors: list[str] = []
                    for cand in candidates:
                        try:
                            return select_dataarray(ds, cand), cand
                        except Exception as exc:
                            errors.append(f"{cand}: {type(exc).__name__}: {exc}")
                    available = sorted(ds.data_vars.keys())
                    if len(available) == 1:
                        only_key = available[0]
                        return ds[only_key], only_key
                    raise RuntimeError(
                        f"Failed to select {label}. Tried {candidates}. "
                        f"Available: {available}. Errors: {errors}"
                    )

                ds_u = xr.open_dataset(u_path, engine="cfgrib")
                ds_v = xr.open_dataset(v_path, engine="cfgrib")
                u_candidates = ["ugrd10m", "u10", "10u"]
                v_candidates = ["vgrd10m", "v10", "10v"]
                u_da, u_key = select_first(ds_u, u_candidates, "u wind")
                v_da, v_key = select_first(ds_v, v_candidates, "v wind")
                log_debug(f"wspd10m: selected u_key={u_key} v_key={v_key}")
                log_debug(summarize_da("u_da", u_da))
                log_debug(summarize_da("v_da", v_da))

                if "time" in u_da.dims:
                    u_da = u_da.isel(time=0)
                    log_debug("wspd10m: selected time=0 for u_da")
                if "time" in v_da.dims:
                    v_da = v_da.isel(time=0)
                    log_debug("wspd10m: selected time=0 for v_da")

                u_da = u_da.squeeze()
                v_da = v_da.squeeze()

                try:
                    u_da, v_da = xr.align(u_da, v_da, join="exact")
                except Exception as exc:
                    raise RuntimeError(
                        "Failed to align u/v grids. "
                        f"u_dims={u_da.dims} u_shape={u_da.shape} u_coords={list(u_da.coords.keys())} "
                        f"v_dims={v_da.dims} v_shape={v_da.shape} v_coords={list(v_da.coords.keys())}"
                    ) from exc

                wspd = np.hypot(u_da.astype("float32"), v_da.astype("float32")).astype("float32")
                wspd.name = "wspd10m"
                wspd.attrs = dict(u_da.attrs)
                wspd.attrs["GRIB_units"] = "m/s"
                da = wspd

                print(
                    "Derived wspd10m: "
                    f"min={float(np.nanmin(da.values)):.2f} max={float(np.nanmax(da.values)):.2f}"
                )
            except Exception as exc:
                if u_da is not None:
                    print(summarize_da("u_da", u_da))
                if v_da is not None:
                    print(summarize_da("v_da", v_da))
                logger.exception("wspd10m derivation failed")
                raise RuntimeError(
                    f"Failed to derive wspd10m: {type(exc).__name__}: {exc}"
                ) from exc
        else:
            try:
                ds = xr.open_dataset(grib_path, engine="cfgrib")
            except Exception as exc:
                message = str(exc)
                if "multiple values for unique key" in message:
                    logger.exception(
                        "cfgrib index collision. Ensure subsetting worked for the requested variable."
                    )
                elif "eccodes" in message.lower() or "ecCodes" in message or "Cannot find the ecCodes library" in message:
                    logger.exception("Failed to open GRIB with cfgrib. ecCodes library not available.")
                else:
                    logger.exception("Failed to open GRIB with cfgrib.")
                return 3

            try:
                da = select_dataarray(ds, normalized_var)
            except Exception as exc:
                logger.exception(
                    "Failed to select variable '%s' (normalized='%s')",
                    args.var,
                    normalized_var,
                )
                return 4
    except RuntimeError as exc:
        logger.exception("Runtime error during data selection")
        return 4

    if "time" in da.dims:
        da = da.isel(time=0)
    da = da.squeeze()

    values = np.asarray(da.values, dtype=np.float32)
    if values.ndim != 2:
        raise RuntimeError(
            "Expected 2D values after squeeze. "
            f"dims={da.dims} shape={values.shape} coords={list(da.coords.keys())} "
            f"attrs_keys={sorted(list(da.attrs.keys()))}"
        )

    try:
        da = normalize_latlon_coords(da)
        lat_name, lon_name = detect_latlon_names(da)
    except Exception as exc:
        logger.exception("Failed to normalize lat/lon coords")
        return 5

    lat_vals = da.coords[lat_name].values
    lon_vals = da.coords[lon_name].values
    print(
        f"Requested var '{args.var}' normalized to '{normalized_var}' using dataset var '{da.name}'\n"
        f"GRIB domain: lat[{lat_name}] min={np.nanmin(lat_vals):.4f} max={np.nanmax(lat_vals):.4f}\n"
        f"GRIB domain: lon[{lon_name}] min={np.nanmin(lon_vals):.4f} max={np.nanmax(lon_vals):.4f}"
    )

    if clip_bbox_wgs84:
        bounds_wgs84 = clip_bbox_wgs84
        print(f"Metadata will use clipped bounds: {bounds_wgs84}")
    else:
        bounds_wgs84 = (
            float(np.nanmin(lon_vals)),
            float(np.nanmin(lat_vals)),
            float(np.nanmax(lon_vals)),
            float(np.nanmax(lat_vals)),
        )
        print(f"Metadata will use full GRIB bounds: {bounds_wgs84}")

    try:
        start_time = time.time()
        byte_band, alpha_band, meta = encode_to_byte_and_alpha(values, var_key=args.var)

        run_id = _resolve_run_id(grib_path)
        out_dir = Path(args.out_root) / args.model / args.region / run_id / args.var
        out_dir.mkdir(parents=True, exist_ok=True)

        cog_path = out_dir / f"fh{args.fh:03d}.cog.tif"
        sidecar_path = out_dir / f"fh{args.fh:03d}.json"

        with tempfile.TemporaryDirectory(prefix="hrrr_cog_") as temp_dir:
            temp_root = Path(temp_dir)
            base_name = grib_path.stem
            byte_tif = temp_root / f"{base_name}.byte.tif"
            warped_tif = temp_root / f"{base_name}.3857.tif"

            print(f"Writing byte GeoTIFF: {byte_tif}")
            write_byte_geotiff_from_arrays(da, byte_band, alpha_band, byte_tif)

            print(f"Warping to EPSG:3857: {warped_tif}")
            warp_to_3857(byte_tif, warped_tif, clip_bounds_3857=clip_bounds_3857)

            info = gdalinfo_json(warped_tif)
            assert_alpha_present(info)
            log_warped_info(warped_tif, info)

            if clip_bounds_3857:
                corner = info.get("cornerCoordinates") or {}
                ll = corner.get("lowerLeft") or [0.0, 0.0]
                ur = corner.get("upperRight") or [0.0, 0.0]
                print(
                    f"Warped GeoTIFF bounds (EPSG:3857): [{ll[0]:.2f}, {ll[1]:.2f}] to [{ur[0]:.2f}, {ur[1]:.2f}]"
                )
                print(
                    f"Expected clip bounds (EPSG:3857): [{clip_bounds_3857[0]:.2f}, {clip_bounds_3857[1]:.2f}] "
                    f"to [{clip_bounds_3857[2]:.2f}, {clip_bounds_3857[3]:.2f}]"
                )

            print(f"Writing COG: {cog_path}")
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
            model=args.model,
            region=args.region,
            run=run_id,
            var=args.var,
            fh=args.fh,
            meta=meta,
        )

        elapsed = time.time() - start_time
        print(f"Done: COG built in {elapsed:.1f}s")
    except Exception as exc:
        logger.exception("GDAL pipeline failed")
        return 6
    finally:
        if ds is not None:
            ds.close()
        if ds_u is not None:
            ds_u.close()
        if ds_v is not None:
            ds_v.close()

    if args.keep_cycles:
        try:
            summary = ensure_latest_cycles(keep_cycles=args.keep_cycles, cache_cfg=cfg)
        except Exception as exc:
            logger.exception("Failed to enforce cycle retention")
            return 7
        print(f"Retention: {summary}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

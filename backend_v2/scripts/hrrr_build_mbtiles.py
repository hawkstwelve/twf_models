from __future__ import annotations

# Notes (correctness fixes):
# - Metadata updates delete+insert managed keys to avoid duplicate rows.
# - Byte GeoTIFF writes explicit alpha band for transparency (no gdal dstalpha).
# - MBTiles build skips gdaladdo to avoid redundant overviews.
# NOTE: rasterio is not used; remove rasterio from requirements.txt if added previously.

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import xarray as xr
from pyproj import CRS, Transformer

from app.services.grid import detect_latlon_names, normalize_latlon_coords
from app.services.hrrr_fetch import ensure_latest_cycles, fetch_hrrr_grib
from app.services.hrrr_runs import HRRRCacheConfig
from app.services.paths import default_hrrr_cache_dir
from app.services.variable_registry import normalize_api_variable, select_dataarray

EPS = 1e-9


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


def compute_scale_params(
    da: xr.DataArray,
    p_low: float,
    p_high: float,
    log_scale: bool,
    eps: float = EPS,
) -> tuple[float, float]:
    data = np.asarray(da.values, dtype=np.float32)
    if log_scale:
        data = np.where(data > eps, np.log10(data), np.nan)
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return 0.0, 1.0
    return (
        float(np.nanpercentile(finite, p_low)),
        float(np.nanpercentile(finite, p_high)),
    )


def _lambert_grid_from_attrs(da: xr.DataArray) -> tuple[np.ndarray, np.ndarray, np.ndarray, CRS]:
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
    values = np.asarray(da.values)

    if values.shape != (ny, nx):
        raise ValueError(f"Values shape {values.shape} does not match GRIB grid {ny}x{nx}")

    if i_scans_neg:
        x_coords = x_coords[::-1]
        values = values[:, ::-1]
    if not j_scans_pos:
        y_coords = y_coords[::-1]
        values = values[::-1, :]

    if x_coords[1] < x_coords[0]:
        x_coords = x_coords[::-1]
        values = values[:, ::-1]
    if y_coords[1] > y_coords[0]:
        y_coords = y_coords[::-1]
        values = values[::-1, :]

    return values, x_coords, y_coords, lambert_crs


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


def write_byte_geotiff_from_da(
    da: xr.DataArray,
    out_tif: Path,
    *,
    vmin: float,
    vmax: float,
    log_scale: bool,
    eps: float = EPS,
) -> Path:
    values, x_coords, y_coords, lambert_crs = _lambert_grid_from_attrs(da)

    source = np.array(values, dtype=np.float32)
    if log_scale:
        alpha_mask = np.isfinite(source) & (source > eps)
    else:
        alpha_mask = np.isfinite(source)

    data = source
    if log_scale:
        data = np.where(alpha_mask, np.log10(source), np.nan)

    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin == vmax:
        vmin, vmax = 0.0, 1.0

    scaled = (data - vmin) / (vmax - vmin)
    scaled = np.clip(scaled, 0.0, 1.0)
    scaled = np.where(np.isfinite(scaled), scaled, 0.0)
    byte_data = (scaled * 255.0).astype(np.uint8)
    alpha = np.where(alpha_mask, 255, 0).astype(np.uint8)

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
    alpha.tofile(band2_path)

    _write_vrt(
        vrt_path,
        x_size=byte_data.shape[1],
        y_size=byte_data.shape[0],
        geotransform=geotransform,
        srs_wkt=lambert_crs.to_wkt(),
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


def warp_to_3857(src_tif: Path, dst_tif: Path) -> None:
    require_gdal("gdalwarp")
    dst_tif.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(
        [
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
            str(src_tif),
            str(dst_tif),
        ]
    )


def build_mbtiles_from_3857_tif(
    warped_tif: Path,
    mbtiles_path: Path,
    *,
    z_min: int,
    z_max: int,
) -> None:
    require_gdal("gdal_translate")
    mbtiles_path.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(
        [
            "gdal_translate",
            "-of",
            "MBTILES",
            "-b",
            "1",
            "-b",
            "2",
            "-co",
            "TILE_FORMAT=PNG",
            "-co",
            "ZOOM_LEVEL_STRATEGY=LOWER",
            "-co",
            f"MINZOOM={z_min}",
            "-co",
            f"MAXZOOM={z_max}",
            str(warped_tif),
            str(mbtiles_path),
        ]
    )
    # Note: skip gdaladdo for MBTiles to avoid redundant/bloated overviews.


def to_rgba_geotiff(src_tif: Path, rgba_tif: Path) -> None:
    require_gdal("gdal_translate")
    rgba_tif.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(
        [
            "gdal_translate",
            "-of",
            "GTiff",
            "-b",
            "1",
            "-b",
            "1",
            "-b",
            "1",
            "-b",
            "2",
            "-co",
            "TILED=YES",
            "-co",
            "COMPRESS=DEFLATE",
            str(src_tif),
            str(rgba_tif),
        ]
    )


def update_mbtiles_metadata(
    mbtiles_path: Path,
    *,
    bounds_wgs84: tuple[float, float, float, float],
    minzoom: int,
    maxzoom: int,
    name: str,
    center: tuple[float, float, int],
) -> None:
    conn = sqlite3.connect(str(mbtiles_path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT);")
        minlon, minlat, maxlon, maxlat = bounds_wgs84
        bounds_str = f"{minlon:.6f},{minlat:.6f},{maxlon:.6f},{maxlat:.6f}"
        center_str = f"{center[0]:.6f},{center[1]:.6f},{center[2]}"
        managed_keys = [
            "name",
            "format",
            "minzoom",
            "maxzoom",
            "bounds",
            "center",
            "type",
            "version",
        ]
        conn.executemany(
            "DELETE FROM metadata WHERE name = ?;",
            [(key,) for key in managed_keys],
        )
        entries = [
            ("name", name),
            ("format", "png"),
            ("minzoom", str(minzoom)),
            ("maxzoom", str(maxzoom)),
            ("bounds", bounds_str),
            ("center", center_str),
            ("type", "overlay"),
            ("version", "1"),
        ]
        conn.executemany(
            "INSERT INTO metadata (name, value) VALUES (?, ?);",
            entries,
        )
        conn.commit()
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build HRRR MBTiles for a run/fh/variable.")
    parser.add_argument("--cache-dir", type=str, default=None)
    parser.add_argument("--run", type=str, default="latest")
    parser.add_argument("--fh", type=int, required=True)
    parser.add_argument("--var", type=str, required=True)
    parser.add_argument("--z-min", type=int, default=5)
    parser.add_argument("--z-max", type=int, default=11)
    parser.add_argument("--out", type=str, default="/tmp/hrrr.mbtiles")
    parser.add_argument("--p-low", type=float, default=2.0)
    parser.add_argument("--p-high", type=float, default=98.0)
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--keep-cycles", type=int, default=None)
    return parser.parse_args()


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


def needs_rebuild(byte_tif: Path) -> bool:
    if not byte_tif.exists() or byte_tif.stat().st_size == 0:
        return True
    try:
        info = gdalinfo_json(byte_tif)
        assert_alpha_present(info)
        return False
    except Exception:
        return True


def main() -> int:
    args = parse_args()
    cache_dir = Path(args.cache_dir) if args.cache_dir else default_hrrr_cache_dir()
    cfg = HRRRCacheConfig(base_dir=cache_dir, keep_runs=1)

    try:
        grib_path = fetch_hrrr_grib(
            run=args.run,
            fh=args.fh,
            variable=args.var,
            cache_cfg=cfg,
        )
    except Exception as exc:
        print(f"ERROR: Failed to fetch HRRR GRIB: {exc}", file=sys.stderr)
        return 2

    print(f"GRIB path: {grib_path}")

    ds: xr.Dataset | None = None
    try:
        try:
            ds = xr.open_dataset(grib_path, engine="cfgrib")
        except Exception as exc:
            message = str(exc)
            if "multiple values for unique key" in message:
                print(
                    "ERROR: cfgrib index collision. Ensure subsetting worked for the requested variable.\n"
                    f"{exc}",
                    file=sys.stderr,
                )
            elif "eccodes" in message.lower() or "ecCodes" in message or "Cannot find the ecCodes library" in message:
                print(
                    "ERROR: Failed to open GRIB with cfgrib. ecCodes library not available.\n"
                    f"{exc}",
                    file=sys.stderr,
                )
            else:
                print(f"ERROR: Failed to open GRIB with cfgrib.\n{exc}", file=sys.stderr)
            return 3

        normalized_var = normalize_api_variable(args.var)
        try:
            da = select_dataarray(ds, normalized_var)
        except Exception as exc:
            print(
                f"ERROR: Failed to select variable '{args.var}' (normalized='{normalized_var}'): {exc}",
                file=sys.stderr,
            )
            return 4

        if "time" in da.dims:
            da = da.isel(time=0)
        da = da.squeeze()

        try:
            da = normalize_latlon_coords(da)
            lat_name, lon_name = detect_latlon_names(da)
        except Exception as exc:
            print(f"ERROR: Failed to normalize lat/lon coords: {exc}", file=sys.stderr)
            return 5

        lat_vals = da.coords[lat_name].values
        lon_vals = da.coords[lon_name].values
        print(
            f"Requested var '{args.var}' normalized to '{normalized_var}' using dataset var '{da.name}'\n"
            f"lat[{lat_name}] min={np.nanmin(lat_vals):.4f} max={np.nanmax(lat_vals):.4f}\n"
            f"lon[{lon_name}] min={np.nanmin(lon_vals):.4f} max={np.nanmax(lon_vals):.4f}"
        )

        bounds_wgs84 = (
            float(np.nanmin(lon_vals)),
            float(np.nanmin(lat_vals)),
            float(np.nanmax(lon_vals)),
            float(np.nanmax(lat_vals)),
        )

        try:
            vmin, vmax = compute_scale_params(da, args.p_low, args.p_high, args.log, EPS)
            print(f"Scale params: vmin={vmin:.4f} vmax={vmax:.4f} log={args.log}")

            run_dir = grib_path.parent
            warp_dir = run_dir / "warp" / normalized_var
            base_name = grib_path.stem
            byte_tif = warp_dir / f"{base_name}.byte.tif"
            warped_tif = warp_dir / f"{base_name}.3857.tif"
            rgba_tif = warp_dir / f"{base_name}.3857.rgba.tif"

            start_time = time.time()
            rebuild_byte = needs_rebuild(byte_tif)

            if rebuild_byte:
                print(f"Writing byte GeoTIFF: {byte_tif}")
                write_byte_geotiff_from_da(
                    da,
                    byte_tif,
                    vmin=vmin,
                    vmax=vmax,
                    log_scale=args.log,
                    eps=EPS,
                )

            if not warped_tif.exists() or warped_tif.stat().st_size == 0 or rebuild_byte:
                print(f"Warping to EPSG:3857: {warped_tif}")
                warp_to_3857(byte_tif, warped_tif)
            else:
                print(f"Reusing warped GeoTIFF: {warped_tif}")

            info = gdalinfo_json(warped_tif)
            assert_alpha_present(info)
            log_warped_info(warped_tif, info)

            if not rgba_tif.exists() or rgba_tif.stat().st_size == 0:
                print(f"Building RGBA GeoTIFF: {rgba_tif}")
                to_rgba_geotiff(warped_tif, rgba_tif)

            out_path = Path(args.out)
            if out_path.exists():
                out_path.unlink()

            print(f"Building MBTiles: {out_path}")
            build_mbtiles_from_3857_tif(
                rgba_tif,
                out_path,
                z_min=args.z_min,
                z_max=args.z_max,
            )

            center_lon = (bounds_wgs84[0] + bounds_wgs84[2]) / 2.0
            center_lat = (bounds_wgs84[1] + bounds_wgs84[3]) / 2.0
            update_mbtiles_metadata(
                out_path,
                bounds_wgs84=bounds_wgs84,
                minzoom=args.z_min,
                maxzoom=args.z_max,
                name=out_path.stem,
                center=(center_lon, center_lat, args.z_min),
            )

            elapsed = time.time() - start_time
            print(f"Done: MBTiles built in {elapsed:.1f}s")
        except Exception as exc:
            print(f"ERROR: GDAL pipeline failed: {exc}", file=sys.stderr)
            return 6
    finally:
        if ds is not None:
            ds.close()

    if args.keep_cycles:
        try:
            summary = ensure_latest_cycles(keep_cycles=args.keep_cycles, cache_cfg=cfg)
        except Exception as exc:
            print(f"WARN: Failed to enforce cycle retention: {exc}", file=sys.stderr)
            return 7
        print(f"Retention: {summary}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

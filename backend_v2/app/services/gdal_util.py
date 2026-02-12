from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import xarray as xr
from pyproj import Transformer

from app.services.georef import derive_georef

logger = logging.getLogger(__name__)

_OVERVIEW_LEVELS = ["2", "4", "8", "16", "32", "64"]
_GDALADDO_MASK_SUPPORTED: bool | None = None


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


def run_cmd_output(args: list[str]) -> str:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Command failed ({' '.join(args)}): {stderr or 'unknown error'}")
    return "\n".join(chunk for chunk in (result.stdout, result.stderr) if chunk)


def run_cmd_json(args: list[str]) -> dict:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Command failed ({' '.join(args)}): {stderr or 'unknown error'}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse JSON from {' '.join(args)}") from exc


def gdalinfo_json(path: Path) -> dict:
    require_gdal("gdalinfo")
    return run_cmd_json(["gdalinfo", "-json", str(path)])


def wgs84_bbox_to_3857(
    bbox_wgs84: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = bbox_wgs84
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    minx, miny = transformer.transform(min_lon, min_lat)
    maxx, maxy = transformer.transform(max_lon, max_lat)
    return minx, miny, maxx, maxy


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


def _write_single_band_vrt(
    vrt_path: Path,
    *,
    x_size: int,
    y_size: int,
    geotransform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
    band_path: Path,
    data_type: str,
    nodata: float | None = None,
) -> None:
    srs_escaped = escape(srs_wkt)
    nodata_xml = f"\n    <NoDataValue>{nodata}</NoDataValue>" if nodata is not None else ""
    vrt = f"""
<VRTDataset rasterXSize=\"{x_size}\" rasterYSize=\"{y_size}\">
  <SRS>{srs_escaped}</SRS>
  <GeoTransform>{','.join(f'{v:.10f}' for v in geotransform)}</GeoTransform>
  <VRTRasterBand dataType=\"{data_type}\" band=\"1\" subClass=\"VRTRawRasterBand\">
    <Description>values</Description>
    <ColorInterp>Gray</ColorInterp>{nodata_xml}
    <SourceFilename relativeToVRT=\"0\">{band_path}</SourceFilename>
    <ImageOffset>0</ImageOffset>
    <PixelOffset>{4 if data_type == 'Float32' else 1}</PixelOffset>
    <LineOffset>{x_size * (4 if data_type == 'Float32' else 1)}</LineOffset>
    <ByteOrder>LSB</ByteOrder>
  </VRTRasterBand>
</VRTDataset>
""".strip()
    vrt_path.write_text(vrt)


def build_gdal_translate_gtiff_cmd(
    src: Path,
    dst: Path,
    *,
    output_mode: str | None = None,
    bands: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    cmd = [
        "gdal_translate",
        "-of",
        "GTiff",
        "-co",
        "TILED=YES",
        "-co",
        "COMPRESS=DEFLATE",
        "-co",
        "PHOTOMETRIC=MINISBLACK",
    ]
    if output_mode == "byte_alpha":
        cmd.extend(["-co", "ALPHA=YES"])
    if bands:
        for band in bands:
            cmd.extend(["-b", band])
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend([str(src), str(dst)])
    return cmd


def write_byte_geotiff_from_arrays(
    da: xr.DataArray,
    byte_band: np.ndarray,
    alpha_band: np.ndarray,
    out_tif: Path,
    *,
    meta: dict | None = None,
) -> tuple[Path, bool]:
    georef = derive_georef(da, [byte_band, alpha_band])
    byte_data = np.asarray(georef.arrays[0], dtype=np.uint8)
    alpha_data = np.asarray(georef.arrays[1], dtype=np.uint8)

    if georef.used_latlon:
        logger.info(
            "Lat/lon fallback transform: dx=%.3f dy=%.3f x=[%.2f,%.2f] y=[%.2f,%.2f] source=%s",
            georef.dx,
            georef.dy,
            georef.x_range[0],
            georef.x_range[1],
            georef.y_range[0],
            georef.y_range[1],
            georef.source,
        )
    else:
        logger.info(
            "Lambert grid transform: dx=%.3f dy=%.3f x=[%.2f,%.2f] y=[%.2f,%.2f]",
            georef.dx,
            georef.dy,
            georef.x_range[0],
            georef.x_range[1],
            georef.y_range[0],
            georef.y_range[1],
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
        geotransform=georef.geotransform,
        srs_wkt=georef.srs_wkt,
        band1_path=band1_path,
        band2_path=band2_path,
    )

    require_gdal("gdal_translate")
    output_mode = (meta or {}).get("output_mode")
    run_cmd(
        build_gdal_translate_gtiff_cmd(
            vrt_path,
            out_tif,
            output_mode=output_mode,
            bands=["1", "2"],
        )
    )

    for temp_path in (band1_path, band2_path, vrt_path):
        try:
            temp_path.unlink()
        except OSError:
            pass

    return out_tif, georef.used_latlon


def write_float_geotiff_from_array(
    da: xr.DataArray,
    float_band: np.ndarray,
    out_tif: Path,
) -> tuple[Path, bool]:
    nodata = -9999.0
    georef = derive_georef(da, [float_band])
    float_data = np.asarray(georef.arrays[0], dtype=np.float32)
    float_data = np.where(np.isfinite(float_data), float_data, nodata).astype(np.float32)

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    band_path = out_tif.with_suffix(".band1.f32.bin")
    vrt_path = out_tif.with_suffix(".vrt")
    float_data.astype(np.float32).tofile(band_path)

    _write_single_band_vrt(
        vrt_path,
        x_size=float_data.shape[1],
        y_size=float_data.shape[0],
        geotransform=georef.geotransform,
        srs_wkt=georef.srs_wkt,
        band_path=band_path,
        data_type="Float32",
        nodata=nodata,
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

    for temp_path in (band_path, vrt_path):
        try:
            temp_path.unlink()
        except OSError:
            pass

    return out_tif, georef.used_latlon


def _read_geotiff_band_float32(path: Path, *, band: int = 1) -> np.ndarray:
    info = gdalinfo_json(path)
    size = info.get("size") or []
    if len(size) != 2:
        raise RuntimeError(f"Unable to read raster size from {path}")
    width = int(size[0])
    height = int(size[1])
    nodata_value = None
    bands = info.get("bands") or []
    if 1 <= band <= len(bands):
        nodata_value = (bands[band - 1] or {}).get("noDataValue")

    raw_path = path.with_suffix(f".band{band}.f32.envi")
    require_gdal("gdal_translate")
    run_cmd(
        [
            "gdal_translate",
            "-of",
            "ENVI",
            "-ot",
            "Float32",
            "-b",
            str(band),
            str(path),
            str(raw_path),
        ]
    )
    try:
        arr = np.fromfile(raw_path, dtype=np.float32)
        expected = width * height
        if arr.size != expected:
            raise RuntimeError(
                f"Unexpected raster byte count for {path}: got={arr.size} expected={expected}"
            )
        arr = arr.reshape((height, width))
        if nodata_value is not None:
            nodata_float = float(nodata_value)
            arr = np.where(np.isclose(arr, nodata_float, atol=1e-6), np.nan, arr)
        return arr
    finally:
        for suffix in ("", ".hdr", ".aux.xml"):
            try:
                Path(str(raw_path) + suffix).unlink()
            except OSError:
                pass


def _extract_raster_georef(
    path: Path,
) -> tuple[int, int, tuple[float, float, float, float, float, float], str]:
    info = gdalinfo_json(path)
    size = info.get("size") or []
    if len(size) != 2:
        raise RuntimeError(f"Unable to read raster size from {path}")
    geotransform_values = info.get("geoTransform") or []
    if len(geotransform_values) != 6:
        raise RuntimeError(f"Unable to read geoTransform from {path}")
    coord_sys = info.get("coordinateSystem") or {}
    srs_wkt = str(coord_sys.get("wkt") or "").strip()
    if not srs_wkt:
        raise RuntimeError(f"Unable to read coordinate system WKT from {path}")
    width = int(size[0])
    height = int(size[1])
    geotransform = tuple(float(v) for v in geotransform_values)
    return width, height, geotransform, srs_wkt


def write_byte_geotiff_singleband_from_georef(
    *,
    byte_band: np.ndarray,
    out_tif: Path,
    geotransform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
    nodata: int | None = None,
) -> Path:
    if byte_band.ndim != 2:
        raise ValueError(f"Expected 2D byte array, got shape={byte_band.shape}")

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    band1_path = out_tif.with_suffix(".band1.bin")
    vrt_path = out_tif.with_suffix(".vrt")
    np.asarray(byte_band, dtype=np.uint8).tofile(band1_path)

    _write_single_band_vrt(
        vrt_path,
        x_size=byte_band.shape[1],
        y_size=byte_band.shape[0],
        geotransform=geotransform,
        srs_wkt=srs_wkt,
        band_path=band1_path,
        data_type="Byte",
        nodata=float(nodata) if nodata is not None else None,
    )

    require_gdal("gdal_translate")
    cmd = build_gdal_translate_gtiff_cmd(
        vrt_path,
        out_tif,
        bands=["1"],
        extra_args=["-a_nodata", str(nodata)] if nodata is not None else None,
    )
    run_cmd(cmd)

    for temp_path in (band1_path, vrt_path):
        try:
            temp_path.unlink()
        except OSError:
            pass

    return out_tif


def write_byte_geotiff_from_georef(
    *,
    byte_band: np.ndarray,
    alpha_band: np.ndarray,
    out_tif: Path,
    geotransform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
    meta: dict | None = None,
) -> Path:
    if byte_band.shape != alpha_band.shape:
        raise ValueError(
            f"byte/alpha shape mismatch: byte={byte_band.shape} alpha={alpha_band.shape}"
        )
    if byte_band.ndim != 2:
        raise ValueError(f"Expected 2D byte array, got shape={byte_band.shape}")

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    band1_path = out_tif.with_suffix(".band1.bin")
    band2_path = out_tif.with_suffix(".band2.bin")
    vrt_path = out_tif.with_suffix(".vrt")
    np.asarray(byte_band, dtype=np.uint8).tofile(band1_path)
    np.asarray(alpha_band, dtype=np.uint8).tofile(band2_path)

    _write_vrt(
        vrt_path,
        x_size=byte_band.shape[1],
        y_size=byte_band.shape[0],
        geotransform=geotransform,
        srs_wkt=srs_wkt,
        band1_path=band1_path,
        band2_path=band2_path,
    )

    require_gdal("gdal_translate")
    output_mode = (meta or {}).get("output_mode")
    run_cmd(
        build_gdal_translate_gtiff_cmd(
            vrt_path,
            out_tif,
            output_mode=output_mode,
            bands=["1", "2"],
        )
    )

    for temp_path in (band1_path, band2_path, vrt_path):
        try:
            temp_path.unlink()
        except OSError:
            pass

    return out_tif


def build_gdalwarp_3857_cmd(
    src_tif: Path,
    dst_tif: Path,
    *,
    resampling: str = "bilinear",
    tr_meters: tuple[float, float] | None = None,
    tap: bool = True,
    with_alpha: bool = True,
    clip_bounds_3857: tuple[float, float, float, float] | None = None,
) -> list[str]:
    if resampling not in {"near", "bilinear"}:
        raise ValueError(f"Unsupported warp resampling: {resampling}")
    cmd = [
        "gdalwarp",
        "-t_srs",
        "EPSG:3857",
        "-r",
        resampling,
        "-co",
        "TILED=YES",
        "-co",
        "COMPRESS=DEFLATE",
        "-overwrite",
    ]
    if with_alpha:
        cmd.extend(["-srcalpha", "-dstalpha"])
    if tr_meters is not None:
        xres, yres = tr_meters
        cmd.extend(["-tr", str(xres), str(yres)])
        if tap:
            cmd.append("-tap")
    if clip_bounds_3857 is not None:
        minx, miny, maxx, maxy = clip_bounds_3857
        cmd.extend(
            [
                "-te",
                str(minx),
                str(miny),
                str(maxx),
                str(maxy),
                "-te_srs",
                "EPSG:3857",
            ]
        )
    cmd.extend([str(src_tif), str(dst_tif)])
    return cmd


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


def assert_single_internal_overview_cog(path: Path) -> None:
    info = gdalinfo_json(path)
    files = [str(item).lower() for item in (info.get("files") or [])]
    if any(item.endswith(".ovr") for item in files):
        raise RuntimeError(f"COG invariant failed: external .ovr found for {path}")

    bands = info.get("bands") or []
    if len(bands) < 1:
        raise RuntimeError(f"COG invariant failed: expected at least 1 band for {path}")

    missing_band_overviews_idx = [
        index for index, band in enumerate(bands) if not ((band or {}).get("overviews") or [])
    ]
    missing_band_overviews = [str(index + 1) for index in missing_band_overviews_idx]
    if missing_band_overviews:
        alpha_band_indexes = [
            index
            for index, band in enumerate(bands)
            if str((band or {}).get("colorInterpretation", "")).lower() == "alpha"
            or str((band or {}).get("description", "")).lower() == "alpha"
        ]
        data_band_has_overviews = any(
            ((band or {}).get("overviews") or [])
            for index, band in enumerate(bands)
            if index not in alpha_band_indexes
        )
        missing_only_alpha = bool(alpha_band_indexes) and set(missing_band_overviews_idx).issubset(
            set(alpha_band_indexes)
        )
        if missing_only_alpha and data_band_has_overviews:
            logger.warning(
                "COG invariant relaxed: missing internal overviews on alpha band(s)=%s",
                ",".join(missing_band_overviews),
            )
            missing_band_overviews = []

    if missing_band_overviews:
        raise RuntimeError(
            "COG invariant failed: missing internal band overviews on bands="
            + ",".join(missing_band_overviews)
        )

    missing_mask_overviews = [
        str(index + 1)
        for index, band in enumerate(bands)
        if not (((band or {}).get("mask") or {}).get("overviews") or [])
    ]
    if missing_mask_overviews:
        if _gdaladdo_supports_mask():
            raise RuntimeError(
                "COG invariant failed: missing internal mask overviews on bands="
                + ",".join(missing_mask_overviews)
            )
        logger.warning(
            "COG invariant relaxed: missing internal mask overviews on bands=%s because gdaladdo -mask is unavailable",
            ",".join(missing_mask_overviews),
        )


def _is_external_overview_conflict(exc: RuntimeError) -> bool:
    return "Cannot add external overviews when there are already internal overviews" in str(exc)


def _is_copy_src_overviews_unsupported(exc: RuntimeError) -> bool:
    message = str(exc)
    return (
        "driver COG does not support creation option COPY_SRC_OVERVIEWS" in message
        or "COPY_SRC_OVERVIEWS cannot be used" in message
    )


def _gdaladdo_supports_mask() -> bool:
    global _GDALADDO_MASK_SUPPORTED
    if _GDALADDO_MASK_SUPPORTED is not None:
        return _GDALADDO_MASK_SUPPORTED
    try:
        output = run_cmd_output(["gdaladdo", "--help"])
    except RuntimeError:
        _GDALADDO_MASK_SUPPORTED = False
        return False
    _GDALADDO_MASK_SUPPORTED = "-mask" in output
    return _GDALADDO_MASK_SUPPORTED


def run_gdaladdo_overviews(
    cog_path: Path,
    band1_resampling: str,
    band2_resampling: str,
) -> None:
    del band2_resampling
    require_gdal("gdaladdo")
    base_cmd = [
        "gdaladdo",
        "--config",
        "GDAL_TIFF_INTERNAL_OVERVIEW",
        "YES",
        "--config",
        "COMPRESS_OVERVIEW",
        "DEFLATE",
        "--config",
        "INTERLEAVE_OVERVIEW",
        "PIXEL",
        "--config",
        "GTIFF_FORCE_EXTERNAL_OVR",
        "NO",
        "--config",
        "USE_RRD",
        "NO",
    ]

    def _run(resampling: str, extra_args: list[str]) -> None:
        run_cmd(base_cmd + ["-r", resampling] + extra_args + [str(cog_path)] + _OVERVIEW_LEVELS)

    run_cmd(base_cmd + ["-clean", str(cog_path)])

    info_before = gdalinfo_json(cog_path)
    bands_before = info_before.get("bands") or []
    ovr_counts_before = [len((b or {}).get("overviews") or []) for b in bands_before]
    logger.info(
        "gdaladdo: before adding overviews path=%s bands=%d band_overview_counts=%s",
        cog_path.name,
        len(bands_before),
        ovr_counts_before,
    )

    has_alpha_band = False
    if len(bands_before) >= 2:
        band2 = bands_before[1] or {}
        color_interp = band2.get("colorInterpretation", "")
        mask_flags = (
            band2.get("mask", {}).get("flags", []) if isinstance(band2.get("mask"), dict) else []
        )
        if color_interp == "Alpha" or "ALPHA" in str(mask_flags):
            has_alpha_band = True
            logger.info("Detected alpha band; adjusting overview generation strategy")

    try:
        if has_alpha_band and band1_resampling == "nearest":
            logger.info("Using all-band nearest resampling for alpha-channel COG")
            _run("nearest", [])
        elif has_alpha_band and band1_resampling != "nearest":
            _run(band1_resampling, ["-b", "1"])
            _run("nearest", ["-b", "2"])
        else:
            _run(band1_resampling, ["-b", "1"])
            if len(bands_before) >= 2:
                _run("nearest", ["-b", "2"])

        info_after_band = gdalinfo_json(cog_path)
        bands_after_band = info_after_band.get("bands") or []
        ovr_counts_after_band = [len((b or {}).get("overviews") or []) for b in bands_after_band]
        logger.info(
            "gdaladdo: after overview generation path=%s bands=%d band_overview_counts=%s",
            cog_path.name,
            len(bands_after_band),
            ovr_counts_after_band,
        )
    except RuntimeError as exc:
        if not _is_external_overview_conflict(exc):
            raise
        logger.warning(
            "Band-specific gdaladdo overviews are not supported by this GDAL build; "
            "falling back to all-band overviews with resampling=%s",
            band1_resampling,
        )
        run_cmd(base_cmd + ["-clean", str(cog_path)])
        _run(band1_resampling, [])
        return

    if _gdaladdo_supports_mask():
        try:
            _run("nearest", ["-mask", "1"])
        except RuntimeError as exc:
            logger.warning("gdaladdo -mask failed; keeping current internal overviews: %s", exc)
    else:
        logger.warning("gdaladdo does not support -mask; keeping current internal overviews")


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
    logger.info(
        "Warped GeoTIFF info: path=%s width=%s height=%s bands=%s bounds_3857=(%.2f,%.2f,%.2f,%.2f)",
        path,
        size[0],
        size[1],
        len(info.get("bands") or []),
        lower_left[0],
        lower_left[1],
        upper_right[0],
        upper_right[1],
    )


def _band_min_max(info: dict, band_index: int) -> tuple[float | None, float | None]:
    bands = info.get("bands") or []
    if band_index < 1 or band_index > len(bands):
        return None, None
    band = bands[band_index - 1] or {}

    def _to_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    min_val = _to_float(band.get("minimum"))
    max_val = _to_float(band.get("maximum"))
    if min_val is not None and max_val is not None:
        return min_val, max_val

    metadata = band.get("metadata") or {}
    if isinstance(metadata, dict):
        for _, domain_values in metadata.items():
            if not isinstance(domain_values, dict):
                continue
            if min_val is None:
                min_val = _to_float(
                    domain_values.get("STATISTICS_MINIMUM")
                    or domain_values.get("STATISTICS_APPROXIMATE_MINIMUM")
                )
            if max_val is None:
                max_val = _to_float(
                    domain_values.get("STATISTICS_MAXIMUM")
                    or domain_values.get("STATISTICS_APPROXIMATE_MAXIMUM")
                )
            if min_val is not None and max_val is not None:
                break

    return min_val, max_val

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import xarray as xr
from pyproj import CRS, Transformer

from app.services.grid import detect_latlon_names, normalize_latlon_coords


@dataclass(frozen=True)
class GeorefDerivation:
    arrays: tuple[np.ndarray, ...]
    geotransform: tuple[float, float, float, float, float, float]
    srs_wkt: str
    used_latlon: bool
    source: str
    x_range: tuple[float, float]
    y_range: tuple[float, float]
    dx: float
    dy: float


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
        raise ValueError("Expected 1D latitude/longitude coordinates")

    lon_wrapped = _normalize_lon_1d(lon)
    da = da.assign_coords({lon_name: (da.coords[lon_name].dims, lon_wrapped)})
    da = da.sortby(lon_name)

    lat_sorted = da.coords[lat_name].values
    if lat_sorted[0] < lat_sorted[-1]:
        da = da.sortby(lat_name, ascending=False)

    return da, lat_name, lon_name


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


def _latlon_axes_from_grib_attrs(
    da: xr.DataArray,
    *,
    expected_shape: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    attrs = da.attrs
    ny_expected, nx_expected = expected_shape

    def _int_attr(*keys: str, default: int | None = None) -> int:
        for key in keys:
            value = attrs.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        if default is not None:
            return default
        raise ValueError(f"Missing integer GRIB attr: one of {keys}")

    def _float_attr(*keys: str) -> float:
        for key in keys:
            value = attrs.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        raise ValueError(f"Missing float GRIB attr: one of {keys}")

    nx = _int_attr("GRIB_Nx", "GRIB_Ni", default=nx_expected)
    ny = _int_attr("GRIB_Ny", "GRIB_Nj", default=ny_expected)
    if nx != nx_expected or ny != ny_expected:
        raise ValueError(
            f"GRIB axis shape mismatch: attrs={ny}x{nx} expected={ny_expected}x{nx_expected}"
        )

    lon_first = _float_attr("GRIB_longitudeOfFirstGridPointInDegrees")
    lat_first = _float_attr("GRIB_latitudeOfFirstGridPointInDegrees")
    lon_last = _float_attr("GRIB_longitudeOfLastGridPointInDegrees")
    lat_last = _float_attr("GRIB_latitudeOfLastGridPointInDegrees")

    i_scan_neg = int(attrs.get("GRIB_iScansNegatively", 0)) == 1
    j_scan_pos = int(attrs.get("GRIB_jScansPositively", 1)) == 1

    try:
        dx_deg = abs(float(attrs.get("GRIB_iDirectionIncrementInDegrees")))
    except (TypeError, ValueError):
        dx_deg = None
    try:
        dy_deg = abs(float(attrs.get("GRIB_jDirectionIncrementInDegrees")))
    except (TypeError, ValueError):
        dy_deg = None

    if dx_deg and np.isfinite(dx_deg) and dx_deg > 0:
        lon_sign = -1.0 if i_scan_neg else 1.0
        lon = lon_first + lon_sign * np.arange(nx, dtype=np.float64) * dx_deg
    else:
        lon = np.linspace(lon_first, lon_last, nx, dtype=np.float64)

    if dy_deg and np.isfinite(dy_deg) and dy_deg > 0:
        lat_sign = 1.0 if j_scan_pos else -1.0
        lat = lat_first + lat_sign * np.arange(ny, dtype=np.float64) * dy_deg
    else:
        lat = np.linspace(lat_first, lat_last, ny, dtype=np.float64)

    return np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)


def _apply_scan_order(data: np.ndarray, grid: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    nx = grid["nx"]
    ny = grid["ny"]
    if data.shape != (ny, nx):
        raise ValueError(f"Values shape {data.shape} does not match GRIB grid {ny}x{nx}")

    x_coords = np.array(grid["x_coords"], copy=True)
    y_coords = np.array(grid["y_coords"], copy=True)
    data_out = np.array(data, copy=True)

    if grid["i_scans_neg"]:
        x_coords = x_coords[::-1]
        data_out = data_out[:, ::-1]
    if not grid["j_scans_pos"]:
        y_coords = y_coords[::-1]
        data_out = data_out[::-1, :]

    if x_coords[1] < x_coords[0]:
        x_coords = x_coords[::-1]
        data_out = data_out[:, ::-1]
    if y_coords[1] > y_coords[0]:
        y_coords = y_coords[::-1]
        data_out = data_out[::-1, :]

    return data_out, x_coords, y_coords


def derive_georef(da: xr.DataArray, arrays: Sequence[np.ndarray]) -> GeorefDerivation:
    if not arrays:
        raise ValueError("derive_georef requires at least one array")
    first_shape = arrays[0].shape
    for arr in arrays:
        if arr.shape != first_shape:
            raise ValueError(
                f"All arrays must share the same shape: first={first_shape} got={arr.shape}"
            )
        if arr.ndim != 2:
            raise ValueError(f"Expected 2D array input, got shape={arr.shape}")

    try:
        grid = _lambert_grid_from_attrs(da)
        transformed = []
        x_coords: np.ndarray | None = None
        y_coords: np.ndarray | None = None
        for arr in arrays:
            arr_data, x_out, y_out = _apply_scan_order(np.asarray(arr), grid)
            transformed.append(np.asarray(arr_data))
            if x_coords is None:
                x_coords = x_out
            if y_coords is None:
                y_coords = y_out

        assert x_coords is not None
        assert y_coords is not None
        dx = abs(x_coords[1] - x_coords[0]) if x_coords.size > 1 else 1.0
        dy = abs(y_coords[1] - y_coords[0]) if y_coords.size > 1 else 1.0
        x_min = float(np.min(x_coords))
        x_max = float(np.max(x_coords))
        y_min = float(np.min(y_coords))
        y_max = float(np.max(y_coords))
        geotransform = (x_min, dx, 0.0, y_max, 0.0, -dy)
        srs_wkt = grid["lambert_crs"].to_wkt()
        return GeorefDerivation(
            arrays=tuple(transformed),
            geotransform=geotransform,
            srs_wkt=srs_wkt,
            used_latlon=False,
            source="lambert",
            x_range=(x_min, x_max),
            y_range=(y_min, y_max),
            dx=float(dx),
            dy=float(dy),
        )
    except ValueError:
        transformed = [np.asarray(arr).copy() for arr in arrays]
        latlon_source = "coords"
        try:
            normalized_da = normalize_latlon_coords(da)
            lat_name, lon_name = detect_latlon_names(normalized_da)
            lat = normalized_da.coords[lat_name].values
            lon = normalized_da.coords[lon_name].values
        except ValueError:
            latlon_source = "grib_attrs"
            lat, lon = _latlon_axes_from_grib_attrs(da, expected_shape=first_shape)

        if lat.ndim != 1 or lon.ndim != 1:
            raise ValueError("Lat/lon fallback expects 1D latitude/longitude arrays")

        lon_wrapped = _normalize_lon_1d(lon.astype(np.float64))
        lon_order = np.argsort(lon_wrapped)
        if not np.array_equal(lon_order, np.arange(lon_order.size)):
            lon_wrapped = lon_wrapped[lon_order]
            transformed = [arr[:, lon_order] for arr in transformed]
        lon = lon_wrapped

        if lat[0] < lat[-1]:
            transformed = [arr[::-1, :] for arr in transformed]
            lat = lat[::-1]

        dx = _infer_spacing(lon, axis_name="longitude") if lon.size > 1 else 1.0
        dy = _infer_spacing(lat, axis_name="latitude") if lat.size > 1 else 1.0
        x_min = float(np.min(lon))
        x_max = float(np.max(lon))
        y_min = float(np.min(lat))
        y_max = float(np.max(lat))
        geotransform = (x_min, dx, 0.0, y_max, 0.0, -dy)
        srs_wkt = CRS.from_epsg(4326).to_wkt()
        return GeorefDerivation(
            arrays=tuple(transformed),
            geotransform=geotransform,
            srs_wkt=srs_wkt,
            used_latlon=True,
            source=latlon_source,
            x_range=(x_min, x_max),
            y_range=(y_min, y_max),
            dx=float(dx),
            dy=float(dy),
        )

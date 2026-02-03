from __future__ import annotations

import numpy as np
import xarray as xr
import logging
from pyproj import CRS, Transformer
from scipy.interpolate import griddata, RegularGridInterpolator

logger = logging.getLogger(__name__)


def detect_latlon_names(ds_or_da: xr.Dataset | xr.DataArray) -> tuple[str, str]:
    coords = ds_or_da.coords
    if "latitude" in coords and "longitude" in coords:
        return "latitude", "longitude"
    if "lat" in coords and "lon" in coords:
        return "lat", "lon"
    raise ValueError("Latitude/longitude coordinates not found in dataset")


def wrap_longitudes(lon_array: np.ndarray) -> np.ndarray:
    return ((lon_array + 180.0) % 360.0) - 180.0


def _ensure_2d_latlon(
    lat: np.ndarray, lon: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    if lat.ndim == 1 and lon.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
        return lat2d, lon2d
    return lat, lon


def normalize_latlon_coords(da: xr.DataArray) -> xr.DataArray:
    lat_name, lon_name = detect_latlon_names(da)
    lat = da.coords[lat_name]
    lon = da.coords[lon_name]

    lon_wrapped = wrap_longitudes(lon.values)

    return da.assign_coords(
        {
            lat_name: (lat.dims, lat.values),
            lon_name: (lon.dims, lon_wrapped),
        }
    )


def reproject_to_web_mercator(
    da: xr.DataArray,
    *,
    width: int,
    height: int,
    bounds_3857: tuple[float, float, float, float],
) -> np.ndarray:
    lat_name, lon_name = detect_latlon_names(da)
    lat = da.coords[lat_name].values
    lon = da.coords[lon_name].values

    lat2d, lon2d = _ensure_2d_latlon(lat, lon)
    values = np.asarray(da.values)

    if lat.ndim == 1 and lon.ndim == 1:
        expected_shape = lat2d.shape
        if values.ndim == 2:
            if values.shape != expected_shape:
                raise ValueError(
                    f"Values shape {values.shape} does not match lat/lon grid {expected_shape}"
                )
        elif values.ndim == 1:
            if values.size == lat.size * lon.size:
                values = values.reshape(expected_shape)
            else:
                raise ValueError(
                    "Values are 1D and cannot be reshaped to match lat/lon grid"
                )
        else:
            raise ValueError("Unsupported values dimensions for 1D lat/lon grid")

    grid_type = str(da.attrs.get("GRIB_gridType", "")).lower()
    if grid_type == "lambert":
        logger.info("Using lambert grid path for reprojection")
        attrs = da.attrs
        try:
            nx = int(attrs.get("GRIB_Nx"))
            ny = int(attrs.get("GRIB_Ny"))
            dx = float(attrs.get("GRIB_DxInMetres"))
            dy = float(attrs.get("GRIB_DyInMetres"))
            lon_0 = wrap_longitudes(float(attrs.get("GRIB_LoVInDegrees")))
            lat_1 = float(attrs.get("GRIB_Latin1InDegrees"))
            lat_2 = float(attrs.get("GRIB_Latin2InDegrees"))
            lat_0 = float(attrs.get("GRIB_LaDInDegrees"))
            lat_first = float(attrs.get("GRIB_latitudeOfFirstGridPointInDegrees"))
            lon_first = wrap_longitudes(
                float(attrs.get("GRIB_longitudeOfFirstGridPointInDegrees"))
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Lambert attrs missing; falling back to lat/lon path: %s", exc)
            grid_type = ""
        if grid_type == "lambert":
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
                raise ValueError(
                    f"Values shape {values.shape} does not match GRIB grid {ny}x{nx}"
                )

            if i_scans_neg:
                x_coords = x_coords[::-1]
                values = values[:, ::-1]
            if not j_scans_pos:
                y_coords = y_coords[::-1]
                values = values[::-1, :]

            minx, miny, maxx, maxy = bounds_3857
            x_tgt = np.linspace(minx, maxx, width)
            y_tgt = np.linspace(maxy, miny, height)
            grid_x, grid_y = np.meshgrid(x_tgt, y_tgt)

            merc_to_lambert = Transformer.from_crs("EPSG:3857", lambert_crs, always_xy=True)
            x_tgt_lam, y_tgt_lam = merc_to_lambert.transform(grid_x, grid_y)

            interpolator = RegularGridInterpolator(
                (y_coords, x_coords),
                values,
                method="linear",
                bounds_error=False,
                fill_value=np.nan,
            )

            samples = np.column_stack([y_tgt_lam.ravel(), x_tgt_lam.ravel()])
            grid = interpolator(samples).reshape((height, width))
            nan_fraction = float(np.isnan(grid).mean())
            logger.info(
                "Lambert grid sample points=%d, NaN fraction=%.4f",
                samples.shape[0],
                nan_fraction,
            )
            return np.asarray(grid, dtype=np.float32)

    logger.info("Using lat/lon griddata fallback path")
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    x_src, y_src = transformer.transform(lon2d, lat2d)

    minx, miny, maxx, maxy = bounds_3857
    pad_x = maxx - minx
    pad_y = maxy - miny
    # Crop to a padded ROI to avoid full-grid triangulation for each tile.
    roi_mask = (
        (x_src >= (minx - pad_x))
        & (x_src <= (maxx + pad_x))
        & (y_src >= (miny - pad_y))
        & (y_src <= (maxy + pad_y))
    )
    x_tgt = np.linspace(minx, maxx, width)
    y_tgt = np.linspace(maxy, miny, height)
    grid_x, grid_y = np.meshgrid(x_tgt, y_tgt)

    if not np.any(roi_mask):
        return np.full((height, width), np.nan, dtype=np.float32)

    mask = roi_mask & np.isfinite(values) & np.isfinite(x_src) & np.isfinite(y_src)
    if not np.any(mask):
        return np.full((height, width), np.nan, dtype=np.float32)

    x_flat = x_src[mask]
    y_flat = y_src[mask]
    v_flat = values[mask]
    points = np.column_stack([x_flat, y_flat])

    if points.shape[0] > 500_000:
        logger.warning(
            "Large ROI (%d points) may impact performance at low zoom",
            points.shape[0],
        )

    if points.shape[0] == 0:
        return np.full((height, width), np.nan, dtype=np.float32)

    grid_linear = griddata(
        points,
        v_flat,
        (grid_x, grid_y),
        method="linear",
        fill_value=np.nan,
    )
    nan_fraction_linear = float(np.isnan(grid_linear).mean())
    logger.info(
        "griddata points=%d, NaN fraction after linear=%.4f",
        points.shape[0],
        nan_fraction_linear,
    )

    if np.isnan(grid_linear).any():
        grid_nearest = griddata(
            points,
            v_flat,
            (grid_x, grid_y),
            method="nearest",
            fill_value=np.nan,
        )
        grid_filled = np.where(np.isfinite(grid_linear), grid_linear, grid_nearest)
        nan_fraction_filled = float(np.isnan(grid_filled).mean())
        logger.info(
            "NaN fraction after nearest fill=%.4f",
            nan_fraction_filled,
        )
        return np.asarray(grid_filled, dtype=np.float32)

    return np.asarray(grid_linear, dtype=np.float32)

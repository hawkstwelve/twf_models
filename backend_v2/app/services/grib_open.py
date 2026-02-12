from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import xarray as xr

from app.models import VarSpec
from app.services.upstream import is_upstream_not_ready_error


class UpstreamNotReadyError(RuntimeError):
    pass


def _coerce_grib_path(grib_path: object) -> Path:
    if hasattr(grib_path, "path"):
        grib_path = getattr(grib_path, "path")
    return Path(os.fspath(grib_path))


def _cfgrib_filter_keys(var_spec: VarSpec | None) -> dict[str, object]:
    if var_spec is None:
        return {}
    selectors = var_spec.selectors
    if not selectors.filter_by_keys:
        return {}
    filter_keys: dict[str, object] = {}
    for key, value in selectors.filter_by_keys.items():
        if key == "level":
            try:
                filter_keys[key] = int(value)
            except (TypeError, ValueError):
                filter_keys[key] = value
        else:
            filter_keys[key] = value
    return filter_keys


def _retry_filters(base_filter_keys: dict[str, object]) -> list[dict[str, object]]:
    retry_filters: list[dict[str, object]] = []
    if base_filter_keys:
        retry_filters.append(dict(base_filter_keys))
        if "stepType" not in base_filter_keys:
            retry_filters.append({**base_filter_keys, "stepType": "instant"})
            retry_filters.append({**base_filter_keys, "stepType": "avg"})
    return retry_filters


def open_cfgrib_dataset(
    grib_path: object,
    var_spec: VarSpec | None,
    *,
    strict: bool = False,
    open_dataset: Callable[..., Any] | None = None,
) -> xr.Dataset:
    path = _coerce_grib_path(grib_path)
    open_fn = open_dataset or xr.open_dataset

    base_filter_keys = _cfgrib_filter_keys(var_spec)
    retry_filters = _retry_filters(base_filter_keys)
    last_exc: Exception | None = None

    for filter_keys in retry_filters:
        try:
            return open_fn(
                path,
                engine="cfgrib",
                backend_kwargs={"filter_by_keys": filter_keys, "indexpath": ""},
            )
        except Exception as exc:
            if is_upstream_not_ready_error(exc):
                raise UpstreamNotReadyError(str(exc)) from exc
            last_exc = exc
            continue

    if strict and retry_filters:
        assert last_exc is not None
        raise RuntimeError(
            f"Failed strict cfgrib open for path={path} filters={retry_filters}: "
            f"{type(last_exc).__name__}: {last_exc}"
        ) from last_exc

    try:
        return open_fn(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    except Exception as exc:
        if is_upstream_not_ready_error(exc):
            raise UpstreamNotReadyError(str(exc)) from exc
        message = str(exc)
        retry_on_multi_key = (
            "multiple values for key" in message
            or "multiple values for unique key" in message
        )
        retry_on_type_hint = "typeOfLevel" in message
        if (retry_on_multi_key or retry_on_type_hint) and not retry_filters:
            for step_type in ("instant", "avg"):
                try:
                    return open_fn(
                        path,
                        engine="cfgrib",
                        backend_kwargs={
                            "filter_by_keys": {"stepType": step_type},
                            "indexpath": "",
                        },
                    )
                except Exception as inner_exc:
                    if is_upstream_not_ready_error(inner_exc):
                        raise UpstreamNotReadyError(str(inner_exc)) from inner_exc
                    continue
        raise

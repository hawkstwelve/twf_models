from __future__ import annotations

from typing import Any

import xarray as xr

VARIABLE_ALIASES: dict[str, str] = {
    "tmp2m": "t2m",
    "2t": "t2m",
}

VARIABLE_SELECTORS: dict[str, dict[str, Any]] = {
    "t2m": {
        "cfVarName": "t2m",
        "shortName": "2t",
        "typeOfLevel": "heightAboveGround",
    },
    "prate": {
        "cfVarName": "prate",
        "shortName": "prate",
        "typeOfLevel": "surface",
    },
}

HERBIE_SEARCH: dict[str, str] = {
    "t2m": ":TMP:2 m above ground:",
    "prate": ":PRATE:surface:",
}


def normalize_api_variable(var: str) -> str:
    value = var.strip().lower()
    return VARIABLE_ALIASES.get(value, value)


def herbie_search_for(api_var: str) -> str | None:
    normalized = normalize_api_variable(api_var)
    return HERBIE_SEARCH.get(normalized)


def _attr_or_na(da: xr.DataArray, key: str) -> str:
    value = da.attrs.get(key)
    return str(value) if value is not None else "n/a"


def fingerprint_da(da: xr.DataArray) -> str:
    return (
        f"varname={da.name} "
        f"cfVarName={_attr_or_na(da, 'GRIB_cfVarName')} "
        f"shortName={_attr_or_na(da, 'GRIB_shortName')} "
        f"paramId={_attr_or_na(da, 'GRIB_paramId')} "
        f"typeOfLevel={_attr_or_na(da, 'GRIB_typeOfLevel')} "
        f"level={_attr_or_na(da, 'GRIB_level')} "
        f"stepType={_attr_or_na(da, 'GRIB_stepType')} "
        f"units={_attr_or_na(da, 'GRIB_units')} "
        f"gridType={_attr_or_na(da, 'GRIB_gridType')}"
    )


def list_available_fingerprints(ds: xr.Dataset) -> list[str]:
    return [fingerprint_da(ds[name]) for name in sorted(ds.data_vars)]


def _score_candidate(da: xr.DataArray, selector: dict[str, Any]) -> int:
    score = 0
    if selector.get("cfVarName") is not None:
        if da.attrs.get("GRIB_cfVarName") == selector["cfVarName"]:
            score += 10
    if selector.get("shortName") is not None:
        if da.attrs.get("GRIB_shortName") == selector["shortName"]:
            score += 8
    if selector.get("typeOfLevel") is not None:
        if da.attrs.get("GRIB_typeOfLevel") == selector["typeOfLevel"]:
            score += 3
    if selector.get("level") is not None:
        if da.attrs.get("GRIB_level") == selector["level"]:
            score += 2
    if selector.get("paramId") is not None:
        if da.attrs.get("GRIB_paramId") == selector["paramId"]:
            score += 5
    return score


def select_dataarray(ds: xr.Dataset, api_var: str) -> xr.DataArray:
    normalized = normalize_api_variable(api_var)
    selector = VARIABLE_SELECTORS.get(normalized)

    direct_candidate = ds.data_vars.get(normalized)

    if selector is None:
        if direct_candidate is not None:
            return direct_candidate
        available = "\n".join(list_available_fingerprints(ds))
        raise ValueError(
            "Variable selection failed\n"
            f"requested={api_var} normalized={normalized}\n"
            "selector=None\n"
            "Available variables:\n"
            f"{available}"
        )

    scored: list[tuple[int, str, xr.DataArray]] = []
    for name in ds.data_vars:
        da = ds[name]
        score = _score_candidate(da, selector)
        if score > 0:
            scored.append((score, name, da))

    scored.sort(key=lambda item: item[0], reverse=True)

    if scored:
        top_score = scored[0][0]
        top_candidates = [item for item in scored if item[0] == top_score]
        if top_score >= 8 and len(top_candidates) == 1:
            return top_candidates[0][2]

    available = "\n".join(list_available_fingerprints(ds))
    candidates = "\n".join(
        f"  {name}: score={score}"
        for score, name, _ in scored[:5]
    )
    raise ValueError(
        "Variable selection failed\n"
        f"requested={api_var} normalized={normalized}\n"
        f"selector={selector}\n"
        f"Top candidates:\n{candidates if candidates else '  (none)'}\n"
        "Available variables:\n"
        f"{available}"
    )

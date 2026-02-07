from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from herbie import Herbie
import requests
import xarray as xr

from app.models import get_model
from app.services.paths import default_gfs_cache_dir

logger = logging.getLogger(__name__)

IDX_FALLBACK_RATE_SECONDS = 300
_IDX_FALLBACK_LOG_CACHE: dict[tuple[str, int], float] = {}
TWF_GFS_PRIORITY = os.environ.get("TWF_GFS_PRIORITY", "aws")
TWF_GFS_HTTP_TIMEOUT_SECONDS = int(os.environ.get("TWF_GFS_HTTP_TIMEOUT_SECONDS", "5"))
TWF_GFS_PROBE_LOOKBACK_HOURS = int(os.environ.get("TWF_GFS_PROBE_LOOKBACK_HOURS", "12"))
TWF_GFS_MAX_PROBE_SECONDS = int(os.environ.get("TWF_GFS_MAX_PROBE_SECONDS", "10"))
TWF_GFS_SKIP_SOURCES = os.environ.get("TWF_GFS_SKIP_SOURCES", "ftpprd.ncep.noaa.gov")


class UpstreamNotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class GribFetchResult:
    path: Path
    is_full_file: bool = False

    def __fspath__(self) -> str:
        return str(self.path)

    def __getattr__(self, name: str):
        return getattr(self.path, name)


def _is_readable_grib(path: Path) -> bool:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return False
        with path.open("rb") as handle:
            return bool(handle.read(4))
    except OSError:
        return False


def _required_grib_vars_for_request(model_id: str, normalized_var: str) -> tuple[list[str], str]:
    from app.models.registry import MODEL_REGISTRY

    fallback_components = ["refc", "crain", "csnow", "cicep", "cfrzr"]
    model = MODEL_REGISTRY.get(model_id)
    if model is None:
        return [normalized_var], "registry_missing"
    var_spec = model.get_var(normalized_var)
    if var_spec is None:
        return [normalized_var], "spec_missing"
    if normalized_var in {"radar_ptype", "radar_ptype_combo"}:
        hints = var_spec.selectors.hints
        return [
            str(hints.get("refl_component") or "refc"),
            str(hints.get("rain_component") or "crain"),
            str(hints.get("snow_component") or "csnow"),
            str(hints.get("sleet_component") or "cicep"),
            str(hints.get("frzr_component") or "cfrzr"),
        ], "registry_hints" if hints else "fallback_default"
    if var_spec.derived and var_spec.derive == "radar_ptype_combo":
        hints = var_spec.selectors.hints
        return [
            str(hints.get("refl_component") or "refc"),
            str(hints.get("rain_component") or "crain"),
            str(hints.get("snow_component") or "csnow"),
            str(hints.get("sleet_component") or "cicep"),
            str(hints.get("frzr_component") or "cfrzr"),
        ], "registry_hints"
    if var_spec.derived and var_spec.derive == "wspd10m":
        hints = var_spec.selectors.hints
        return [
            str(hints.get("u_component") or "10u"),
            str(hints.get("v_component") or "10v"),
        ], "registry_hints"
    return [normalized_var], "registry_default"


def _inventory_strings(herbie: Herbie | None) -> list[str]:
    if herbie is None:
        return []
    try:
        inv = herbie.inventory()
    except Exception as exc:
        logger.info("GFS inventory lookup failed: %r", exc)
        return []
    if inv is None:
        return []
    for key in ("searchString", "variable", "shortName", "cfVarName"):
        if key in inv.columns:
            values = inv[key].dropna().astype(str).tolist()
            if values:
                return values
    try:
        return [str(row) for row in inv.itertuples(index=False)]
    except Exception:
        return []


def _local_grib_varnames(path: Path) -> list[str]:
    def _open_with(filter_keys: dict[str, object] | None) -> xr.Dataset:
        kwargs = {"indexpath": ""}
        if filter_keys:
            kwargs["filter_by_keys"] = filter_keys
        return xr.open_dataset(path, engine="cfgrib", backend_kwargs=kwargs)

    attempts = [None]
    last_exc: Exception | None = None
    for filter_keys in attempts:
        ds = None
        try:
            ds = _open_with(filter_keys)
            return sorted(list(ds.data_vars))
        except Exception as exc:
            last_exc = exc
            message = str(exc)
            if filter_keys is None and ("stepType" in message or "multiple values for key" in message):
                for step_type in ("instant", "avg"):
                    ds_retry = None
                    try:
                        ds_retry = _open_with({"stepType": step_type})
                        return sorted(list(ds_retry.data_vars))
                    except Exception as retry_exc:
                        last_exc = retry_exc
                    finally:
                        if ds_retry is not None:
                            try:
                                ds_retry.close()
                            except Exception:
                                pass
            continue
        finally:
            if ds is not None:
                try:
                    ds.close()
                except Exception:
                    pass
    logger.info("GFS local GRIB inspection failed: %r", last_exc)
    return []


def _subset_contains_required_variables(
    model_id: str | None,
    required_vars: list[str] | None,
    available: list[str] | None,
) -> tuple[bool, list[str], list[str]]:
    """Best-effort validation that a subset GRIB contains all required fields.

    Notes:
    - Herbie inventory fields vary by source (shortName like "TMP", "UGRD" or
      searchString snippets like ":TMP:2 m above ground:").
    - Our API variables are normalized ids ("tmp2m", "10u", "10v", "refc", etc.).

    This matcher expands each required API var into one or more plausible GRIB tokens
    and considers a required var satisfied if ANY token matches the inventory.
    """

    available_list = list(available or [])
    if not required_vars:
        return True, [], available_list

    from app.services.variable_registry import normalize_api_variable

    required_norm = [normalize_api_variable(v) for v in required_vars if str(v).strip()]
    if not required_norm:
        return True, [], available_list

    # Normalize available inventory strings.
    available_upper = [str(item).strip().upper() for item in available_list if str(item).strip()]
    available_norm = [normalize_api_variable(item) for item in available_list if str(item).strip()]

    def _tokens_from_search(var: str) -> list[str]:
        # Try to derive shortName tokens from the model registry/herbie selector search.
        try:
            selectors = _resolve_var_selectors(model_id or "gfs", var)
            search = _select_herbie_search(selectors) or ""
        except Exception:
            search = ""

        tokens: list[str] = []
        if search:
            for alt in str(search).split("|"):
                # Typical pattern: ":TMP:2 m above ground:" -> parts[1] == "TMP"
                parts = [p for p in alt.split(":") if p]
                if parts:
                    # Prefer the first all-alpha-ish token (e.g., TMP, UGRD, REFC).
                    cand = parts[0].strip()
                    if cand:
                        tokens.append(cand)
                    if len(parts) > 1:
                        cand2 = parts[1].strip()
                        if cand2:
                            tokens.append(cand2)
        return tokens

    # Hard fallbacks for common/derived vars when inventory only exposes GRIB shortNames.
    # (These are intentionally conservative and limited.)
    FALLBACK_TOKEN_MAP: dict[str, list[str]] = {
        "tmp2m": ["TMP"],
        "t2m": ["TMP"],
        "10u": ["UGRD"],
        "10v": ["VGRD"],
        "wspd10m": ["UGRD", "VGRD"],
        "refc": ["REFC"],
        "refd": ["REFD"],
        "crain": ["CRAIN"],
        "csnow": ["CSNOW"],
        "cicep": ["CICEP"],
        "cfrzr": ["CFRZR"],
        "gust10m": ["GUST"],
    }

    def _candidate_tokens(var: str) -> list[str]:
        tokens: list[str] = []
        # 1) Static token map.
        tokens.extend(FALLBACK_TOKEN_MAP.get(var, []))
        # 2) Search-derived tokens.
        tokens.extend(_tokens_from_search(var))
        # 3) Raw forms (helps if required vars are already GRIB-like).
        tokens.append(var)
        tokens.append(var.upper())
        # Dedup preserving order.
        out: list[str] = []
        seen: set[str] = set()
        for t in tokens:
            tt = str(t).strip()
            if not tt:
                continue
            key = tt.upper()
            if key in seen:
                continue
            seen.add(key)
            out.append(tt)
        return out

    matched: list[str] = []
    for var in required_norm:
        tokens = _candidate_tokens(var)

        # Direct matches against normalized inventory (best when inventory gives cfgrib varnames).
        if var in available_norm:
            matched.append(var)
            continue

        # Match any token to inventory shortNames or searchStrings.
        ok = False
        for token in tokens:
            t_up = token.upper()
            # Exact shortName match.
            if t_up in available_upper:
                ok = True
                break
            # Substring match for searchString-ish inventories.
            if any(t_up in item for item in available_upper):
                ok = True
                break
        if ok:
            matched.append(var)

    return len(matched) == len(required_norm), matched, available_list


def _parse_run_datetime(run: str) -> datetime | None:
    if run.lower() == "latest":
        return None
    for fmt in ("%Y%m%d%H", "%Y%m%d_%H", "%Y%m%d_%Hz", "%Y%m%dT%H"):
        try:
            return datetime.strptime(run, fmt)
        except ValueError:
            continue
    if len(run) == 8 and run.isdigit():
        return datetime.strptime(run + "00", "%Y%m%d%H")
    raise ValueError("Run format must be 'latest' or YYYYMMDD or YYYYMMDDhh or YYYYMMDD_hh[z]")


def _cache_dir_for_run(base_dir: Path, run_dt: datetime) -> Path:
    return base_dir / run_dt.strftime("%Y%m%d") / run_dt.strftime("%H")


def _is_idx_missing_message(message: str) -> bool:
    text = message.lower()
    patterns = [
        "no index file was found",
        "index_as_dataframe",
        "inventory not found",
        "no inventory",
        "download the full file first",
        "index not ready",
        "idx missing",
    ]
    return any(pattern in text for pattern in patterns)


def _log_idx_missing(run_id: str, fh: int) -> None:
    now_ts = time.time()
    key = (run_id, fh)
    last_ts = _IDX_FALLBACK_LOG_CACHE.get(key, 0.0)
    if now_ts - last_ts < IDX_FALLBACK_RATE_SECONDS:
        return
    _IDX_FALLBACK_LOG_CACHE[key] = now_ts
    logger.info("IDX missing; deferring subset: run=%s fh=%02d", run_id, fh)


def _parse_priority(value: str | None) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_blocked_hosts(value: str | None) -> set[str]:
    raw = (value or "").strip()
    if not raw:
        return set()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


class _RequestsGuard:
    def __init__(self, timeout_seconds: int, blocked_hosts: set[str]) -> None:
        self._timeout_seconds = timeout_seconds
        self._blocked_hosts = blocked_hosts
        self._orig_head = requests.head
        self._orig_get = requests.get
        self._orig_session_request = requests.sessions.Session.request

    def _wrap(self, fn):
        def _inner(url, *args, **kwargs):
            host = urlparse(url).hostname or ""
            if host.lower() in self._blocked_hosts:
                raise requests.exceptions.ConnectTimeout(
                    f"Blocked GFS source: {host}"
                )
            kwargs.setdefault("timeout", self._timeout_seconds)
            return fn(url, *args, **kwargs)

        return _inner

    def _wrap_session_request(self, fn):
        def _inner(session, method, url, *args, **kwargs):
            host = urlparse(url).hostname or ""
            if host.lower() in self._blocked_hosts:
                raise requests.exceptions.ConnectTimeout(
                    f"Blocked GFS source: {host}"
                )
            kwargs.setdefault("timeout", self._timeout_seconds)
            return fn(session, method, url, *args, **kwargs)

        return _inner

    def __enter__(self):
        requests.head = self._wrap(self._orig_head)
        requests.get = self._wrap(self._orig_get)
        requests.sessions.Session.request = self._wrap_session_request(self._orig_session_request)
        return self

    def __exit__(self, exc_type, exc, tb):
        requests.head = self._orig_head
        requests.get = self._orig_get
        requests.sessions.Session.request = self._orig_session_request


def _requests_guard(timeout_seconds: int, blocked_hosts: set[str]) -> _RequestsGuard:
    return _RequestsGuard(timeout_seconds, blocked_hosts)


def _select_herbie_search(selectors: object) -> str | None:
    try:
        values = list(getattr(selectors, "search", []))
    except AttributeError:
        return None
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return "|".join(values)


def _resolve_var_selectors(model_id: str, variable: str | None) -> object:
    if not variable:
        from app.models.base import VarSelectors

        return VarSelectors()

    from app.models.base import VarSelectors
    from app.models.registry import MODEL_REGISTRY
    from app.services.variable_registry import herbie_search_for, normalize_api_variable

    model = MODEL_REGISTRY.get(model_id)
    if model is not None:
        var_spec = model.get_var(normalize_api_variable(variable))
        if var_spec is not None:
            return var_spec.selectors

    fallback_search = herbie_search_for(variable, model=model_id)
    if fallback_search:
        return VarSelectors(search=[fallback_search])
    return VarSelectors()


def fetch_gfs_grib(
    *,
    run: str,
    fh: int,
    product: str = "pgrb2.0p25",
    model: str = "gfs",
    variable: str | None = None,
    search_override: str | None = None,
    cache_key: str | None = None,
    required_vars: list[str] | None = None,
    cache_dir: Path | None = None,
    **kwargs: object,
) -> GribFetchResult:
    """Example: fetch_grib(model="gfs", region="conus", run="latest", fh=0, var="tmp2m")."""
    base_dir = cache_dir or default_gfs_cache_dir()
    timeout_seconds = kwargs.get("timeout", TWF_GFS_HTTP_TIMEOUT_SECONDS)
    try:
        timeout_seconds = int(timeout_seconds) if timeout_seconds is not None else TWF_GFS_HTTP_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        timeout_seconds = TWF_GFS_HTTP_TIMEOUT_SECONDS
    priority_value = kwargs.get("priority", TWF_GFS_PRIORITY)
    priority = _parse_priority(str(priority_value) if priority_value is not None else None)
    priority_arg = priority if priority else None
    lookback_hours = kwargs.get("lookback_hours", TWF_GFS_PROBE_LOOKBACK_HOURS)
    try:
        lookback_hours = int(lookback_hours)
    except (TypeError, ValueError):
        lookback_hours = TWF_GFS_PROBE_LOOKBACK_HOURS
    max_probe_seconds = kwargs.get("max_probe_seconds", TWF_GFS_MAX_PROBE_SECONDS)
    try:
        max_probe_seconds = int(max_probe_seconds)
    except (TypeError, ValueError):
        max_probe_seconds = TWF_GFS_MAX_PROBE_SECONDS
    skip_sources_value = kwargs.get("skip_sources", TWF_GFS_SKIP_SOURCES)
    blocked_hosts = _parse_blocked_hosts(
        str(skip_sources_value) if skip_sources_value is not None else None
    )
    run_dt = _parse_run_datetime(run)

    plugin = get_model(model)
    normalized_var = plugin.normalize_var_id(variable) if variable else None

    search = search_override
    if not search:
        selectors = _resolve_var_selectors(model, variable)
        search = _select_herbie_search(selectors)
    if not search:
        raise UpstreamNotReady("Subset search required for GFS fetch")

    logger.info(
        "Fetching GFS GRIB: run=%s fh=%02d model=%s product=%s variable=%s search=%s priority=%s timeout=%ss",
        run,
        fh,
        model,
        product,
        variable or "subset",
        search,
        ",".join(priority) if priority else "default",
        timeout_seconds,
    )

    if run_dt is None:
        now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        herbie = None
        start_ts = time.time()
        with _requests_guard(timeout_seconds, blocked_hosts):
            for i in range(0, max(1, lookback_hours)):
                if time.time() - start_ts > max_probe_seconds:
                    raise UpstreamNotReady("Could not resolve latest GFS cycle (probe timeout)")
                candidate = now - timedelta(hours=i)
                try:
                    H = Herbie(candidate, model=model, product=product, fxx=fh, priority=priority_arg)
                except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout) as exc:
                    raise UpstreamNotReady(
                        f"Upstream timeout while probing GFS source: {exc}"
                    ) from exc
                if H.grib:
                    herbie = H
                    run_dt = H.date
                    break
        if herbie is None or run_dt is None:
            raise UpstreamNotReady(
                f"Could not resolve latest GFS cycle in the last {lookback_hours} hours"
            )
    else:
        with _requests_guard(timeout_seconds, blocked_hosts):
            try:
                herbie = Herbie(run_dt, model=model, product=product, fxx=fh, priority=priority_arg)
            except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout) as exc:
                raise UpstreamNotReady(
                    f"Upstream timeout while probing GFS source: {exc}"
                ) from exc

    target_dir = _cache_dir_for_run(base_dir, run_dt)
    target_dir.mkdir(parents=True, exist_ok=True)

    suffix_parts: list[str] = []
    if cache_key:
        suffix_parts.append(str(cache_key))
    # Always include the requested variable if it differs, to prevent collisions.
    if variable and (not cache_key or str(variable) != str(cache_key)):
        suffix_parts.append(str(variable))
    if not suffix_parts:
        suffix_parts = [variable or "subset"]

    expected_suffix = "__".join(suffix_parts)
    expected_filename = f"{model}.t{run_dt:%H}z.{product}f{fh:02d}.{expected_suffix}.grib2"
    expected_path = target_dir / expected_filename
    original_required_vars = list(required_vars or [])
    required_expanded = False
    if required_vars is not None:
        required_lc = [str(item).strip().lower() for item in required_vars if str(item).strip()]
        if any(item in {"radar_ptype", "radar_ptype_combo"} for item in required_lc):
            if normalized_var:
                validate_vars, _ = _required_grib_vars_for_request(model, normalized_var)
            else:
                validate_vars = ["refc", "crain", "csnow", "cicep", "cfrzr"]
            validate_source = "explicit_expanded"
            required_expanded = True
        else:
            validate_vars = required_lc
            validate_source = "explicit"
    elif normalized_var:
        validate_vars, validate_source = _required_grib_vars_for_request(model, normalized_var)
    else:
        validate_vars = []
        validate_source = "none"
    if validate_vars is not None and not validate_vars:
        validate_vars = None
    logger.info(
        "GFS required vars: normalized_var=%s original_required_vars=%s expanded_required_vars=%s source=%s",
        normalized_var,
        original_required_vars,
        validate_vars or [],
        validate_source,
    )
    available_vars = _inventory_strings(herbie)

    if expected_path.exists():
        if _is_readable_grib(expected_path):
            if available_vars:
                logger.info("Cached GFS subset validation using inventory vars")
                ok, matched, available = _subset_contains_required_variables(
                    model,
                    validate_vars,
                    available_vars,
                )
            else:
                available_local = _local_grib_varnames(expected_path)
                logger.info("Cached GFS subset validation using local GRIB vars")
                ok, matched, available = _subset_contains_required_variables(
                    model,
                    validate_vars,
                    available_local,
                )
            if not ok:
                logger.warning(
                    "Cached GFS subset missing required variables; purging: path=%s variable=%s required=%s matched=%s available=%s",
                    expected_path,
                    variable or "subset",
                    validate_vars or [],
                    matched,
                    available,
                )
                try:
                    expected_path.unlink()
                except OSError:
                    pass
            else:
                logger.info("Using cached GFS GRIB: %s", expected_path)
                return GribFetchResult(path=expected_path, is_full_file=False)
        else:
            raise RuntimeError(
                "Immutable cache conflict: target GFS GRIB exists but is unreadable; "
                f"refusing overwrite at {expected_path}"
            )
    try:
        with _requests_guard(timeout_seconds, blocked_hosts):
            downloaded = herbie.download(search, save_dir=target_dir)
    except Exception as exc:
        message = str(exc)
        if _is_idx_missing_message(message):
            _log_idx_missing(run_dt.strftime("%Y%m%d_%Hz"), fh)
            raise UpstreamNotReady("Index not ready for requested GFS GRIB") from exc
        if isinstance(exc, (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout)):
            raise UpstreamNotReady(
                f"Upstream timeout while probing GFS source: {exc}"
            ) from exc
        raise RuntimeError(f"Herbie download failed: {exc}") from exc
    if isinstance(downloaded, (list, tuple)):
        downloaded = downloaded[0] if downloaded else None

    if downloaded is None:
        raise UpstreamNotReady("Herbie did not return a GRIB2 path")

    path = Path(downloaded)
    if not path.exists():
        if expected_path.exists() and _is_readable_grib(expected_path):
            path = expected_path
        else:
            raise UpstreamNotReady(
                f"Downloaded GRIB2 not found for requested variable={variable or 'subset'} "
                f"run={run_dt.strftime('%Y%m%d_%Hz')} fh={fh:02d}; reported_path={path}"
            )

    if path.stat().st_size == 0:
        raise UpstreamNotReady(f"Downloaded GRIB2 is empty: {path}")

    if path.resolve() != expected_path.resolve():
        if expected_path.exists():
            raise RuntimeError(
                "Immutable cache conflict: expected deterministic path already exists; "
                f"refusing overwrite at {expected_path}"
            )
        logger.info("Moving GRIB into cache layout: %s -> %s", path, expected_path)
        try:
            path.replace(expected_path)
        except OSError:
            shutil.move(str(path), str(expected_path))

    ok, matched, available = _subset_contains_required_variables(
        model,
        validate_vars,
        available_vars,
    )
    available_inventory = available
    available_local = []
    if (not available_inventory) or not ok:
        available_local = _local_grib_varnames(expected_path)
        ok, matched, _ = _subset_contains_required_variables(
            model,
            validate_vars,
            available_local,
        )
    if not ok:
        logger.warning(
            "Downloaded GFS subset missing required variables; deleting and deferring: path=%s variable=%s required=%s matched=%s available_inventory=%s available_local=%s",
            expected_path,
            variable or "subset",
            validate_vars or [],
            matched,
            available_inventory,
            available_local,
        )
        try:
            expected_path.unlink()
        except OSError:
            pass
        raise UpstreamNotReady(
            "Requested variables not available yet: "
            f"var={variable or 'subset'} required={validate_vars or []} "
            f"run={run_dt.strftime('%Y%m%d_%Hz')} fh={fh:02d}"
        )

    return GribFetchResult(path=expected_path, is_full_file=False)


def is_upstream_not_ready(exc: BaseException) -> bool:
    return isinstance(exc, UpstreamNotReady)

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# Add backend_v2 to path so app module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

from herbie import Herbie

from app.models import get_model
from app.services.variable_registry import herbie_search_for


TYPE_OF_LEVEL_HINTS: dict[str, str] = {
    "heightAboveGround": "above ground",
    "surface": "surface",
    "isobaricInhPa": " mb",
}


@dataclass(frozen=True)
class ValidationResult:
    requested_var: str
    checked_var: str
    search_patterns: tuple[str, ...]
    matches: int
    ok: bool
    reason: str


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


def _parse_vars(value: str) -> list[str]:
    items = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError("--vars cannot be empty")
    return items


def _selector_patterns_for_var(model_id: str, var_id: str, var_spec) -> list[str]:
    patterns: list[str] = []
    if var_spec is not None:
        patterns = [item.strip() for item in var_spec.selectors.search if str(item).strip()]
    if patterns:
        return patterns
    fallback = herbie_search_for(var_id, model=model_id)
    if not fallback:
        return []
    return [item.strip() for item in fallback.split("|") if item.strip()]


def _filter_inventory_df(df, filter_by_keys: dict[str, str]):
    result = df
    if not filter_by_keys:
        return result
    if "level" in df.columns:
        level = filter_by_keys.get("level")
        if level is not None:
            level_text = str(level).strip()
            result = result[result["level"].astype(str).str.contains(level_text, regex=False)]
    if "level" in df.columns:
        tol = filter_by_keys.get("typeOfLevel")
        if tol:
            hint = TYPE_OF_LEVEL_HINTS.get(str(tol))
            if hint:
                result = result[result["level"].astype(str).str.contains(hint, case=False, regex=False)]
    return result


def _validate_non_derived_var(model_id: str, requested_var: str, checked_var: str, var_spec, H: Herbie) -> ValidationResult:
    patterns = _selector_patterns_for_var(model_id, checked_var, var_spec)
    if not patterns:
        return ValidationResult(
            requested_var=requested_var,
            checked_var=checked_var,
            search_patterns=tuple(),
            matches=0,
            ok=False,
            reason="No selector search patterns configured",
        )

    total_matches = 0
    filter_by_keys = var_spec.selectors.filter_by_keys if var_spec is not None else {}
    for pattern in patterns:
        df = H.inventory(pattern)
        df = _filter_inventory_df(df, filter_by_keys)
        total_matches += int(len(df.index))
    return ValidationResult(
        requested_var=requested_var,
        checked_var=checked_var,
        search_patterns=tuple(patterns),
        matches=total_matches,
        ok=total_matches > 0,
        reason="ok" if total_matches > 0 else "No IDX records matched selector patterns",
    )


def _component_vars_for_derived(var_spec) -> tuple[str, ...]:
    hints = var_spec.selectors.hints
    values = tuple(
        item
        for item in (
            hints.get("prate_component"),
            hints.get("u_component"),
            hints.get("v_component"),
            hints.get("refl_component"),
            hints.get("ptype_component"),
            hints.get("rain_component"),
            hints.get("snow_component"),
            hints.get("sleet_component"),
            hints.get("frzr_component"),
        )
        if item
    )
    return values


def _resolve_requested_vars(plugin, vars_arg: str | None) -> list[str]:
    if vars_arg:
        raw = _parse_vars(vars_arg)
        return [plugin.normalize_var_id(item) for item in raw]
    return sorted(plugin.vars.keys())


def _resolve_herbie_object(
    *,
    run: str,
    model_id: str,
    product: str,
    fh: int,
    source: str,
    lookback_hours: int,
) -> Herbie:
    priority = [source] if source else None
    run_dt = _parse_run_datetime(run)
    if run_dt is not None:
        H = Herbie(run_dt, model=model_id, product=product, fxx=fh, priority=priority)
        if H.idx is None:
            raise RuntimeError(f"No IDX found for run={run} model={model_id} product={product} fh={fh}")
        return H

    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    for i in range(max(1, lookback_hours)):
        candidate = now - timedelta(hours=i)
        H = Herbie(candidate, model=model_id, product=product, fxx=fh, priority=priority)
        if H.idx is not None:
            return H
    raise RuntimeError(
        f"Could not find latest IDX in lookback window: model={model_id} product={product} fh={fh} hours={lookback_hours}"
    )


def _validate_var(plugin, H: Herbie, model_id: str, requested_var: str) -> list[ValidationResult]:
    var_spec = plugin.get_var(requested_var)
    if var_spec is None:
        return [
            ValidationResult(
                requested_var=requested_var,
                checked_var=requested_var,
                search_patterns=tuple(),
                matches=0,
                ok=False,
                reason="Unknown variable in plugin",
            )
        ]

    if not var_spec.derived:
        return [_validate_non_derived_var(model_id, requested_var, requested_var, var_spec, H)]

    components = _component_vars_for_derived(var_spec)
    if not components:
        return [
            ValidationResult(
                requested_var=requested_var,
                checked_var=requested_var,
                search_patterns=tuple(),
                matches=0,
                ok=False,
                reason="Derived variable has no component hints",
            )
        ]

    results: list[ValidationResult] = []
    for component in components:
        component_spec = plugin.get_var(component)
        results.append(_validate_non_derived_var(model_id, requested_var, component, component_spec, H))
    return results


def _print_results(results: list[ValidationResult]) -> int:
    failures = 0
    for row in results:
        status = "PASS" if row.ok else "FAIL"
        if not row.ok:
            failures += 1
        patterns = "|".join(row.search_patterns) if row.search_patterns else "(none)"
        print(
            f"[{status}] requested={row.requested_var} checked={row.checked_var} "
            f"matches={row.matches} search={patterns} reason={row.reason}"
        )
    print(f"\nSummary: total={len(results)} failed={failures}")
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate model variable selectors against Herbie IDX inventory.")
    parser.add_argument("--model", required=True, help="Model id, e.g. hrrr or gfs")
    parser.add_argument("--run", default="latest", help="Run id: latest, YYYYMMDD, YYYYMMDDhh, YYYYMMDD_HH[z]")
    parser.add_argument("--fh", type=int, default=0)
    parser.add_argument("--source", default="nomads", help="Herbie source priority, default=nomads")
    parser.add_argument("--vars", default=None, help="Comma-separated API vars; default=all vars in plugin")
    parser.add_argument("--lookback-hours", type=int, default=12)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plugin = get_model(args.model)
    requested_vars = _resolve_requested_vars(plugin, args.vars)
    H = _resolve_herbie_object(
        run=args.run,
        model_id=plugin.id,
        product=plugin.product,
        fh=args.fh,
        source=args.source,
        lookback_hours=args.lookback_hours,
    )
    print(
        f"Validating model={plugin.id} product={plugin.product} run={H.date:%Y%m%d_%Hz} "
        f"fh={args.fh} idx_source={H.idx_source}"
    )

    rows: list[ValidationResult] = []
    for var in requested_vars:
        rows.extend(_validate_var(plugin, H, plugin.id, var))
    failures = _print_results(rows)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

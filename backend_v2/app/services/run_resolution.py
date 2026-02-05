from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

logger = logging.getLogger(__name__)

DATA_ROOT_ENV = "TWF_DATA_V2_ROOT"
DEFAULT_ROOT = "/opt/twf_models/data/v2"
RUN_RE = re.compile(r"^\d{8}_\d{2}z$")


def get_data_root() -> Path:
    return Path(os.environ.get(DATA_ROOT_ENV, DEFAULT_ROOT))


def _list_run_dirs(model: str, region: str) -> list[Path]:
    root = get_data_root() / model / region
    if not root.exists() or not root.is_dir():
        return []
    return [p for p in root.iterdir() if p.is_dir()]


def _latest_pointer_path(model: str, region: str) -> Path:
    return get_data_root() / model / region / "LATEST.json"


def _read_latest_pointer(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("LATEST.json read failed: %s", exc)
        return None
    run_id = payload.get("run_id")
    if isinstance(run_id, str):
        if RUN_RE.match(run_id):
            return run_id
        logger.warning("LATEST.json run_id has invalid format: %s", run_id)
    return None


def _run_dir_has_outputs(run_dir: Path) -> bool:
    if not run_dir.exists() or not run_dir.is_dir():
        return False
    try:
        return any(path.is_file() for path in run_dir.rglob("fh*.cog.tif"))
    except OSError:
        return False


def list_runs(model: str, region: str) -> list[str]:
    run_dirs = _list_run_dirs(model, region)
    if not run_dirs:
        return []
    matched: list[tuple[datetime, str]] = []
    for path in run_dirs:
        if not RUN_RE.match(path.name):
            continue
        try:
            run_dt = datetime.strptime(path.name, "%Y%m%d_%Hz")
        except ValueError:
            continue
        matched.append((run_dt, path.name))

    if not matched:
        return []

    matched.sort(key=lambda item: item[0], reverse=True)
    return [name for _, name in matched]


def resolve_run(model: str, region: str, run: str) -> str:
    if run != "latest":
        return run

    pointer_path = _latest_pointer_path(model, region)
    pointer_run = _read_latest_pointer(pointer_path)
    if pointer_run:
        run_dir = get_data_root() / model / region / pointer_run
        if _run_dir_has_outputs(run_dir):
            logger.info(
                "Resolved latest run from LATEST.json: model=%s region=%s run=%s",
                model,
                region,
                pointer_run,
            )
            return pointer_run
        logger.warning(
            "Ignoring LATEST.json pointer (missing/empty run dir): model=%s region=%s run=%s",
            model,
            region,
            pointer_run,
        )
    else:
        logger.info("LATEST.json missing or invalid; falling back to scan: model=%s region=%s", model, region)

    runs = list_runs(model, region)
    if not runs:
        raise HTTPException(status_code=404, detail="No runs found for model/region")

    resolved = runs[0]
    logger.info("Resolved latest run from scan: model=%s region=%s run=%s", model, region, resolved)
    return resolved
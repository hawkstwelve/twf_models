from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fastapi import HTTPException

logger = logging.getLogger(__name__)

DATA_ROOT_ENV = "DATA_V2_ROOT"
DEFAULT_ROOT = "/opt/twf_models/data/v2"
RUN_RE = re.compile(r"^\d{8}_\d{2}z$")


def get_data_root() -> Path:
    return Path(os.environ.get(DATA_ROOT_ENV, DEFAULT_ROOT)).resolve()


def _list_run_dirs(model: str, region: str) -> list[Path]:
    root = get_data_root() / model / region
    if not root.exists() or not root.is_dir():
        return []
    return [p for p in root.iterdir() if p.is_dir()]


def list_runs(model: str, region: str) -> list[str]:
    run_dirs = _list_run_dirs(model, region)
    if not run_dirs:
        return []

    names = [p.name for p in run_dirs]
    if all(RUN_RE.match(name) for name in names):
        return sorted(names, reverse=True)

    run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in run_dirs]


def resolve_run(model: str, region: str, run: str) -> str:
    if run != "latest":
        return run

    runs = list_runs(model, region)
    if not runs:
        raise HTTPException(status_code=404, detail="No runs found for model/region")

    resolved = runs[0]
    logger.info("Resolved latest run: model=%s region=%s run=%s", model, region, resolved)
    return resolved
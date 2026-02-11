from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from app.services.offline_tiles import build_and_publish_run_var, discover_source_fhs

logger = logging.getLogger(__name__)


def _parse_fhs(value: str | None) -> list[int] | None:
    if value is None or not value.strip():
        return None
    fhs: list[int] = []
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        fhs.append(int(token))
    return sorted(set(fhs))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and publish offline PMTiles for a model/run/var.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--run", required=True, help="Run id in YYYYMMDD_HHz format")
    parser.add_argument("--var", required=True)
    parser.add_argument("--fhs", default=None, help="Optional comma-separated forecast hours")
    parser.add_argument("--list-fhs", action="store_true")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()

    requested_fhs = _parse_fhs(args.fhs)
    if args.list_fhs:
        discovered = discover_source_fhs(args.model, args.region, args.run, args.var)
        print(json.dumps({"model": args.model, "run": args.run, "var": args.var, "fhs": discovered}, indent=2))
        return 0

    try:
        result = build_and_publish_run_var(
            model=args.model,
            region=args.region,
            run=args.run,
            var=args.var,
            fhs=requested_fhs,
        )
    except Exception as exc:
        logger.exception("Offline tiles pipeline failed")
        print(str(exc))
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

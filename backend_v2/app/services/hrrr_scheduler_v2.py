from __future__ import annotations

import argparse
import logging

from app.services import model_scheduler_v2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the HRRR V2 near-real-time scheduler.")
    parser.add_argument("--region", type=str, default="pnw")
    parser.add_argument("--vars", type=str, default=model_scheduler_v2.VAR_DEFAULTS)
    parser.add_argument("--primary-vars", type=str, default=model_scheduler_v2.PRIMARY_VAR_DEFAULT)
    parser.add_argument("--model", type=str, default="hrrr")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    if args.self_test:
        return model_scheduler_v2.run_self_test()
    try:
        return model_scheduler_v2.run_scheduler(
            model=args.model,
            region=args.region,
            vars=model_scheduler_v2.parse_vars(args.vars),
            primary_vars=model_scheduler_v2.parse_vars(args.primary_vars),
        )
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Scheduler shutdown requested")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

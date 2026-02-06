from __future__ import annotations

import logging
import sys

from app.services import model_scheduler_v2


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    argv = sys.argv[1:]
    if "--model" not in argv:
        argv = ["--model", "hrrr", *argv]
    print(
        "hrrr_scheduler_v2.py is deprecated; forwarding to model_scheduler_v2.",
        file=sys.stderr,
    )
    return model_scheduler_v2.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

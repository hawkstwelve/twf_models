from __future__ import annotations

DEFAULT_HERBIE_PRIORITY = "aws,nomads,google,azure,pando,pando2"


def parse_herbie_priority(raw: str | None) -> list[str]:
    value = (raw or "").strip()
    if not value:
        value = DEFAULT_HERBIE_PRIORITY
    return [
        part.strip().lower()
        for part in value.split(",")
        if part.strip()
    ]

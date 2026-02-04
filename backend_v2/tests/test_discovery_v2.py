from __future__ import annotations

from app.services.discovery_v2 import is_valid_run_id, parse_fh_filename


def test_is_valid_run_id() -> None:
    assert is_valid_run_id("20260204_20z")
    assert is_valid_run_id("19991231_00z")
    assert not is_valid_run_id("20260204_2z")
    assert not is_valid_run_id("2026-02-04_20z")
    assert not is_valid_run_id("latest")


def test_parse_fh_filename() -> None:
    assert parse_fh_filename("fh000.cog.tif") == 0
    assert parse_fh_filename("fh006.cog.tif") == 6
    assert parse_fh_filename("fh120.cog.tif") == 120
    assert parse_fh_filename("fh6.cog.tif") is None
    assert parse_fh_filename("fh006.tif") is None
    assert parse_fh_filename("fh006.cog.tif.ovr") is None

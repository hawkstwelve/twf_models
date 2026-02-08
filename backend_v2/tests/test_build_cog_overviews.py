from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_cog


def test_is_copy_src_overviews_unsupported() -> None:
    exc = RuntimeError(
        "Command failed (...): Warning 6: driver COG does not support creation option COPY_SRC_OVERVIEWS"
    )
    assert build_cog._is_copy_src_overviews_unsupported(exc)

    exc = RuntimeError(
        "Command failed (...): ERROR 6: fh000.cog.tif: COPY_SRC_OVERVIEWS cannot be used when the bands have not the same number of overview levels."
    )
    assert build_cog._is_copy_src_overviews_unsupported(exc)

    exc = RuntimeError("Command failed (...): some unrelated gdal error")
    assert not build_cog._is_copy_src_overviews_unsupported(exc)


def test_run_gdaladdo_overviews_no_mask_support_keeps_band_overviews(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_cmd(args: list[str]) -> None:
        calls.append(list(args))

    monkeypatch.setattr(build_cog, "require_gdal", lambda _cmd: None)
    monkeypatch.setattr(build_cog, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(build_cog, "_gdaladdo_supports_mask", lambda: False)

    build_cog.run_gdaladdo_overviews(Path("/tmp/sample.tif"), "average", "nearest")

    assert len(calls) == 3
    assert calls[0][-2:] == ["-clean", "/tmp/sample.tif"]
    assert calls[1][-7:] == ["/tmp/sample.tif", "2", "4", "8", "16", "32", "64"]
    assert calls[2][-7:] == ["/tmp/sample.tif", "2", "4", "8", "16", "32", "64"]
    assert calls[1][calls[1].index("-r") + 1] == "average"
    assert calls[2][calls[2].index("-r") + 1] == "nearest"
    assert calls[1][calls[1].index("-b") + 1] == "1"
    assert calls[2][calls[2].index("-b") + 1] == "2"


def test_run_gdaladdo_overviews_external_conflict_falls_back_to_all_bands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run_cmd(args: list[str]) -> None:
        calls.append(list(args))
        if "-b" in args and args[args.index("-b") + 1] == "2":
            raise RuntimeError(
                "Command failed (...): ERROR 6: sample.tif: Cannot add external overviews when there are already internal overviews"
            )

    monkeypatch.setattr(build_cog, "require_gdal", lambda _cmd: None)
    monkeypatch.setattr(build_cog, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(build_cog, "_gdaladdo_supports_mask", lambda: False)

    build_cog.run_gdaladdo_overviews(Path("/tmp/sample.tif"), "average", "nearest")

    assert len(calls) == 5
    assert calls[0][-2:] == ["-clean", "/tmp/sample.tif"]
    assert "-b" in calls[1]
    assert "-b" in calls[2]
    assert calls[3][-2:] == ["-clean", "/tmp/sample.tif"]
    assert "-b" not in calls[4]
    assert calls[4][-7:] == ["/tmp/sample.tif", "2", "4", "8", "16", "32", "64"]


def test_assert_single_internal_overview_cog_relaxes_missing_mask_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = {
        "files": ["/tmp/sample.tif"],
        "bands": [
            {"overviews": [{}], "mask": {}},
            {"overviews": [{}], "mask": {}},
        ],
    }
    monkeypatch.setattr(build_cog, "gdalinfo_json", lambda _path: info)
    monkeypatch.setattr(build_cog, "_gdaladdo_supports_mask", lambda: False)

    build_cog.assert_single_internal_overview_cog(Path("/tmp/sample.tif"))


def test_assert_single_internal_overview_cog_requires_mask_when_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = {
        "files": ["/tmp/sample.tif"],
        "bands": [
            {"overviews": [{}], "mask": {}},
            {"overviews": [{}], "mask": {}},
        ],
    }
    monkeypatch.setattr(build_cog, "gdalinfo_json", lambda _path: info)
    monkeypatch.setattr(build_cog, "_gdaladdo_supports_mask", lambda: True)

    with pytest.raises(RuntimeError, match="missing internal mask overviews"):
        build_cog.assert_single_internal_overview_cog(Path("/tmp/sample.tif"))


def test_assert_single_internal_overview_cog_relaxes_alpha_only_missing_band_overviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = {
        "files": ["/tmp/sample.tif"],
        "bands": [
            {"overviews": [{}], "mask": {}, "colorInterpretation": "Gray"},
            {"overviews": [], "mask": {}, "colorInterpretation": "Alpha"},
        ],
    }
    monkeypatch.setattr(build_cog, "gdalinfo_json", lambda _path: info)
    monkeypatch.setattr(build_cog, "_gdaladdo_supports_mask", lambda: False)

    build_cog.assert_single_internal_overview_cog(Path("/tmp/sample.tif"))

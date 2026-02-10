from __future__ import annotations

import numpy as np

from app.services.colormaps_v2 import VAR_SPECS, encode_to_byte_and_alpha, get_lut


def test_wspd10m_legend_stops_present() -> None:
    """Verify wspd10m has legend_stops for stepped legend display."""
    spec = VAR_SPECS["wspd10m"]
    legend_stops = spec.get("legend_stops")
    assert legend_stops is not None
    assert len(legend_stops) == 27
    assert legend_stops[0] == (0, "#FFFFFF")
    assert legend_stops[-1] == (100, "#680868")
    # Ensure no "stops" field exists (stops are now legend_stops)
    assert "stops" not in spec


def test_wspd10m_lut_continuous() -> None:
    """Verify wspd10m LUT is continuous 256-step (not discrete)."""
    lut = get_lut("wspd10m")
    assert isinstance(lut, np.ndarray)
    assert lut.shape == (256, 4)
    # Verify it's continuous by checking colors change gradually
    assert not np.array_equal(lut[0], lut[127])
    assert not np.array_equal(lut[127], lut[255])


def test_wspd10m_is_continuous_type() -> None:
    """Verify wspd10m spec is type=continuous with range."""
    spec = VAR_SPECS["wspd10m"]
    assert spec["type"] == "continuous"
    assert "range" in spec
    assert spec["range"] == (0.0, 100.0)
    assert "colors" in spec


def test_display_metadata_present() -> None:
    """Verify display_name and legend_title are present for key vars."""
    for var_key in ["tmp2m", "wspd10m", "refc"]:
        spec = VAR_SPECS[var_key]
        assert "display_name" in spec, f"{var_key} missing display_name"
        assert "legend_title" in spec, f"{var_key} missing legend_title"
        assert isinstance(spec["display_name"], str)
        assert isinstance(spec["legend_title"], str)


def test_encode_includes_display_metadata() -> None:
    """Verify encode_to_byte_and_alpha includes display metadata in output."""
    values = np.array([[10.0, 20.0], [30.0, 40.0]])
    byte_band, alpha, meta = encode_to_byte_and_alpha(values, "wspd10m")
    
    assert "display_name" in meta
    assert "legend_title" in meta
    assert meta["display_name"] == "10m Wind Speed"
    assert meta["legend_title"] == "Wind Speed (mph)"
    
    # Verify legend_stops are present for wspd10m
    assert "legend_stops" in meta
    assert len(meta["legend_stops"]) == 27
    
    # Verify no "stops" field (only legend_stops)
    assert "stops" not in meta


def test_encode_tmp2m_metadata() -> None:
    """Verify tmp2m encoding includes display metadata."""
    values = np.array([[50.0, 60.0], [70.0, 80.0]])
    byte_band, alpha, meta = encode_to_byte_and_alpha(values, "tmp2m")
    
    assert "display_name" in meta
    assert "legend_title" in meta
    assert meta["display_name"] == "2m Temperature"
    assert meta["legend_title"] == "Temperature (\u00b0F)"
    
    # tmp2m should not have legend_stops (continuous smooth legend)
    assert "legend_stops" not in meta


def test_encode_refc_metadata() -> None:
    """Verify refc encoding includes reflectivity display metadata."""
    values = np.array([[10.0, 20.0], [30.0, 40.0]])
    _, _, meta = encode_to_byte_and_alpha(values, "refc")

    assert meta["display_name"] == "Composite Reflectivity"
    assert meta["legend_title"] == "Reflectivity (dBZ)"


def test_encode_refc_masks_sub_10dbz() -> None:
    """Verify refc <10 dBZ values are transparent (no precip/noise)."""
    values = np.array([[0.0, 5.0], [10.0, 20.0]], dtype=np.float32)
    byte_band, alpha, _ = encode_to_byte_and_alpha(values, "refc")

    assert int(alpha[0, 0]) == 0
    assert int(alpha[0, 1]) == 0
    assert int(alpha[1, 0]) == 255
    assert int(alpha[1, 1]) == 255
    # 10 dBZ should map to first visible color bin, not white/no-data.
    assert int(byte_band[1, 0]) == 0


def test_qpf6h_spec_continuous_with_fixed_range_and_legend_stops() -> None:
    spec = VAR_SPECS["qpf6h"]
    assert spec["type"] == "continuous"
    assert spec["units"] == "in"
    assert spec["range"] == (0.0, 6.0)
    assert spec["colors"] == VAR_SPECS["precip_total"]["colors"]
    legend_stops = spec.get("legend_stops")
    assert legend_stops is not None
    assert len(legend_stops) == len(spec["colors"])
    assert legend_stops[0][0] == 0.01
    assert legend_stops[-1][0] == 25.0


def test_encode_qpf6h_includes_range_and_legend_stops() -> None:
    values = np.array([[0.0, 1.0], [3.0, 6.0]], dtype=np.float32)
    byte_band, alpha, meta = encode_to_byte_and_alpha(values, "qpf6h")

    assert byte_band.shape == values.shape
    assert alpha.shape == values.shape
    assert meta["kind"] == "continuous"
    assert meta["units"] == "in"
    assert meta["range"] == [0.0, 6.0]
    assert "legend_stops" in meta


def test_precip_ptype_spec_discrete_with_ptype_breaks() -> None:
    spec = VAR_SPECS["precip_ptype"]
    assert spec["type"] == "discrete"
    assert spec["units"] == "in/hr"
    assert isinstance(spec["levels"], list)
    assert len(spec["levels"]) == 256
    assert isinstance(spec["colors"], list)
    assert len(spec["colors"]) == 256
    assert spec["range"] == (0.0, 1.0)
    assert spec["bins_per_ptype"] == 64
    assert spec["display_name"] == "Precipitation Intensity"
    assert spec["legend_title"] == "Precipitation Rate (in/hr)"
    assert spec["ptype_order"] == ["frzr", "sleet", "snow", "rain"]
    assert set(spec["ptype_breaks"].keys()) == {"frzr", "sleet", "snow", "rain"}
    assert spec["ptype_breaks"]["frzr"] == {"offset": 0, "count": 64}
    assert spec["ptype_breaks"]["sleet"] == {"offset": 64, "count": 64}
    assert spec["ptype_breaks"]["snow"] == {"offset": 128, "count": 64}
    assert spec["ptype_breaks"]["rain"] == {"offset": 192, "count": 64}
    assert set(spec["ptype_levels"].keys()) == {"frzr", "sleet", "snow", "rain"}
    assert len(spec["ptype_levels"]["frzr"]) == 64
    assert float(spec["ptype_levels"]["frzr"][0]) == 0.0
    assert float(spec["ptype_levels"]["frzr"][-1]) == 1.0


def test_encode_precip_ptype_is_discrete() -> None:
    values = np.array([[0.0, 0.5], [1.0, 2.0]], dtype=np.float32)
    byte_band, alpha, meta = encode_to_byte_and_alpha(values, "precip_ptype")

    assert byte_band.shape == values.shape
    assert alpha.shape == values.shape
    assert meta["kind"] == "discrete"
    assert meta["units"] == "in/hr"
    assert "levels" in meta
    assert meta["ptype_order"] == ["frzr", "sleet", "snow", "rain"]
    assert meta["ptype_breaks"]["frzr"] == {"offset": 0, "count": 64}
    assert meta["range"] == [0.0, 1.0]
    assert meta["bins_per_ptype"] == 64

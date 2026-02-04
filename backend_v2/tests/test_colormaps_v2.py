from __future__ import annotations

import numpy as np

from app.services.colormaps_v2 import VAR_SPECS, get_lut


def test_wspd10m_stops_present() -> None:
    spec = VAR_SPECS["wspd10m"]
    stops = spec.get("stops")
    assert stops is not None
    assert len(stops) == 29
    assert stops[0] == (0, "#FFFFFF")
    assert stops[-1] == (100, "#680868")


def test_wspd10m_lut_length() -> None:
    lut = get_lut("wspd10m")
    assert isinstance(lut, np.ndarray)
    assert lut.shape == (256, 4)

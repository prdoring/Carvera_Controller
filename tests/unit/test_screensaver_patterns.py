import math
import random

import pytest

from carveracontroller.ui.screensaver_patterns import STYLES, TRACE_STYLES, Rotation, Trace, pattern, preferences


def test_defaults_and_invalid_preferences():
    assert preferences({}) == (30, "random", True)
    assert preferences({"screensaver_timeout_minutes": "broken", "screensaver_style": "missing"}) == (
        30,
        "random",
        True,
    )
    assert preferences(
        {"screensaver_timeout_minutes": "0", "screensaver_style": "clock", "screensaver_show_clock": "0"}
    ) == (0, "clock", False)
    assert preferences({"screensaver_timeout_minutes": "999"})[0] == 30


def test_rotation_visits_every_design_without_boundary_repeats():
    rotation = Rotation(random.Random(7))
    count = len(STYLES)
    values = [rotation.next() for _ in range(20 * count)]
    for start in range(0, len(values), count):
        assert set(values[start : start + count]) == set(STYLES)
    assert all(a != b for a, b in zip(values, values[1:]))


@pytest.mark.parametrize("style", TRACE_STYLES)
def test_patterns_are_repeatable_varied_and_bounded(style):
    assert pattern(style, random.Random(4)) == pattern(style, random.Random(4))
    assert pattern(style, random.Random(4)) != pattern(style, random.Random(5))
    for seed in range(60):
        paths = pattern(style, random.Random(seed))
        assert 0 < len(paths) <= 48
        for path in paths:
            assert 2 <= len(path) <= 100
            assert Trace(path).length > 0
            assert all(
                math.isfinite(x) and math.isfinite(y) and 0.03 <= x <= 0.97 and 0.12 <= y <= 0.84 for x, y in path
            )


def test_trace_interpolates_by_distance_without_connecting_separate_paths():
    trace = Trace([(0, 0), (3, 0), (3, 4)])
    assert trace.length == 7
    assert trace.prefix(0) == []
    assert trace.prefix(2) == [(0, 0), (2, 0)]
    assert trace.prefix(5) == [(0, 0), (3, 0), (3, 2)]
    assert trace.prefix(7) == trace.points

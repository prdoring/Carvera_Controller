import pytest

from carveracontroller.machine.state_values import finite_number


@pytest.mark.parametrize(("value", "expected"), [(0, 0.0), (-12.5, -12.5), ("12.5", 12.5), (" -3 ", -3.0)])
def test_numeric_machine_status(value, expected):
    assert finite_number(value) == expected


@pytest.mark.parametrize("value", [None, True, object(), [], "invalid", "nan", "inf", float("-inf")])
def test_invalid_machine_status_is_rejected(value):
    with pytest.raises(ValueError, match="numeric machine status"):
        finite_number(value)


def test_overflowing_machine_status_is_rejected():
    with pytest.raises(ValueError, match="numeric machine status"):
        finite_number(10**10000)

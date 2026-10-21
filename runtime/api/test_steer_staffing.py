"""Steering report command remains reachable from the worker recipes."""

from runtime.api.test_steer_prompt import _STEER_DIR, _read


def test_steering_report_command():
    loop = _read(_STEER_DIR / "loop.md")
    assert "yoke steering report get" in loop

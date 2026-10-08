"""Steering remains the staffing owner across the split worker recipes."""

from runtime.api.test_steer_prompt import _STEER_DIR, _read


def test_steering_seat_is_the_only_staffing_path():
    loop = _read(_STEER_DIR / "loop.md")
    assert "unclaimed" in loop
    assert "yoke steering report get" in loop
    assert "this seat's to staff; nothing else" in loop
    lifecycle = _read(_STEER_DIR / "worker-lifecycle.md") + _read(
        _STEER_DIR / "worker-launch.md"
    )
    assert "There is no second staffing" in lifecycle

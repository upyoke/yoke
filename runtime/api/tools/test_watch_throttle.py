"""Unit tests for :mod:`yoke_core.tools._watch_throttle`.

Covers the standalone primitives — :class:`ProgressGate`,
:func:`annotate_progress_line`, and :func:`load_throttle_policy` —
without exercising the runner. Runner integration tests live in
``test_watch_throttle_integration.py``.
"""

from __future__ import annotations

import pytest

from yoke_core.tools._watch_throttle import (
    Classification,
    DEFAULT_MIN_INTERVAL_SECONDS,
    DEFAULT_PERCENT_STEP,
    LineClass,
    ProgressGate,
    ThrottlePolicy,
    annotate_progress_line,
    load_throttle_policy,
)


class _FakeClock:
    """Monotonic clock fake whose value the test advances explicitly."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


class TestProgressGate:
    def test_first_progress_line_always_emits(self):
        clock = _FakeClock()
        gate = ProgressGate(
            ThrottlePolicy(percent_step=5.0, min_interval_seconds=10.0),
            time_source=clock,
        )
        decision = gate.consider(
            Classification(LineClass.PROGRESS, progress_value=5.0)
        )
        assert decision.emit is True
        assert decision.suppressed_count == 0

    def test_below_step_and_within_window_is_suppressed(self):
        clock = _FakeClock()
        gate = ProgressGate(
            ThrottlePolicy(percent_step=5.0, min_interval_seconds=10.0),
            time_source=clock,
        )
        gate.consider(Classification(LineClass.PROGRESS, progress_value=10.0))
        # +1% within 0s window must suppress.
        clock.advance(0.5)
        decision = gate.consider(
            Classification(LineClass.PROGRESS, progress_value=11.0)
        )
        assert decision.emit is False
        assert gate.pending_suppressed == 1

    def test_percent_step_crossed_emits_with_count(self):
        clock = _FakeClock()
        gate = ProgressGate(
            ThrottlePolicy(percent_step=5.0, min_interval_seconds=999.0),
            time_source=clock,
        )
        gate.consider(Classification(LineClass.PROGRESS, progress_value=10.0))
        # Three suppressed ticks (within window, below step):
        for v in (11.0, 12.0, 13.0):
            d = gate.consider(
                Classification(LineClass.PROGRESS, progress_value=v)
            )
            assert d.emit is False
        # Crossing the 5-step (10 -> 15) emits with the suppressed count.
        crossing = gate.consider(
            Classification(LineClass.PROGRESS, progress_value=15.0)
        )
        assert crossing.emit is True
        assert crossing.suppressed_count == 3

    def test_time_window_emits_for_non_numeric_lines_with_count(self):
        clock = _FakeClock()
        gate = ProgressGate(
            ThrottlePolicy(percent_step=999.0, min_interval_seconds=10.0),
            time_source=clock,
        )
        gate.consider(Classification(LineClass.PROGRESS))
        clock.advance(2.0)
        for _ in range(2):
            d = gate.consider(Classification(LineClass.PROGRESS))
            assert d.emit is False
        clock.advance(20.0)
        decision = gate.consider(Classification(LineClass.PROGRESS))
        assert decision.emit is True
        assert decision.suppressed_count == 2

    def test_total_suppressed_accumulates_across_emissions(self):
        clock = _FakeClock()
        gate = ProgressGate(
            ThrottlePolicy(percent_step=10.0, min_interval_seconds=999.0),
            time_source=clock,
        )
        gate.consider(Classification(LineClass.PROGRESS, progress_value=10.0))
        for v in (11.0, 12.0):
            gate.consider(Classification(LineClass.PROGRESS, progress_value=v))
        gate.consider(Classification(LineClass.PROGRESS, progress_value=20.0))
        for v in (21.0, 22.0, 23.0):
            gate.consider(Classification(LineClass.PROGRESS, progress_value=v))
        # 5 suppressed total; 3 pending since last emit.
        assert gate.total_suppressed == 5
        assert gate.pending_suppressed == 3

    def test_time_window_does_not_short_circuit_inside_percent_step(self):
        """A tick that crosses ``min_interval_seconds`` but not ``percent_step`` stays suppressed."""

        clock = _FakeClock()
        gate = ProgressGate(
            ThrottlePolicy(percent_step=10.0, min_interval_seconds=1.0),
            time_source=clock,
        )
        first = gate.consider(
            Classification(LineClass.PROGRESS, progress_value=1.0)
        )
        assert first.emit is True
        clock.advance(2.0)
        second = gate.consider(
            Classification(LineClass.PROGRESS, progress_value=2.0)
        )
        assert second.emit is False
        assert gate.pending_suppressed == 1

    def test_first_numeric_line_after_non_numeric_emit_primes_baseline(self):
        """A non-numeric first emit must not silence subsequent numeric lines forever."""

        clock = _FakeClock()
        gate = ProgressGate(
            ThrottlePolicy(percent_step=10.0, min_interval_seconds=999.0),
            time_source=clock,
        )
        banner = gate.consider(Classification(LineClass.PROGRESS))
        assert banner.emit is True
        clock.advance(0.1)
        first_numeric = gate.consider(
            Classification(LineClass.PROGRESS, progress_value=12.0)
        )
        assert first_numeric.emit is True
        clock.advance(0.1)
        next_numeric = gate.consider(
            Classification(LineClass.PROGRESS, progress_value=14.0)
        )
        assert next_numeric.emit is False
        clock.advance(0.1)
        crossing = gate.consider(
            Classification(LineClass.PROGRESS, progress_value=22.0)
        )
        assert crossing.emit is True

    def test_consider_rejects_non_progress(self):
        gate = ProgressGate(ThrottlePolicy())
        with pytest.raises(ValueError):
            gate.consider(Classification(LineClass.URGENT))


class TestAnnotateProgressLine:
    def test_no_annotation_when_zero(self):
        assert annotate_progress_line("pytest 25%\n", 0) == "pytest 25%\n"

    def test_annotation_inserted_before_newline(self):
        out = annotate_progress_line("pytest 25%\n", 4)
        assert out == "pytest 25% (suppressed 4 ticks)\n"

    def test_annotation_appended_to_unterminated_line(self):
        out = annotate_progress_line("pytest 25%", 4)
        assert out == "pytest 25% (suppressed 4 ticks)"


class TestLoadThrottlePolicy:
    def test_defaults_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(tmp_path / "missing.json"))
        policy = load_throttle_policy()
        assert policy.percent_step == DEFAULT_PERCENT_STEP
        assert policy.min_interval_seconds == DEFAULT_MIN_INTERVAL_SECONDS

    def test_valid_overrides_applied(self, tmp_path, monkeypatch):
        config_path = tmp_path / ".yoke" / "config.json"
        config_path.parent.mkdir()
        config_path.write_text(
            '{"settings": {'
            '"watcher_progress_percent_step": 12, '
            '"watcher_progress_min_interval_seconds": 30'
            '}}\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))
        policy = load_throttle_policy()
        assert policy.percent_step == 12.0
        assert policy.min_interval_seconds == 30.0

    @pytest.mark.parametrize("bad_value", ["banana", "-1", "0", ""])
    def test_invalid_value_falls_back_to_default(
        self, tmp_path, monkeypatch, bad_value
    ):
        config_path = tmp_path / ".yoke" / "config.json"
        config_path.parent.mkdir()
        config_path.write_text(
            '{"settings": {'
            f'"watcher_progress_percent_step": "{bad_value}", '
            f'"watcher_progress_min_interval_seconds": "{bad_value}"'
            '}}\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))
        policy = load_throttle_policy()
        # Bad config never silently breaks — defaults take over.
        assert policy.percent_step == DEFAULT_PERCENT_STEP
        assert policy.min_interval_seconds == DEFAULT_MIN_INTERVAL_SECONDS

"""Native payload duration is preferred over start-row elapsed time."""

from __future__ import annotations

from yoke_core.domain.observe_parsing import parse_hook_event


def test_native_duration_is_used_without_tool_use_id() -> None:
    rec = parse_hook_event(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "duration_ms": 25,
            "session_id": "sess-native",
        },
        hook_event="PostToolUse",
    )
    assert rec is not None
    assert rec.duration_ms == 25
    assert rec.tool_use_id is None


def test_native_duration_wins_over_missing_start_row() -> None:
    rec = parse_hook_event(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "tool_use_id": "tu-native",
            "duration_ms": 12,
            "session_id": "sess-native",
        },
        hook_event="PostToolUse",
    )
    assert rec is not None
    assert rec.duration_ms == 12


def test_missing_native_duration_retains_labelled_hook_measurement(monkeypatch):
    from yoke_core.domain import observe_parsing
    from yoke_core.domain.observe_event_emission import build_envelope
    from yoke_core.domain.observe_timing import ElapsedMeasurement

    monkeypatch.setattr(
        observe_parsing,
        "measure_tool_call_duration",
        lambda *args, **kwargs: ElapsedMeasurement(355000, "measured"),
    )
    rec = parse_hook_event(
        {"tool_name": "Bash"}, session_id="session", hook_event="PostToolUse"
    )
    assert rec.duration_ms == 355000
    assert build_envelope(rec)["context"]["detail"]["timing_status"] == "measured"


def test_native_duration_survives_report_owner_recalculation(monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone
    from yoke_core.domain import hook_overhead_tool
    from yoke_core.domain.performance_observations import observation

    now = datetime.now(timezone.utc)
    end = now - timedelta(minutes=20)
    start = end - timedelta(seconds=355)
    envelope = json.dumps({"context": {"detail": {"timing_status": "native_duration"}}})
    source = {
        "event_id": "native-command",
        "event_name": "HarnessToolCallCompleted",
        "created_at": end,
        "duration_ms": 11240,
        "envelope": envelope,
        "executor": "codex",
        "tool_name": "Bash",
        "tool_use_id": "exec-command",
        "started_at": start,
        "completed_at": end,
    }
    result = observation(source, now)
    assert result["duration_ms"] == 11240
    assert result["breakdown"]["native_duration_ms"] == 11240
    fallback = observation({**source, "envelope": "{}"}, now)
    assert fallback["duration_ms"] == 355000
    assert fallback["breakdown"]["hook_elapsed_ms"] == 355000

    # The aggregate tool report and Performance inspection share the preference.
    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(hook_overhead_tool.db_backend, "connect", lambda: Connection())
    monkeypatch.setattr(
        hook_overhead_tool,
        "_tool_metric_rows",
        lambda *args: [
            (
                11240,
                envelope,
                end,
                "session",
                "codex",
                "codex-cli",
                "Bash",
                "exec-command",
                start,
                end,
            )
        ],
    )
    rows = hook_overhead_tool.tool_latency_rows(1)
    assert all(row["mean_ms"] == 11240 for row in rows)

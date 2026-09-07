"""A slow hook says which phase was slow, and says nothing else."""

from __future__ import annotations

from yoke_cli.hook_phase_timing import (
    HookPhaseTiming,
    PHASE_TIMING_ENV_VAR,
    PHASE_TIMING_MARKER,
    phase_timing_requested,
)


def test_the_three_phases_and_the_fallback_reason_are_all_named() -> None:
    summary = HookPhaseTiming(
        resident_wait_ms=2003,
        fallback_ms=1841,
        client_wall_ms=3944,
        fallback_reason="YOKE_HOOK_RESIDENT_UNREACHABLE",
    ).summary()

    assert summary.startswith(f"{PHASE_TIMING_MARKER}: ")
    assert "resident_wait_ms=2003" in summary
    assert "fallback_ms=1841" in summary
    assert "client_wall_ms=3944" in summary
    assert "fallback_reason=YOKE_HOOK_RESIDENT_UNREACHABLE" in summary


def test_an_unmeasured_phase_says_so_instead_of_reporting_zero() -> None:
    summary = HookPhaseTiming(resident_wait_ms=12).summary()

    assert "resident_wait_ms=12" in summary
    assert "fallback_ms=not-measured" in summary
    assert "client_wall_ms=not-measured" in summary
    assert "fallback_reason=none" in summary


def test_timing_is_off_until_this_machine_asks_for_it(monkeypatch) -> None:
    monkeypatch.delenv(PHASE_TIMING_ENV_VAR, raising=False)
    assert not phase_timing_requested()

    monkeypatch.setenv(PHASE_TIMING_ENV_VAR, "1")
    assert phase_timing_requested()


def test_a_degraded_hook_reports_its_phases_and_still_returns_its_exit_code(
    monkeypatch, capsys
) -> None:
    from pathlib import Path

    from yoke_cli.commands.adapters import hooks
    from yoke_cli.hook_resident_client import ResidentUnavailable

    def refuse(*_args, **_kwargs):
        raise ResidentUnavailable(
            "YOKE_HOOK_RESIDENT_UNREACHABLE",
            "socket unavailable (ConnectionRefusedError)",
            log_path=Path("/tmp/evaluator.log"),
            resident_wait_ms=2001,
        )

    monkeypatch.setattr(
        "yoke_cli.hook_resident_client.evaluate_with_resident", refuse
    )
    monkeypatch.setattr(
        hooks,
        "_evaluate_inprocess",
        lambda *_args, elapsed_ms=None, **_kwargs: (
            elapsed_ms.append(1841) if elapsed_ms is not None else None,
            7,
        )[1],
    )
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("sys.stdin", _EmptyStdin())

    exit_code = hooks.hook_evaluate(["PreToolUse"])

    assert exit_code == 7
    reported = capsys.readouterr().err
    assert f"{PHASE_TIMING_MARKER}: " in reported
    assert "resident_wait_ms=2001" in reported
    assert "fallback_ms=1841" in reported
    assert "fallback_reason=YOKE_HOOK_RESIDENT_UNREACHABLE" in reported


def test_the_timing_line_carries_no_payload_or_credential() -> None:
    summary = HookPhaseTiming(
        resident_wait_ms=1,
        fallback_ms=2,
        client_wall_ms=3,
        fallback_reason="YOKE_HOOK_RESIDENT_CRASHED",
    ).summary()

    # Only durations and one refusal code — nothing a payload could carry.
    for field in summary.removeprefix(f"{PHASE_TIMING_MARKER}: ").split(" "):
        name, _, value = field.partition("=")
        assert name in {
            "resident_wait_ms",
            "fallback_ms",
            "client_wall_ms",
            "fallback_reason",
        }
        assert value.isdigit() or value.replace("_", "").isalnum()


class _EmptyStdin:
    def read(self) -> str:
        return "{}"

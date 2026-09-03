"""Every registered `yoke` command teaches the same fix for a refused call.

The adapter wrapper exists because the OS text names the syscall, not the
boundary: an agent reads ``Operation not permitted`` as a broken database
and starts debugging Postgres instead of the harness config that refused.
"""

from __future__ import annotations

import pytest

from yoke_cli import sandbox_denial


def _fail(_remaining):
    raise OSError(1, "Operation not permitted")


def _succeed(remaining):
    return len(remaining)


def test_a_refused_command_is_translated_and_reports_failure(monkeypatch, capsys):
    monkeypatch.setattr(sandbox_denial, "sandbox_recovery", lambda: "RUN THE REPAIR.")
    assert sandbox_denial.run(_fail, [], ["items", "get", "YOK-1"]) == 1
    err = capsys.readouterr().err
    assert "yoke items get YOK-1 was refused" in err
    assert "RUN THE REPAIR." in err


def test_an_unidentified_harness_leaves_the_error_alone(monkeypatch):
    """Naming the wrong harness is worse than naming none, so it re-raises."""
    monkeypatch.setattr(sandbox_denial, "sandbox_recovery", lambda: None)
    with pytest.raises(OSError):
        sandbox_denial.run(_fail, [], ["items", "get"])


def test_any_other_failure_is_re_raised_untouched(monkeypatch):
    monkeypatch.setattr(sandbox_denial, "sandbox_recovery", lambda: "RUN THE REPAIR.")

    def _other(_remaining):
        raise ValueError("no such column: nope")

    with pytest.raises(ValueError):
        sandbox_denial.run(_other, [], ["items", "get"])


def test_a_successful_command_passes_its_result_through():
    assert sandbox_denial.run(_succeed, ["a", "b"], ["items", "get"]) == 2

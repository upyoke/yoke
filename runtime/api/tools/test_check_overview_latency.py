"""Production latency proof cannot pass on empty or incomplete telemetry."""

import json

import pytest

from runtime.api.tools.check_overview_latency import EvidenceUnavailable, evaluate


def _events(elapsed, *, members=10, outcome="ok"):
    rows = []
    for value in elapsed:
        rows.extend(
            [
                {"step": "shipping_overview", "phase": "start"},
                {
                    "step": "shipping_overview",
                    "phase": "end",
                    "elapsed_ms": value,
                    "member_count": members,
                    "outcome": outcome,
                },
            ]
        )
    return [{"message": "Deployment start timing: " + json.dumps(row)} for row in rows]


def test_populated_p95_excludes_empty_overviews():
    with pytest.raises(EvidenceUnavailable, match="latency failed"):
        evaluate(_events([10] * 100, members=0) + _events([6000]))
    assert evaluate(_events([100, 200, 4000]))["populated_p95_ms"] == 4000


@pytest.mark.parametrize("events", [[], _events([10], members=0), _events([10])[:1]])
def test_missing_or_unpaired_evidence_refuses(events):
    with pytest.raises(EvidenceUnavailable):
        evaluate(events)


def test_deadline_failure_cannot_hide_behind_good_p95():
    with pytest.raises(EvidenceUnavailable, match="latency failed"):
        evaluate(
            _events([100] * 100) + _events([25000], members=None, outcome="failed")
        )


def test_missing_controller_command_has_named_recovery(monkeypatch, capsys):
    from runtime.api.tools import check_overview_latency as checker

    monkeypatch.setattr("sys.argv", ["check-overview", "--run-id", "release-run"])

    def unavailable(_run_id):
        raise OSError("controller command missing")

    monkeypatch.setattr(checker, "window_start", unavailable)
    with pytest.raises(SystemExit) as raised:
        checker.main()
    assert raised.value.code == 1
    error = capsys.readouterr().err
    assert "overview_latency_evidence_unavailable" in error
    assert "verify the controller CLI and production log-read access" in error

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

"""Production origin proof needs both elapsed time and real, authorized traffic."""

import subprocess

import pytest

from runtime.api.tools import verify_session_resume_origin as proof


@pytest.mark.parametrize(
    ("counts", "reason"),
    [
        ("0|0|0|12", "origin_observation_pending"),
        ("1|0|0|0", "origin_observation_pending"),
        ("1|1|0|12", "unauthorized_resume"),
        ("1|0|1|12", "unauthorized_resume"),
        ("not a row", "origin_evidence_unreadable"),
    ],
)
def test_incomplete_or_unauthorized_evidence_refuses(monkeypatch, counts, reason):
    monkeypatch.setenv("DEPLOYMENT_RUN_ID", "test-release")
    monkeypatch.setattr(
        proof.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, counts, ""),
    )
    with pytest.raises(SystemExit, match=reason):
        proof.main()


def test_full_day_with_authorized_traffic_passes(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_RUN_ID", "test-release")

    def run(args, **kwargs):
        assert args[:3] == ["yoke", "db", "read"]
        assert "LEFT JOIN harness_sessions" in args[3]
        assert "INTERVAL '1 day'" in args[3]
        return subprocess.CompletedProcess(args, 0, "1|0|0|12\n", "")

    monkeypatch.setattr(proof.subprocess, "run", run)
    assert proof.main() == 0

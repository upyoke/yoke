"""Large run details stay available without overflowing routine human reads."""

import io
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import deployment_reads


@pytest.fixture
def render(monkeypatch):
    result = {
        "run_id": "run-example",
        "run": {
            "id": "run-example", "status": "executing", "current_stage": "qa",
            "member_items": [{"id": n, "detail": "x" * 2_000} for n in range(29)],
            "membership_removals": [{"id": 30}],
            "bound_sources": {"evidence": "x" * 30_000},
        },
        "attestation_warnings": [{"message": "x" * 2_000}],
    }
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        out = io.StringIO()
        kwargs["human_writer"](SimpleNamespace(result=result), out, io.StringIO())
        calls.append(out.getvalue())
        return 0

    monkeypatch.setattr(deployment_reads, "dispatch_and_emit", dispatch)
    return calls


def test_default_run_with_twenty_nine_members_is_bounded(render):
    assert deployment_reads.deployment_runs_get(["run-example"]) == 0
    text = render[-1]
    assert len(text.encode()) < 2_400
    assert "member count: 29" in text
    assert "removed member count: 1" in text
    assert "attestation warning count: 1" in text
    assert "executing" in text and "qa" in text
    assert "member_items membership_removals" in text
    assert "--include-member-closure" in text and "--full" in text


@pytest.mark.parametrize("option", ["--full", "--include-member-closure"])
def test_explicit_detail_is_complete(render, option):
    assert deployment_reads.deployment_runs_get(["run-example", option]) == 0
    assert "x" * 30_000 in render[-1]


@pytest.mark.parametrize("fields,projection", [
    (["status"], {"field": "status"}),
    (["status", "current_stage"], {"fields": ["status", "current_stage"]}),
])
def test_named_field_reads_keep_existing_transport(render, fields, projection):
    assert deployment_reads.deployment_runs_get(["run-example", *fields]) == 0
    assert render[0]["payload"] == projection
    assert "x" * 30_000 in render[-1]


def test_missing_membership_is_unknown():
    from yoke_cli.commands.adapters.deployment_run_output import write_run_summary

    out = io.StringIO()
    write_run_summary({"run_id": "run-example", "run": {"status": "executing"}}, out)
    assert "member count: unavailable" in out.getvalue()

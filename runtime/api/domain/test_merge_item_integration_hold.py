"""An integration dependency holds only the merge: the PR opens first."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import standalone_item_merge_cli as cli
from yoke_core.domain import standalone_item_merge_integration_hold as hold
from yoke_core.domain.merge_landing_readiness import LandingBlocker, LandingReadiness

HEAD = "c" * 40
ITEM = {
    "id": 7,
    "public_ref": "ITEM-7",
    "workflow": {"id": "dash"},
    "project": {"slug": "widgets"},
    "worktrees": [
        {"branch": "ITEM-7", "commit_sha": HEAD, "lane_role": "implementation"}
    ],
}
BLOCKED = (
    "integration_dependency_blocked: ITEM-7 may not land until its integration "
    "dependencies clear. Work, test and open the pull request now"
)
INTEGRATION = LandingBlocker(hold.INTEGRATION_GATE, BLOCKED)
QA_PROOF = LandingBlocker("QA proof", "ITEM-7: QA case 3 has not passed")


def _readiness(*blockers: LandingBlocker) -> LandingReadiness:
    return LandingReadiness(
        public_ref="ITEM-7",
        branch="ITEM-7",
        blockers=list(blockers),
        repo_root=Path("/tmp/checkout"),
        target="main",
    )


@pytest.mark.parametrize(
    "blockers,held",
    [
        ((INTEGRATION,), True),
        ((INTEGRATION, QA_PROOF), False),
        ((QA_PROOF,), False),
        ((), False),
        (
            (
                LandingBlocker(
                    hold.INTEGRATION_GATE,
                    "integration_dependency_gate_unavailable: could not evaluate",
                ),
            ),
            False,
        ),
    ],
)
def test_only_an_answered_integration_hold_publishes(blockers, held):
    assert hold.held_only_by_integration(_readiness(*blockers)) is held


def _ensure_spy(calls, result):
    def ensure(ctx, public_ref, *, lane_head, item_public_ref):
        calls.append((ctx.args.branch, ctx.args.target, public_ref, lane_head,
                      item_public_ref))
        return result

    return ensure


def test_publish_opens_and_records_the_pull_request_at_the_lane_head(monkeypatch):
    monkeypatch.setattr(hold, "_find_worktree", lambda *_a: "/tmp/lane")
    calls: list = []
    lines = hold.publish_held_lane(
        ITEM, _readiness(INTEGRATION), ensure=_ensure_spy(calls, ("88", None, ""))
    )
    assert calls == [("ITEM-7", "main", "ITEM-7", HEAD, "ITEM-7")]
    assert lines == [
        f"pull request 88 is open for 'ITEM-7' at {HEAD[:12]}, not armed or "
        "queued: only the merge is held."
    ]


def test_publish_reports_a_record_failure_and_an_open_failure(monkeypatch):
    monkeypatch.setattr(hold, "_find_worktree", lambda *_a: "/tmp/lane")
    warned = hold.publish_held_lane(
        ITEM, _readiness(INTEGRATION),
        ensure=_ensure_spy([], ("88", None, "pull request 88 was not recorded")),
    )
    assert warned[0] == "warning: pull request 88 was not recorded"
    assert warned[1].startswith("pull request 88 is open")
    failed = hold.publish_held_lane(
        ITEM, _readiness(INTEGRATION), ensure=_ensure_spy([], ("", "push refused", ""))
    )
    assert failed[0].startswith("pull request not opened for 'ITEM-7': push refused")


def _run_merge(monkeypatch, readiness, argv):
    published: list = []
    failures: list = []
    monkeypatch.setattr(cli, "_resolve_item", lambda *_a: (ITEM, ""))
    monkeypatch.setattr(cli.report, "bind", lambda **_k: lambda *_a, **_kw: None)
    monkeypatch.setattr(cli, "refresh_recorded_head", lambda item, _r: (item, ""))
    monkeypatch.setattr(cli.readiness_gate, "assess", lambda *_a, **_k: readiness)
    monkeypatch.setattr(cli.readiness_gate, "print_check", lambda *_a, **_k: 1)
    monkeypatch.setattr(
        cli.hold, "publish_held_lane",
        lambda item, ready: published.append(item["public_ref"]) or ["pull request 88"],
    )
    monkeypatch.setattr(
        cli.report, "fail_json",
        lambda message, **extra: failures.append((message, extra)) or 1,
    )
    return cli.run(argv), published, failures


def test_merge_publishes_then_returns_the_integration_refusal(monkeypatch, capsys):
    readiness = _readiness(INTEGRATION)
    code, published, failures = _run_merge(monkeypatch, readiness, ["ITEM-7"])
    assert code == 1
    assert published == ["ITEM-7"]
    assert failures[0][0] == readiness.refusal()
    assert BLOCKED in failures[0][0]
    assert failures[0][1]["integration_hold"] == ["pull request 88"]
    assert "pull request 88" in capsys.readouterr().out


@pytest.mark.parametrize(
    "blockers,argv",
    [((INTEGRATION, QA_PROOF), ["ITEM-7"]), ((INTEGRATION,), ["ITEM-7", "--check"])],
)
def test_other_blockers_and_check_publish_nothing(monkeypatch, blockers, argv):
    code, published, _failures = _run_merge(monkeypatch, _readiness(*blockers), argv)
    assert code == 1
    assert published == []

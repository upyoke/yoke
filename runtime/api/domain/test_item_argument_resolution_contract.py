"""Cross-boundary contract for public item arguments and typed internal ids."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain import machine_config
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.yok_n_parser import parse_item_argument

DECOY_INTERNAL_ID = 2318
DECOY_PUBLIC_SEQUENCE = 2279
YOKE_INTERNAL_ID = 2366
SHARED_PUBLIC_SEQUENCE = 2318
FOREIGN_INTERNAL_ID = 4366


@pytest.fixture
def identity_db(test_db):
    """Seed overlapping internal and public numbers in two projects."""
    seed_project_identities(test_db)
    test_db.execute(
        "UPDATE projects SET public_item_prefix='YOK' WHERE slug='yoke'"
    )
    test_db.execute(
        "UPDATE projects SET public_item_prefix='EXT' "
        "WHERE slug='externalwebapp'"
    )
    for item_id, project_id, sequence in (
        (DECOY_INTERNAL_ID, 1, DECOY_PUBLIC_SEQUENCE),
        (YOKE_INTERNAL_ID, 1, SHARED_PUBLIC_SEQUENCE),
        (FOREIGN_INTERNAL_ID, 2, SHARED_PUBLIC_SEQUENCE),
    ):
        insert_item(
            test_db,
            id=item_id,
            project_id=project_id,
            project_sequence=sequence,
        )
    return test_db


@pytest.mark.parametrize(
    ("raw", "project", "expected"),
    [
        ("2318", "yoke", YOKE_INTERNAL_ID),
        ("YOK-2318", None, YOKE_INTERNAL_ID),
        ("EXT-2318", None, FOREIGN_INTERNAL_ID),
        (YOKE_INTERNAL_ID, None, YOKE_INTERNAL_ID),
    ],
)
def test_public_and_internal_resolution_matrix(
    identity_db, raw, project, expected,
) -> None:
    assert parse_item_argument(raw, project=project, conn=identity_db) == expected


def test_explicit_project_wins_over_checkout_mapping(
    identity_db, monkeypatch,
) -> None:
    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: 2)
    assert (
        parse_item_argument("2318", project="yoke", conn=identity_db)
        == YOKE_INTERNAL_ID
    )


def test_checkout_mapping_resolves_bare_sequence(identity_db, monkeypatch) -> None:
    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: 2)
    assert parse_item_argument("2318", conn=identity_db) == FOREIGN_INTERNAL_ID


def test_missing_context_refuses_before_identity_read(monkeypatch) -> None:
    from yoke_core.domain import yok_n_parser

    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: None)
    identity_read = Mock(side_effect=AssertionError("identity read must not run"))
    monkeypatch.setattr(yok_n_parser, "_resolve_over_open_path", identity_read)

    with pytest.raises(ValueError, match="bare numeric item refs are project-local"):
        parse_item_argument("2318")
    identity_read.assert_not_called()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2318", YOKE_INTERNAL_ID),
        ("YOK-2318", YOKE_INTERNAL_ID),
        ("EXT-2318", FOREIGN_INTERNAL_ID),
    ],
)
def test_done_transition_resolves_before_running(
    identity_db, monkeypatch, raw, expected,
) -> None:
    from yoke_core.engines import done_transition

    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: 1)
    run = Mock(return_value=0)
    monkeypatch.setattr(done_transition, "run", run)

    assert done_transition.main([raw]) == 0
    assert run.call_args.args[0] == expected


def test_done_transition_missing_context_has_no_side_effect(
    identity_db, monkeypatch, capsys,
) -> None:
    from yoke_core.engines import done_transition

    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: None)
    run = Mock(side_effect=AssertionError("transition must not run"))
    monkeypatch.setattr(done_transition, "run", run)

    assert done_transition.main(["2318"]) == 2
    assert "bare numeric item refs are project-local" in capsys.readouterr().err
    run.assert_not_called()


def _invoke_missing_context_boundary(name: str, monkeypatch) -> str:
    if name == "advance-skip":
        from yoke_core.domain import advance_skip

        return str(advance_skip.main(["polish", "2318"]))
    if name == "ac-presence":
        from yoke_core.domain import check_ac_presence

        return str(check_ac_presence.main(["2318"]))
    if name == "hard-blocks":
        from yoke_core.domain import check_hard_blocks

        return str(check_hard_blocks.main(["2318"]))
    if name == "conduct-handoff":
        from yoke_core.domain import conduct_reviewed_handoff

        return str(conduct_reviewed_handoff.main(["2318"]))
    if name == "shepherd-gate":
        from yoke_core.domain import shepherd_gate

        return str(shepherd_gate.main(["check", "2318"]))
    if name == "verify-claim":
        from yoke_core.domain import verify_claim

        return str(verify_claim.main(["--item-id", "2318"]))
    if name == "stale-string-audit":
        from yoke_core.domain import stale_string_audit

        return str(stale_string_audit.main(["discover-surfaces", "2318"]))
    if name == "render-body":
        from yoke_core.domain import render_body

        return str(render_body.main(["2318"]))
    if name == "db-claim-prose":
        from yoke_core.domain import db_claim_prose_check

        return str(db_claim_prose_check._cli_main(["check-item", "2318"]))
    if name == "path-claim-coverage":
        from yoke_core.domain import path_claim_spec_coverage_gate

        return str(path_claim_spec_coverage_gate.main(["2318"]))
    if name == "idea-readiness":
        from yoke_core.domain import idea_readiness_check

        return str(idea_readiness_check.main(["2318"]))
    if name == "idea-readiness-repair":
        from yoke_core.domain import idea_readiness_repair

        return str(idea_readiness_repair.main(["--item", "2318"]))
    if name == "claim-coverage-repair":
        from yoke_core.domain import idea_readiness_repair_claim_coverage

        return str(
            idea_readiness_repair_claim_coverage.main(["--item", "2318"])
        )
    if name == "overlap-repair":
        from yoke_core.domain import idea_readiness_repair_cross_item_overlap

        return str(
            idea_readiness_repair_cross_item_overlap.main(["--item", "2318"])
        )
    if name == "usher-reconcile":
        from yoke_core.engines import usher_reconcile_github

        return str(usher_reconcile_github.main(["2318"]))
    if name == "deploy-item-run":
        from yoke_core.domain import deploy_pipeline_item_run

        return str(deploy_pipeline_item_run.create_run_for_item_ref("2318"))
    if name == "worktree-resolve":
        from yoke_core.domain.worktree_item_resolve import resolve_item_worktree

        with pytest.raises(ValueError) as raised:
            resolve_item_worktree("2318")
        return str(raised.value)
    if name == "validate-epic":
        from yoke_core.domain.validate_epic_context import _resolve_epic

        with pytest.raises(ValueError) as raised:
            _resolve_epic(Mock(), "2318")
        return str(raised.value)
    if name == "session-focus":
        from yoke_core.hooks.sessions_claims import cmd_who_claims

        with pytest.raises(ValueError) as raised:
            cmd_who_claims(Mock(), "2318")
        return str(raised.value)
    if name == "github-ownership":
        from yoke_core.domain.backlog_github_sync_cli import check_ownership

        allowed, reason, holder = check_ownership("2318", conn=Mock())
        assert (allowed, holder) == (False, "")
        return reason
    raise AssertionError(name)


@pytest.mark.parametrize(
    "boundary",
    [
        "advance-skip", "ac-presence", "hard-blocks", "conduct-handoff",
        "shepherd-gate", "verify-claim", "stale-string-audit", "render-body",
        "db-claim-prose", "path-claim-coverage", "idea-readiness",
        "idea-readiness-repair", "claim-coverage-repair", "overlap-repair",
        "usher-reconcile", "deploy-item-run", "worktree-resolve",
        "validate-epic", "session-focus", "github-ownership",
    ],
)
def test_operator_boundaries_preserve_missing_context_teaching(
    boundary, monkeypatch, capsys,
) -> None:
    from yoke_core.domain import yok_n_parser

    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: None)
    identity_read = Mock(side_effect=AssertionError("identity read must not run"))
    monkeypatch.setattr(yok_n_parser, "_resolve_over_open_path", identity_read)

    detail = _invoke_missing_context_boundary(boundary, monkeypatch)
    captured = capsys.readouterr()

    assert "bare numeric item refs are project-local" in (
        detail + captured.out + captured.err
    )
    identity_read.assert_not_called()


def test_legacy_deploy_item_run_keeps_public_ref_for_nested_reads(
    monkeypatch,
) -> None:
    from yoke_core.domain import deploy_pipeline_item_run

    calls: list[tuple[str, ...]] = []

    def yoke_db(*args: str, **_kwargs) -> str:
        calls.append(args)
        if args[:2] == ("items", "get"):
            return "flow-1" if args[-1] == "deployment_flow" else "yoke"
        if args[:2] == ("runs", "create-run"):
            return "run-20260821-001"
        return "ok"

    monkeypatch.setattr(
        deploy_pipeline_item_run,
        "parse_item_argument",
        lambda _raw: YOKE_INTERNAL_ID,
    )
    monkeypatch.setattr(deploy_pipeline_item_run, "_yoke_db", yoke_db)

    result = deploy_pipeline_item_run.create_run_for_item_ref("2318")

    assert result is not None
    assert calls[0] == ("items", "get", "2318", "deployment_flow")
    assert calls[1] == ("items", "get", "2318", "project")
    assert calls[-1] == (
        "runs", "add-item", "run-20260821-001", str(YOKE_INTERNAL_ID),
    )


def test_https_resolution_carries_raw_ref_and_project(monkeypatch) -> None:
    from yoke_core.domain import control_plane_transport

    monkeypatch.setattr(
        control_plane_transport,
        "local_connection_or_none",
        lambda _connect: None,
    )
    seen = {}

    def relay(function_id, payload, target):
        seen.update(function_id=function_id, payload=payload, target=target)
        return {"item": {"id": YOKE_INTERNAL_ID}}

    monkeypatch.setattr(control_plane_transport, "relay", relay)
    assert (
        parse_item_argument("2318", project="yoke")
        == YOKE_INTERNAL_ID
    )
    assert seen["target"].item_ref == "2318"
    assert seen["target"].project_id == "yoke"

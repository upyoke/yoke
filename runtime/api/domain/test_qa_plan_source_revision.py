"""Release QA uses frozen source definitions or refuses a newer saved source."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_installer_campaign_plan_sync import (
    source_checkout as source_checkout,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    seed_member_qa_case,
)
from yoke_core.domain import qa_plan_source_revision as source_binding
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    snapshot_flow_requirements,
    _plan_snapshot,
)
from yoke_core.domain.qa_plan_management import QaPlanError, replace_plan_cases
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)


@pytest.fixture
def bound_plan(test_db, source_checkout, monkeypatch):
    root, git = source_checkout
    old = git(root, "rev-parse", "HEAD").stdout.strip()
    rid = seed_member_qa_case(
        test_db, run_id="run-source-proof", member_item_id=9811, lineage=old
    )
    pid = test_db.execute(
        "SELECT plan_id FROM qa_requirements WHERE id=%s", (rid,)
    ).fetchone()[0]
    test_db.execute("UPDATE projects SET default_branch='stable' WHERE id=1")
    test_db.execute("UPDATE qa_plans SET source_revision=%s WHERE id=%s", (old, pid))
    row = test_db.execute(
        "SELECT r.flow,f.stages FROM deployment_runs r JOIN deployment_flows f ON f.id=r.flow WHERE r.id='run-source-proof'"
    ).fetchone()
    frozen = snapshot_flow_requirements(
        test_db, flow_id=row["flow"], project_id=1, stages=json.loads(row["stages"])
    )
    test_db.execute(
        "UPDATE deployment_runs SET release_lineage=%s,requirement_snapshot=%s WHERE id='run-source-proof'",
        (old, frozen),
    )
    test_db.commit()
    monkeypatch.setattr(
        source_binding,
        "open_carried_work_source",
        lambda conn, project_id: LocalCheckoutSource(str(root)),
    )
    original = _plan_snapshot(test_db, pid, project_id=1)["cases"]
    (root / "cases.json").write_text('["new behavior"]\n')
    assert git(root, "commit", "-am", "Change source behavior").returncode == 0
    new = git(root, "rev-parse", "HEAD").stdout.strip()
    assert git(root, "push", "origin", "stable").returncode == 0
    changed = [
        {
            **case,
            "instructions": "expect the newer behavior",
            "method_config": {"command": "false"},
        }
        for case in original
    ]
    replace_plan_cases(test_db, plan_id=pid, cases=changed, source_revision=new)
    return pid, rid, old, new, original


def test_frozen_candidate_definitions_survive_a_later_saved_plan_sync(
    test_db, bound_plan
):
    pid, rid, old, new, original = bound_plan
    test_db.execute("DELETE FROM qa_requirements WHERE id=%s", (rid,))
    test_db.commit()
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-source-proof",
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=9811,
    )
    created = result["created_requirement_ids"]
    assert len(created) == 1
    actual = test_db.execute(
        "SELECT instructions FROM qa_requirements WHERE id=%s", (created[0],)
    ).fetchone()[0]
    assert actual == original[0]["instructions"]
    config = test_db.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (created[0],)
    ).fetchone()[0]
    assert json.loads(config)["command"] == original[0]["method_config"]["command"]
    assert result["candidate_revision"] == old
    assert (
        test_db.execute(
            "SELECT source_revision FROM qa_plans WHERE id=%s", (pid,)
        ).fetchone()[0]
        == new
    )


def test_live_newer_source_refuses_before_deployment_refresh_writes(
    test_db, bound_plan
):
    pid, rid, old, new, original = bound_plan
    with pytest.raises(
        QaPlanError, match="qa_plan_source_candidate_mismatch.*Release a candidate"
    ):
        rematerialize_for_deployment_stage(
            test_db,
            deployment_run_id="run-source-proof",
            deployment_stage=ITEM_QA_STAGE,
            deployment_member_item_id=9811,
        )
    assert (
        test_db.execute(
            "SELECT instructions FROM qa_requirements WHERE id=%s", (rid,)
        ).fetchone()[0]
        == original[0]["instructions"]
    )


def test_source_binding_cannot_be_removed_by_raw_replacement(test_db, bound_plan):
    pid, rid, old, new, original = bound_plan
    with pytest.raises(QaPlanError, match="qa_plan_source_revision_required"):
        replace_plan_cases(test_db, plan_id=pid, cases=original)
    assert (
        test_db.execute(
            "SELECT source_revision FROM qa_plans WHERE id=%s", (pid,)
        ).fetchone()[0]
        == new
    )


def _recorded_source(test_db, pid):
    return test_db.execute(
        "SELECT source_revision FROM qa_plans WHERE id=%s", (pid,)
    ).fetchone()[0]


def test_sync_from_an_ancestor_of_the_recorded_source_refuses(test_db, bound_plan):
    pid, rid, old, new, original = bound_plan
    with pytest.raises(
        QaPlanError,
        match=f"qa_plan_source_revision_regression: source {old} does not "
        f"descend from the plan's recorded source {new}.*current main",
    ):
        replace_plan_cases(test_db, plan_id=pid, cases=original, source_revision=old)
    test_db.rollback()
    assert _recorded_source(test_db, pid) == new


def test_sync_from_the_recorded_source_or_a_descendant_proceeds(
    test_db, bound_plan, source_checkout
):
    pid, rid, old, new, original = bound_plan
    root, git = source_checkout
    replace_plan_cases(test_db, plan_id=pid, cases=original, source_revision=new)
    assert _recorded_source(test_db, pid) == new
    (root / "cases.json").write_text('["newest behavior"]\n')
    assert git(root, "commit", "-am", "Change source again").returncode == 0
    newest = git(root, "rev-parse", "HEAD").stdout.strip()
    assert git(root, "push", "origin", "stable").returncode == 0
    replace_plan_cases(test_db, plan_id=pid, cases=original, source_revision=newest)
    assert _recorded_source(test_db, pid) == newest


def test_unknown_commit_refuses_by_name(test_db, bound_plan):
    pid, rid, old, new, original = bound_plan
    missing = "0" * 40
    with pytest.raises(
        QaPlanError, match=f"qa_plan_source_unmerged_or_unverified: .*{missing}"
    ):
        replace_plan_cases(
            test_db, plan_id=pid, cases=original, source_revision=missing
        )
    test_db.rollback()
    assert _recorded_source(test_db, pid) == new
    test_db.execute(
        "UPDATE qa_plans SET source_revision=%s WHERE id=%s", (missing, pid)
    )
    test_db.commit()
    with pytest.raises(
        QaPlanError,
        match=f"qa_plan_source_ancestry_unverified: the plan's recorded source "
        f"{missing} is not in the project repository",
    ):
        replace_plan_cases(test_db, plan_id=pid, cases=original, source_revision=new)
    test_db.rollback()
    assert _recorded_source(test_db, pid) == missing


def test_old_serving_response_refuses_source_sync_before_write(tmp_path, monkeypatch):
    from yoke_cli.commands.adapters import qa_plan_source_input as source_input

    cases = tmp_path / "cases.json"
    cases.write_text("[]")
    monkeypatch.setattr(source_input, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(source_input, "build_actor", lambda **kw: None)
    monkeypatch.setattr(
        source_input,
        "call_dispatcher",
        lambda **kw: SimpleNamespace(success=True, result={"plan": {"id": 1}}),
    )
    args = SimpleNamespace(
        stdin=False,
        cases_file=str(cases),
        plan_id=1,
        project="sample",
        session_id=None,
        source_revision="a" * 40,
    )
    with pytest.raises(
        ValueError, match="source_binding_unavailable.*No cases were written"
    ):
        source_input.case_payload(args)


def test_source_document_uses_version_admitted_sync_endpoint(tmp_path, monkeypatch):
    from yoke_cli.commands.adapters import (
        qa_plan_source_input as source_input,
        qa_catalog,
    )
    from unittest.mock import Mock

    document = {"source_revision": "a" * 40, "cases": [{"case_key": "probe"}]}
    path = tmp_path / "source.json"
    path.write_text(json.dumps(document))
    monkeypatch.setattr(source_input, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(source_input, "build_actor", lambda **kw: None)
    monkeypatch.setattr(
        source_input,
        "call_dispatcher",
        lambda **kw: SimpleNamespace(
            success=True, result={"plan": {"source_revision": None}}
        ),
    )
    dispatched = Mock(return_value=0)
    monkeypatch.setattr(qa_catalog, "dispatch_and_emit", dispatched)
    args = ["--project", "sample", "--plan-id", "1", "--cases-file", str(path)]
    assert qa_catalog.qa_plan_cases_sync(args) == 0
    assert dispatched.call_args.kwargs["function_id"] == "qa.plan_cases.sync"
    assert (
        dispatched.call_args.kwargs["payload"]["source_revision"]
        == document["source_revision"]
    )
    dispatched.reset_mock()
    assert qa_catalog.qa_plan_cases_replace(args) == 2
    dispatched.assert_not_called()


def test_presentation_shares_repository_and_exact_ancestry_only(monkeypatch):
    from unittest.mock import Mock
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation

    conn = object()
    source = Mock()
    source.resolve_commit.side_effect = lambda value: value
    source.contains_commit.return_value = True
    opened = Mock(return_value=source)
    monkeypatch.setattr(source_binding, "open_carried_work_source", opened)
    candidates = {"first": "a" * 40, "same": "a" * 40, "later": "b" * 40}
    monkeypatch.setattr(
        source_binding, "run_delivered_sha", lambda conn, run, project: candidates[run]
    )
    plan = {"id": 1, "project_id": 1, "source_revision": "c" * 40}

    @presentation_operation
    def read():
        source_binding.require_candidate_plan(conn, plan, "first")
        source_binding.require_candidate_plan(conn, {**plan, "id": 2}, "same")
        source_binding.require_candidate_plan(conn, plan, "later")
        source_binding.require_candidate_plan(
            conn, {**plan, "source_revision": "d" * 40}, "later"
        )
        source_binding.require_candidate_plan(conn, {**plan, "project_id": 2}, "first")

    read()
    assert opened.call_count == 2  # Project identity separates repositories.
    assert source.resolve_commit.call_count == 3  # Same candidate resolves once.
    assert (
        source.contains_commit.call_count == 4
    )  # Candidate and source separate proof.
    read()
    assert opened.call_count == 4
    assert source.contains_commit.call_count == 8
    source.contains_commit.return_value = False
    with pytest.raises(QaPlanError, match="qa_plan_source_candidate_mismatch"):
        read()  # A previous presentation cannot lend its pass to this one.
    source.contains_commit.side_effect = OSError("repository unavailable")
    with pytest.raises(QaPlanError, match="Restore project repository read access"):
        read()


def test_overview_uses_recorded_qa_while_admission_still_requires_source(
    test_db, bound_plan, monkeypatch
):
    from unittest.mock import Mock, patch
    from yoke_core.domain.deployment_run_list_read import list_deployment_runs
    from yoke_core.domain.deployment_run_carried_work_source import (
        CarriedWorkSourceUnavailable,
    )
    from runtime.api.domain.test_deployment_shipping_reads import CountedConnection

    unavailable = Mock(
        side_effect=CarriedWorkSourceUnavailable("offline", "Restore repository access")
    )
    monkeypatch.setattr(source_binding, "open_carried_work_source", unavailable)
    with patch(
        "yoke_core.domain.deployment_run_list_read.connect",
        return_value=CountedConnection(test_db),
    ):
        rows = list_deployment_runs(
            project=None, status=None, limit=20, relevance="overview"
        )
    run = next(row for row in rows if row["id"] == "run-source-proof")
    assert run["member_items"]
    assert all(
        member["item_qa"]["state"] != "unreadable" for member in run["member_items"]
    )
    unavailable.assert_not_called()
    # The display scope expires; an actual admission still refuses this source.
    with pytest.raises(QaPlanError, match="qa_plan_source_candidate_mismatch.*Restore"):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id="run-source-proof",
            deployment_stage=ITEM_QA_STAGE,
            deployment_member_item_id=9811,
        )
    assert unavailable.called
    from yoke_core.domain.deployment_qa_presentation_reads import (
        recorded_source_presentation,
    )

    # Even inside display composition, a locking admission cannot borrow it.
    with (
        recorded_source_presentation(),
        pytest.raises(QaPlanError, match="qa_plan_source_candidate_mismatch"),
    ):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id="run-source-proof",
            deployment_stage=ITEM_QA_STAGE,
            deployment_member_item_id=9811,
        )

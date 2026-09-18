"""Both readiness repairs, run where the item project's files are absent.

The hosted control plane has no checkout for any item's project, so every
repair there works from what a machine that does have one reported. These
run that shape for real: the checkout is genuinely unregistered rather
than patched away, the repairs are the production ones, and the only
thing stubbed is the body render and GitHub sync a spec write triggers,
which has nothing to do with where the files are.

What each journey owes is different. The stale-count repair rewrites the
spec, so it unbinds the reading that drove it and needs a second reading
to be verified. The claim repair touches neither spec nor tree, so the
first reading still verifies it — except for a narrow, which needs a
worktree no handoff supplies and must therefore refuse before it has
changed anything.
"""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
    local_human,
    seed_target,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.machine_config_test import clear_machine_checkout
from yoke_core.domain import backlog_rendering, idea_readiness_repair
from yoke_core.domain.idea_readiness_check import run_all_checks
from yoke_core.domain.idea_readiness_local_inputs import (
    build_local_execution_request,
    read_spec,
)
from yoke_core.domain.idea_readiness_repair import attempt_stale_count_repair
from yoke_core.domain.idea_readiness_repair_claim_coverage import (
    attempt_claim_coverage_repair,
)
from yoke_core.domain.idea_readiness_results import (
    CLASS_PURE_STALE_COUNT,
    VERDICT_PASS,
    VERDICT_UNAVAILABLE,
)
from yoke_core.domain.path_claims import register
from yoke_core.engines import readiness_local_observations as local

_ITEM_ID = 4951
_PROJECT_ID = 1
_BUDGET_PATH = "packages/yoke-core/src/yoke_core/domain/streamed_module.py"
_RECORDED_LINES = 120
_ACTUAL_LINES = 200


def _spec(recorded: int) -> str:
    return (
        "Modify `yoke_core.domain.streamed_module.stream_rows` so it streams.\n"
        "\n"
        "## File Budget\n\n"
        f"- `{_BUDGET_PATH}` — current {recorded} lines; remaining headroom "
        f"{350 - recorded}; at-or-over-limit: false; responsibility: streaming.\n"
    )


@pytest.fixture
def item(test_db):
    return insert_item(
        test_db, id=_ITEM_ID, workflow_id="dash", status="idea",
        spec=_spec(_RECORDED_LINES),
    )


@pytest.fixture
def observing_machine(tmp_path):
    """A checkout whose file has drifted past what the spec records."""
    root = tmp_path / "project"
    module = root / _BUDGET_PATH
    module.parent.mkdir(parents=True)
    # Defines the function the spec names, so the only thing the checks
    # find is the drift between its length and the recorded one.
    module.write_text(
        "def stream_rows():\n" + "    pass\n" * (_ACTUAL_LINES - 1),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@example.com",
         "-c", "user.name=t", "commit", "-q", "-m", "seed"],
        check=True,
    )
    return root


@pytest.fixture
def hosted(test_db):
    """This host holds the control plane and no project checkout at all."""
    clear_machine_checkout(_PROJECT_ID)
    yield
    clear_machine_checkout(_PROJECT_ID)


@pytest.fixture
def quiet_body_sync():
    """A spec write renders a body and pushes to GitHub; neither is under test."""
    with (
        mock.patch.object(backlog_rendering, "_render_body", return_value=True),
        mock.patch.object(
            backlog_rendering, "_sync_body", return_value=(True, "full"),
        ),
        mock.patch.object(backlog_rendering, "_record_sync_failure"),
        mock.patch.object(idea_readiness_repair, "_emit_audit", return_value=True),
    ):
        yield


def _observe(conn, repo_root) -> dict:
    return local.collect(
        build_local_execution_request(conn, _ITEM_ID, read_spec(conn, _ITEM_ID)),
        repo_root,
    )


def test_a_stale_count_repair_runs_from_another_machines_reading(
    test_db, item, hosted, observing_machine, quiet_body_sync,
) -> None:
    """The count written is the one the machine with the file reported."""
    observations = _observe(test_db, observing_machine)
    outcome = run_all_checks(test_db, _ITEM_ID, observations)
    assert outcome.classification == CLASS_PURE_STALE_COUNT

    repair = attempt_stale_count_repair(
        item_id=_ITEM_ID,
        issues=outcome.issue_payloads(),
        observations=observations,
    )

    assert [p.actual for p in repair.repaired_paths] == [_ACTUAL_LINES]
    assert read_spec(test_db, _ITEM_ID) == _spec(_ACTUAL_LINES)


def test_the_spec_write_unbinds_the_reading_that_drove_it(
    test_db, item, hosted, observing_machine, quiet_body_sync,
) -> None:
    """So the repair reports unverified rather than claiming a pass.

    This is the honest answer, not a failure: the write changed the spec
    every earlier reading was bound to, and nothing on this host can read
    the files again.
    """
    observations = _observe(test_db, observing_machine)
    outcome = run_all_checks(test_db, _ITEM_ID, observations)

    repair = attempt_stale_count_repair(
        item_id=_ITEM_ID,
        issues=outcome.issue_payloads(),
        observations=observations,
    )

    assert repair.rerun_verdict == VERDICT_UNAVAILABLE
    assert repair.success is False


def test_a_second_reading_completes_the_repair(
    test_db, item, hosted, observing_machine, quiet_body_sync,
) -> None:
    """The round the caller runs next, which is what actually verifies it."""
    first = _observe(test_db, observing_machine)
    attempt_stale_count_repair(
        item_id=_ITEM_ID,
        issues=run_all_checks(test_db, _ITEM_ID, first).issue_payloads(),
        observations=first,
    )

    second = _observe(test_db, observing_machine)
    verified = run_all_checks(test_db, _ITEM_ID, second)

    assert verified.verdict == VERDICT_PASS
    assert verified.unavailable == []


def test_a_repair_with_no_reading_at_all_refuses(
    test_db, item, hosted, quiet_body_sync,
) -> None:
    """No checkout here and none reported: nothing to repair against."""
    repair = attempt_stale_count_repair(
        item_id=_ITEM_ID,
        issues=[{
            "code": "STALE_LINE_COUNT",
            "context": {
                "path": _BUDGET_PATH,
                "recorded": _RECORDED_LINES,
                "actual": _ACTUAL_LINES,
            },
        }],
        observations=None,
    )

    assert repair.success is False
    assert read_spec(test_db, _ITEM_ID) == _spec(_RECORDED_LINES)


def _register_claim(conn, paths) -> int:
    actor = local_human(conn)
    target_ids = [seed_target(conn, path_string=p) for p in paths]
    claim_id = register(
        conn, actor_id=actor, integration_target="main",
        target_ids=target_ids, item_id=_ITEM_ID,
    )
    conn.commit()
    return claim_id


def test_a_narrow_refuses_before_it_has_changed_anything(
    test_db, item, hosted,
) -> None:
    """Dropping a path needs a boundary proof that reads the worktree.

    No handoff supplies one — the observing machine is asked for readiness
    findings, not for a claim boundary — so a host without the tree has to
    refuse, and refusing after the paired widen would leave the claim
    half-repaired.
    """
    _register_claim(test_db, [_BUDGET_PATH, "packages/yoke-core/stale.py"])

    repair = attempt_claim_coverage_repair(
        item_id=_ITEM_ID,
        issues=[
            {"code": "FILE_BUDGET_NOT_IN_CLAIM",
             "context": {"path": "packages/yoke-core/added.py"}},
            {"code": "CLAIM_NOT_IN_FILE_BUDGET",
             "context": {"path": "packages/yoke-core/stale.py"}},
        ],
    )

    assert repair.success is False
    assert repair.repaired_paths == []
    assert repair.error == "repair refused before mutation"
    assert repair.refused_paths[0]["reason"] == "narrow_boundary_checkout_missing"

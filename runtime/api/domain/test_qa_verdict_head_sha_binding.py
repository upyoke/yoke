"""A passing blocking verdict must name the tree it verified, and say so early.

The terminal gate matches every passing blocking run against the merged tree.
A run recorded without that identity reads as satisfied at the write surface
and in the gate summary, then refuses at the merge -- so the write refuses it
up front and both other surfaces describe what they do and do not check.
"""

from unittest.mock import patch

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import qa_run
from yoke_core.domain.qa_gate_summary import _format_text
from yoke_core.domain.qa_terminal_settlement import blocking_requirement_issues

HEAD_SHA = "99b148ac0c699c99b3173c847e89491a835b8919"
JSON_RESULT = (
    '{"ci_run_id": "32409940181", '
    '"verification_tree": {"head_sha": "' + HEAD_SHA + '"}}'
)
PROSE_RESULT = (
    "Exact-head CI result: head sha " + HEAD_SHA + ", "
    "run https://github.com/owner/repo/actions/runs/32409940181"
)


class _Conn:
    def close(self):
        pass


def _blocking_requirement(**overrides):
    row = {
        "qa_kind": "plan_case",
        "method_id": "command-ci",
        "blocking_mode": "blocking",
        "waived_at": None,
    }
    row.update(overrides)
    return row


def _record_verdict(raw_result, requirement_row):
    request = FunctionCallRequest(
        function="qa.run.record_verdict",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=7),
        payload={
            "performed_by": "ci_run",
            "verdict": "pass",
            "raw_result": raw_result,
        },
    )
    with patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()):
        with patch(
            "yoke_core.domain.db_helpers.query_one", return_value=requirement_row,
        ):
            return qa_run.handle_qa_run_record_verdict(request)


def test_prose_raw_result_is_refused_at_the_write():
    outcome = _record_verdict(PROSE_RESULT, _blocking_requirement())

    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "verification_tree" in outcome.error.message
    assert outcome.error.jsonpath == "$.payload.raw_result"


def test_empty_raw_result_is_refused_at_the_write():
    outcome = _record_verdict(None, _blocking_requirement())

    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"


def test_json_head_sha_satisfies_the_write_guard():
    assert not qa_run._names_no_verified_tree(
        "pass", _blocking_requirement(), JSON_RESULT,
    )


def test_guard_ignores_runs_the_terminal_gate_never_sha_matches():
    prose = PROSE_RESULT
    assert not qa_run._names_no_verified_tree("fail", _blocking_requirement(), prose)
    assert not qa_run._names_no_verified_tree(
        "pass", _blocking_requirement(blocking_mode="advisory"), prose,
    )
    assert not qa_run._names_no_verified_tree(
        "pass", _blocking_requirement(waived_at="2026-08-20T00:00:00Z"), prose,
    )


def test_stale_sha_recovery_names_the_json_shape():
    issues = blocking_requirement_issues(
        [
            {
                "id": 15542,
                "blocking_mode": "blocking",
                "run_id": 16569,
                "verdict": "pass",
                "completed_at": "2026-08-20T00:00:00Z",
                "method_id": "command-ci",
                "requirement_source": "flow_derived",
                "recorded_head_sha": "",
            }
        ],
        accepted_shas=(HEAD_SHA,),
        public_ref="YOK-1",
        require_any=True,
    )

    assert len(issues) == 1
    assert issues[0].state == "stale-sha"
    recovery = issues[0].recovery
    assert "JSON" in recovery
    assert "verification_tree" in recovery
    assert "head_sha" in recovery


def test_gate_summary_text_discloses_that_it_skips_tree_freshness():
    text = _format_text({
        "target": "YOK-1",
        "transition": "reviewed-implementation",
        "qa_tables_present": True,
        "no_requirements": False,
        "satisfied": True,
        "blocking_unsatisfied_count": 0,
        "browser_unsatisfied_count": 0,
        "e2e_unsatisfied_count": 0,
        "tree_freshness_checked": False,
        "requirements": [],
    })

    assert "Tree freshness: not evaluated here" in text

"""A machine reporting readiness findings cannot invent consequences.

The claim-coverage repair turns an issue's ``context.path`` into a
path-claim amendment, and the stale-count repair turns one into a spec
rewrite. Both take their issues from a readiness run that may have been
performed on another machine, so admission is what stands between a
reported finding and a write. These cover what it lets through.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.idea_readiness_observation_admission import (
    CODE_NOT_OBSERVABLE,
    CONTEXT_NOT_IN_SPEC,
    admit_advisories,
    admit_issues,
    observable_issue_codes,
)

_BUDGET_PATH = "packages/yoke-core/src/yoke_core/domain/streamed.py"
_REFERENCE = "yoke_core.domain.streamed.stream_rows"
_COMMAND = "python3 -m pytest runtime/api/test_streamed.py"
_SPEC = (
    f"Modify `{_REFERENCE}` so it streams.\n"
    "\n"
    "## File Budget\n\n"
    f"- `{_BUDGET_PATH}` — current 10 lines; remaining headroom 340; "
    "at-or-over-limit: false; responsibility: streaming.\n"
)


def _issue(code: str, context: dict) -> dict:
    return {"code": code, "message": "m", "remediation": "r", "context": context}


def _admit(payloads):
    return admit_issues(
        payloads, spec_text=_SPEC, rehearsal_commands=[_COMMAND],
    )


def test_the_claim_coverage_codes_are_not_observable() -> None:
    """These are decided from the claim tables; no file read produces one.

    They are the codes that drive widen and narrow, so admitting one on a
    machine's say-so is what would let it drive a claim amendment.
    """
    codes = observable_issue_codes()

    assert "FILE_BUDGET_NOT_IN_CLAIM" not in codes
    assert "CLAIM_NOT_IN_FILE_BUDGET" not in codes


@pytest.mark.parametrize(
    "code",
    ["FILE_BUDGET_NOT_IN_CLAIM", "CLAIM_NOT_IN_FILE_BUDGET",
     "MISSING_FILE_BUDGET", "cross_item_overlap", "INVENTED_CODE", ""],
)
def test_a_code_the_file_checks_cannot_emit_is_rejected(code) -> None:
    admitted, rejected = _admit([_issue(code, {"path": _BUDGET_PATH})])

    assert admitted == []
    assert rejected == [{"reason": CODE_NOT_OBSERVABLE, "code": code}]


def test_a_sizing_finding_about_the_file_budget_is_admitted() -> None:
    admitted, rejected = _admit([
        _issue("STALE_LINE_COUNT",
               {"path": _BUDGET_PATH, "recorded": 10, "actual": 40}),
    ])

    assert rejected == []
    assert [issue.code for issue in admitted] == ["STALE_LINE_COUNT"]
    assert admitted[0].context["actual"] == 40


def test_a_sizing_finding_about_an_unlisted_path_is_rejected() -> None:
    """Otherwise a reported path becomes a claim amendment for any file at all."""
    admitted, rejected = _admit([
        _issue("STALE_LINE_COUNT", {"path": "packages/yoke-core/secrets.py"}),
    ])

    assert admitted == []
    assert rejected[0]["reason"] == CONTEXT_NOT_IN_SPEC


def test_a_function_owner_finding_must_name_a_reference_the_spec_makes() -> None:
    admitted, _rejected = _admit([
        _issue("UNRESOLVED_FUNCTION", {"reference": _REFERENCE}),
    ])
    forged, rejected = _admit([
        _issue("UNRESOLVED_FUNCTION", {"reference": "yoke_core.domain.other.f"}),
    ])

    assert [issue.code for issue in admitted] == ["UNRESOLVED_FUNCTION"]
    assert forged == []
    assert rejected[0]["reason"] == CONTEXT_NOT_IN_SPEC


def test_a_rehearsal_finding_must_name_a_command_the_item_declared() -> None:
    from yoke_core.domain.attestation_rehearsal_command_shape import (
        ATTESTATION_REHEARSAL_COMMAND_FAILED,
    )

    admitted, _rejected = _admit([
        _issue(ATTESTATION_REHEARSAL_COMMAND_FAILED, {"command": _COMMAND}),
    ])
    forged, rejected = _admit([
        _issue(ATTESTATION_REHEARSAL_COMMAND_FAILED, {"command": "rm -rf /"}),
    ])

    assert len(admitted) == 1
    assert forged == []
    assert rejected[0]["reason"] == CONTEXT_NOT_IN_SPEC


def test_a_finding_that_is_not_a_mapping_is_rejected() -> None:
    admitted, rejected = _admit(["not-an-issue", None])

    assert admitted == []
    assert len(rejected) == 2


def test_nothing_reported_admits_nothing_and_rejects_nothing() -> None:
    assert _admit(None) == ([], [])


def test_only_symlink_hints_about_file_budget_paths_survive() -> None:
    advisories = admit_advisories(
        [
            {"code": "SYMLINK_CANONICAL_HINT",
             "context": {"symlink_path": _BUDGET_PATH}},
            {"code": "SYMLINK_CANONICAL_HINT",
             "context": {"symlink_path": "elsewhere.py"}},
            {"code": "INVENTED_ADVISORY",
             "context": {"symlink_path": _BUDGET_PATH}},
        ],
        spec_text=_SPEC,
    )

    assert len(advisories) == 1
    assert advisories[0]["context"]["symlink_path"] == _BUDGET_PATH

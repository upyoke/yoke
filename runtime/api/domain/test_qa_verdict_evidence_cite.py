"""Agent verdicts cite evidence belonging to the case they settle."""

import pytest

from yoke_core.domain.qa_plan_review_submission import _validated_verdicts
from yoke_core.domain.qa_verdict_evidence_cite import QaVerdictEvidenceUncited


@pytest.mark.parametrize("verdict", ["pass", "fail"])
@pytest.mark.parametrize("rationale", ["looks good", "run 12", "artifact 40", "artifact 41.5"])
def test_artifact_bearing_case_requires_its_own_evidence(verdict, rationale):
    case = {
        "requirement_id": 5,
        "capture_run_id": 12,
        "artifacts": [{"id": 41}],
    }
    row = {"requirement_id": 5, "verdict": verdict, "rationale": rationale}
    with pytest.raises(QaVerdictEvidenceUncited, match="Cite one of artifact 41"):
        _validated_verdicts([case], [row])
    row["rationale"] = "The observed outcome is visible in Artifact 41."
    assert _validated_verdicts([case], [row]) == {5: (verdict, row["rationale"])}


def test_capture_run_citation_is_available_without_artifacts():
    case = {"requirement_id": 5, "capture_run_id": 12, "artifacts": []}
    row = {"requirement_id": 5, "verdict": "pass", "rationale": "The setup in run 12 passed."}
    assert _validated_verdicts([case], [row]) == {5: ("pass", row["rationale"])}


def test_undetermined_and_already_recorded_verdicts_use_their_existing_rules():
    case = {"requirement_id": 5, "capture_run_id": 12, "artifacts": []}
    row = {"requirement_id": 5, "verdict": "undetermined", "rationale": "Missing proof."}
    assert _validated_verdicts([case], [row]) == {5: ("undetermined", row["rationale"])}
    row.update(verdict="pass", rationale="Recorded before citations were required.")
    assert _validated_verdicts([case], [row], persisted=frozenset({5})) == {
        5: ("pass", row["rationale"])
    }

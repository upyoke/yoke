"""Pure dependency satisfaction values and recorded landing inputs."""

from yoke_core.domain.dependencies import (
    evaluate_satisfaction as _evaluate_satisfaction,
)
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

TEST_ITEM_ID = 4242
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"
TEST_WORKFLOW = builtin_workflow_runtime("issue")


def evaluate_satisfaction(*args, **kwargs):
    return _evaluate_satisfaction(*args, workflow=TEST_WORKFLOW, **kwargs)


class TestEvaluateSatisfaction:
    """Satisfaction condition evaluation."""

    # --- status:done ---

    def test_status_done_satisfied(self):
        result = evaluate_satisfaction("status:done", "done")
        assert result.satisfied is True

    def test_status_done_not_satisfied(self):
        for status in (
            "idea",
            "implementing",
            "reviewing-implementation",
            "implemented",
            "release",
        ):
            result = evaluate_satisfaction("status:done", status)
            assert result.satisfied is False, (
                f"status={status} should not satisfy status:done"
            )

    # --- status:implemented ---

    def test_status_implemented_satisfied_by_implemented(self):
        result = evaluate_satisfaction("status:implemented", "implemented")
        assert result.satisfied is True

    def test_status_implemented_satisfied_by_release(self):
        result = evaluate_satisfaction("status:implemented", "release")
        assert result.satisfied is True

    def test_status_implemented_satisfied_by_done(self):
        result = evaluate_satisfaction("status:implemented", "done")
        assert result.satisfied is True

    def test_status_implemented_not_satisfied(self):
        for status in ("idea", "implementing", "reviewing-implementation"):
            result = evaluate_satisfaction("status:implemented", status)
            assert result.satisfied is False

    # --- fact:merged ---

    def test_fact_merged_satisfied_by_recorded_landing(self):
        result = evaluate_satisfaction(
            "fact:merged",
            "implementing",
            TEST_ITEM_REF,
            blocking_merged=True,
            dependency_created_at="2026-01-01T00:00:00Z",
            blocking_merged_at="2026-01-02T00:00:00Z",
        )
        assert result.satisfied is True

    def test_fact_merged_not_satisfied_by_explicit_flag(self):
        result = evaluate_satisfaction(
            "fact:merged",
            "implementing",
            TEST_ITEM_REF,
            blocking_merged=False,
        )
        assert result.satisfied is False

    def test_fact_merged_landing_with_release_status(self):
        """A dated landing clears the edge even without an explicit merge flag."""
        result = evaluate_satisfaction(
            "fact:merged",
            "release",
            dependency_created_at="2026-01-01T00:00:00Z",
            blocking_merged_at="2026-01-02T00:00:00Z",
        )
        assert result.satisfied is True

    def test_fact_merged_landing_with_done_status(self):
        result = evaluate_satisfaction(
            "fact:merged",
            "done",
            dependency_created_at="2026-01-01T00:00:00Z",
            blocking_merged_at="2026-01-02T00:00:00Z",
        )
        assert result.satisfied is True

    def test_fact_merged_without_recorded_landing_stays_unsatisfied(self):
        result = evaluate_satisfaction("fact:merged", "implementing")
        assert result.satisfied is False

    # --- unknown ---

    def test_unknown_satisfaction_fails_safe(self):
        result = evaluate_satisfaction("unknown:condition", "done")
        assert result.satisfied is False

    # --- reasons ---

    def test_reason_contains_status(self):
        result = evaluate_satisfaction("status:done", "implementing")
        assert "implementing" in result.reason


# ---------------------------------------------------------------------------
# Gate-point query tests
# ---------------------------------------------------------------------------

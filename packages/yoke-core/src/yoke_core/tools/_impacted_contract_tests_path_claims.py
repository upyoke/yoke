"""Bounded impact companions for path-claim feasibility and policy teaching."""

PATH_CLAIM_FEASIBILITY_TESTS = (
    "runtime/api/domain/test_scheduler_path_claim_feasibility.py",
    "runtime/api/test_scheduler_next_step.py",
)

PATH_CLAIM_SOURCE_PATHS = frozenset(
    {
        "packages/yoke-core/src/yoke_core/domain/path_claims_overlap.py",
        "packages/yoke-core/src/yoke_core/domain/path_render_overlap.py",
    }
)

SURVEY_ADVISORY_TESTS = ("runtime/api/domain/test_conflict_survey_coordination.py",)

SURVEY_ADVISORY_SOURCE_PATHS = frozenset(
    {"packages/yoke-core/src/yoke_core/domain/path_claims_overlap_survey.py"}
)

OVERRIDE_POLICY_SOURCE_PATHS = frozenset(
    {
        "AGENTS.md",
        "docs/public/reference/agent-rules/verification.md",
    }
)
OVERRIDE_POLICY_TESTS = ("runtime/api/test_verification_failure_ownership_policy.py",)

PATH_CLAIM_CONTRACTS = (
    (
        "path_override_policy_contract",
        OVERRIDE_POLICY_SOURCE_PATHS,
        OVERRIDE_POLICY_TESTS,
    ),
    (
        "path_claim_feasibility_contract",
        PATH_CLAIM_SOURCE_PATHS,
        PATH_CLAIM_FEASIBILITY_TESTS,
    ),
    (
        "survey_advisory_contract",
        SURVEY_ADVISORY_SOURCE_PATHS,
        SURVEY_ADVISORY_TESTS,
    ),
)

__all__ = [
    "PATH_CLAIM_CONTRACTS",
    "PATH_CLAIM_FEASIBILITY_TESTS",
    "PATH_CLAIM_SOURCE_PATHS",
    "SURVEY_ADVISORY_SOURCE_PATHS",
    "SURVEY_ADVISORY_TESTS",
]

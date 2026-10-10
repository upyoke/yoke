"""QA requirement creation recipes stay aligned with workflow binding."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import schema_api_context as sac


REPO_ROOT = Path(__file__).resolve().parents[3]

_EXECUTOR_PACKET_PATHS = (
    "runtime/harness/claude/agents/yoke-engineer.md",
    "runtime/harness/claude/agents/yoke-tester.md",
    "runtime/harness/codex/agents/yoke-engineer.toml",
    "runtime/harness/codex/agents/yoke-tester.toml",
    "packages/yoke-core/src/yoke_core/install_bundle_tree/"
    "runtime/harness/claude/agents/yoke-engineer.md",
    "packages/yoke-core/src/yoke_core/install_bundle_tree/"
    "runtime/harness/claude/agents/yoke-tester.md",
    "packages/yoke-core/src/yoke_core/install_bundle_tree/"
    "runtime/harness/codex/agents/yoke-engineer.toml",
    "packages/yoke-core/src/yoke_core/install_bundle_tree/"
    "runtime/harness/codex/agents/yoke-tester.toml",
)

_REQUIRED_ADD_RECIPE = (
    "yoke qa requirement add --item PREFIX-N "
    "--qa-kind ac_verification --qa-phase verification "
    "--blocking-mode blocking --requirement-source ac_derived "
    "--workflow-transition reviewed-implementation"
)


@pytest.mark.parametrize("relative_path", _EXECUTOR_PACKET_PATHS)
def test_runner_packet_creation_recipes_are_transition_bound(
    relative_path: str,
) -> None:
    body = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    role = "engineer_agent" if "engineer" in relative_path else "tester_agent"
    assert f"yoke packets render --role {role} --topic qa --detail full" in body
    body = sac.render_topic_packet("qa", role=role, detail="full")
    assert _REQUIRED_ADD_RECIPE in body
    assert "every row must include `workflow_transition_id`" in body
    assert (
        "requirement-add --epic-id PREFIX-N --task-num K --workflow-transition STAGE"
    ) in body


@pytest.mark.parametrize(
    ("relative_path", "required_text"),
    (
        (
            ".agents/skills/yoke/implement/implementing/qa-seeding.md",
            "--qa-phase verification \\\n"
            "  --workflow-transition reviewed-implementation",
        ),
        (
            ".agents/skills/yoke/implement/implementing/browser-seeding.md",
            "--qa-phase verification \\\n"
            "  --workflow-transition reviewed-implementation",
        ),
        (
            ".agents/skills/yoke/shepherd/boss-verdict-transitions.md",
            "--qa-phase verification --workflow-transition QA_STAGE",
        ),
        (
            ".agents/skills/yoke/onboard/seed-work.md",
            "--requirement-source explicit --workflow-transition reviewed-implementation",
        ),
        (
            ".yoke/docs/reference/browser-scenarios.md",
            "--qa-phase verification \\\n"
            "  --workflow-transition reviewed-implementation",
        ),
        (
            ".yoke/docs/reference/db-reference/qa-cli-and-body-write.md",
            "--qa-phase verification \\\n"
            " --workflow-transition reviewed-implementation",
        ),
        (
            ".yoke/docs/reference/db-reference/qa-cli-and-body-write.md",
            "--qa-phase verification --workflow-transition reviewed-implementation",
        ),
        (
            "docs/qa-platform/cli-reference.md",
            "--requirement-source explicit \\\n"
            " --workflow-transition reviewed-implementation",
        ),
    ),
)
def test_authored_creation_recipes_are_transition_bound(
    relative_path: str,
    required_text: str,
) -> None:
    body = (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    def normalize(text: str) -> str:
        return " ".join(text.replace("\\\n", " ").split())

    assert normalize(required_text) in normalize(body)


def test_public_batch_recipe_requires_a_binding_in_every_row() -> None:
    body = (REPO_ROOT / "docs/qa-platform/cli-reference.md").read_text(encoding="utf-8")
    assert "Every `add-batch` row therefore includes" in body
    assert '`"workflow_transition_id":"<stage>"`' in body
    assert "every row requires `workflow_transition_id`" in body


def test_ci_recovery_recipe_preserves_repository_and_qa_authority() -> None:
    body = (REPO_ROOT / "docs/qa-platform/cli-reference.md").read_text(encoding="utf-8")
    prose = " ".join(body.split())
    assert "commands that target the repository explicitly" in prose
    assert "force-cancel endpoint for an orphaned run" in prose
    assert "yoke qa case run --requirement-id REQUIREMENT_ID" in prose
    assert "yoke watch pytest -- <CI pytest paths and options> --collect-only" in prose


_BROWSER_PLACEMENT_ANCHOR = "browser-scenarios.md#where-a-browser-case-runs"


def test_browser_case_placement_has_one_home() -> None:
    home = (REPO_ROOT / "docs/public/reference/browser-scenarios.md").read_text(
        encoding="utf-8"
    )
    compact = " ".join(home.split())
    assert "## Where a Browser case runs" in home
    assert "A `post_deploy` case with `--target-env ENV`" in compact
    assert "A pre-merge `verification` case against that server" in compact
    assert "No Browser case. Select the `approval_on_done` posture" in compact


@pytest.mark.parametrize(
    "relative_path",
    (
        ".agents/skills/yoke/idea/delivery-requirements.md",
        ".agents/skills/yoke/dash/file-and-claim.md",
        ".agents/skills/yoke/dash/verify.md",
        ".agents/skills/yoke/implement/implementing/browser-seeding.md",
        ".agents/skills/yoke/refine/review-rubric.md",
    ),
)
def test_browser_case_authoring_surfaces_link_the_placement_home(
    relative_path: str,
) -> None:
    body = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert _BROWSER_PLACEMENT_ANCHOR in body

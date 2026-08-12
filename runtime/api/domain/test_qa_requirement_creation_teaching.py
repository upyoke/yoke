"""QA requirement creation recipes stay aligned with workflow binding."""

from __future__ import annotations

from pathlib import Path

import pytest


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
    assert _REQUIRED_ADD_RECIPE in body
    assert "every row must include `workflow_transition_id`" in body
    assert (
        "requirement-add --epic-id E --task-num K --workflow-transition STAGE"
    ) in body


@pytest.mark.parametrize(
    ("relative_path", "required_text"),
    (
        (
            ".agents/skills/yoke/advance/implementing/qa-seeding.md",
            "--qa-phase verification \\\n"
            "  --workflow-transition reviewed-implementation",
        ),
        (
            ".agents/skills/yoke/advance/implementing/browser-seeding.md",
            "--qa-phase verification \\\n"
            "  --workflow-transition reviewed-implementation",
        ),
        (
            ".agents/skills/yoke/shepherd/boss-verdict-transitions.md",
            '--qa-phase "verification" \\\n'
            ' --workflow-transition "reviewed-implementation"',
        ),
        (
            ".agents/skills/yoke/onboard/seed-work.md",
            "--requirement-source explicit \\\n"
            "  --workflow-transition reviewed-implementation",
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
            ".yoke/docs/reference/db-reference.md",
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
    assert required_text in body


def test_public_batch_recipe_requires_a_binding_in_every_row() -> None:
    body = (REPO_ROOT / "docs/qa-platform/cli-reference.md").read_text(encoding="utf-8")
    assert "Every `add-batch` row therefore includes" in body
    assert '`"workflow_transition_id":"<stage>"`' in body
    assert "every row requires `workflow_transition_id`" in body

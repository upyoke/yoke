"""Agent filing recipes resolve scoped instructions before authoring.

Every recipe that files through a non-web entry surface also carries the
attestation flag, because ``items.create`` refuses the filing without it
and no adapter sets it for the caller.
"""

from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
SKILLS = ROOT / ".agents" / "skills" / "yoke"
RESOLVER = "yoke workflow execution-instruction resolve"
FUNCTION_ID = "workflow.execution_instruction.resolve"
ATTESTATION = "--execution-instructions-considered"

#: Every recipe file whose filing command reaches ``items.create``
#: through a non-web entry surface.
FILING_RECIPES = (
    "dash/file-and-claim.md",
    "idea/infer-and-create.md",
    "curate/cluster-and-work-item.md",
    "onboard/seed-work.md",
    "conduct/simulation-gate-escalation.md",
    "feed/materialize.md",
)


def _read(relative: str) -> str:
    return (SKILLS / relative).read_text(encoding="utf-8")


def _ordered(text: str, first: str, second: str) -> None:
    assert first in text
    assert second in text
    assert text.index(first) < text.index(second)


def test_dash_resolves_before_filing_and_before_escalation_authoring() -> None:
    text = _read("dash/file-and-claim.md")
    filing = text.split("## New instruction", 1)[1].split(
        "## Existing reference and first claim", 1
    )[0]
    _ordered(
        filing,
        f"{RESOLVER} --workflow dash --project PROJECT",
        'yoke dash "<specific title>" --project PROJECT --content-file /tmp/dash-instruction.txt '
        f"{ATTESTATION} --json",
    )

    # Escalation is its own phase file; the entrypoint only routes to it.
    escalation = _read("dash/escalate.md")
    _ordered(
        escalation,
        f"{RESOLVER} --workflow issue --project PROJECT",
        "Apply instructions; present grounded findings",
    )
    assert FUNCTION_ID in filing
    assert FUNCTION_ID in escalation


def test_idea_resolves_after_scope_selection_and_before_create() -> None:
    text = _read("idea/infer-and-create.md")
    resolution = text.split(
        "### c2. Resolve execution instructions before final authoring", 1
    )[1]
    _ordered(resolution, RESOLVER, "## 5. Create The Item")
    assert FUNCTION_ID in resolution
    assert "remains defense in depth" in resolution


def test_feed_resolves_each_materialized_item_before_create() -> None:
    text = _read("feed/materialize.md").split(
        "### 3A.2 Resolve The Filing Contract", 1
    )[1]
    _ordered(text, RESOLVER, "### 3A.3 Create via `/yoke idea`")
    assert FUNCTION_ID in text
    assert "/yoke idea --workflow ${_workflow}" in text


def test_curate_resolves_both_cluster_outputs_and_quick_promotion() -> None:
    cluster = _read("curate/cluster-and-work-item.md")
    filing = cluster.split("## 3. Validate and propose", 1)[1]
    _ordered(filing, RESOLVER, "## 4. Produce approved outputs")
    _ordered(
        filing,
        f"{RESOLVER} --workflow dash --project {{project}}",
        "yoke ouroboros field-note promote",
    )
    _ordered(
        filing,
        f"{RESOLVER} --workflow issue --project {{project}}",
        'yoke items create "{title}" issue',
    )

    router = _read("curate/SKILL.md")
    assert "[cluster-and-work-item.md](cluster-and-work-item.md)" in router
    quick = cluster
    _ordered(
        quick,
        f"{RESOLVER} --workflow dash --project {{project}}",
        "yoke ouroboros field-note promote",
    )
    assert FUNCTION_ID in filing
    assert quick.index(FUNCTION_ID) < quick.index(RESOLVER)


def test_onboard_and_conduct_resolve_before_seed_or_gap_filing() -> None:
    onboard = _read("onboard/seed-work.md")
    _ordered(
        onboard,
        f"{RESOLVER} --workflow issue --project {{project}}",
        'yoke items create "{title}" issue',
    )
    conduct = _read("conduct/simulation-gate-escalation.md")
    assert "[Idea](../idea/SKILL.md)" in conduct
    assert "exact target project" in conduct
    idea = _read("idea/infer-and-create.md")
    _ordered(idea, RESOLVER, "## 5. Create The Item")
    assert FUNCTION_ID in onboard
    assert FUNCTION_ID in idea


@pytest.mark.parametrize("recipe", FILING_RECIPES)
def test_every_filing_recipe_attests_the_resolved_instructions(recipe) -> None:
    text = _read(recipe)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("yoke items create", 'yoke dash "')) or (
            "$(yoke items create" in stripped
        ):
            assert ATTESTATION in stripped, (recipe, stripped)

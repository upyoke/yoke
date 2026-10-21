"""Agent filing recipes carry the execution-instructions attestation flag.

Every recipe that files through a non-web entry surface also carries the
attestation flag, because ``items.create`` refuses the filing without it
and no adapter sets it for the caller.
"""

from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
SKILLS = ROOT / ".agents" / "skills" / "yoke"
ATTESTATION = "--execution-instructions-considered"

#: Every recipe file whose filing command reaches ``items.create``
#: through a non-web entry surface.
FILING_RECIPES = (
    "dash/file-and-claim.md",
    "idea/infer-and-create.md",
    "curate/cluster-and-work-item.md",
    "conduct/simulation-gate-escalation.md",
    "feed/materialize.md",
)


def _read(relative: str) -> str:
    return (SKILLS / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize("recipe", FILING_RECIPES)
def test_every_filing_recipe_attests_the_resolved_instructions(recipe) -> None:
    text = _read(recipe)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(
            ("yoke items create", "yoke dash --title", "yoke task --title")
        ) or ("$(yoke items create" in stripped):
            assert ATTESTATION in stripped, (recipe, stripped)

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ONBOARD = ROOT / ".agents" / "skills" / "yoke" / "onboard"


def _read(name: str) -> str:
    return (ONBOARD / name).read_text(encoding="utf-8")


def test_execution_profile_names_pack_prerequisites_before_confirmation() -> None:
    text = _read("profile-and-scaffold.md")

    prerequisite = text.index("declared local\n  tool prerequisites")
    confirmation = text.index("### Confirm (stop 1 of 2)")

    assert prerequisite < confirmation
    assert "minimum version" in text
    assert "install\n  recipe" in text
    assert "yoke packs list --project {project} --json" in text


def test_onboarding_treats_pack_preview_as_the_pulumi_preflight() -> None:
    text = _read("hosting-and-environments.md")

    assert "preview is also the local-tool preflight" in text
    assert "`pulumi` prerequisite row with status `ready`" in text
    assert "named prerequisite code" in text
    assert "--allow-missing-tools" in text
    assert "explicitly confirmed" in text

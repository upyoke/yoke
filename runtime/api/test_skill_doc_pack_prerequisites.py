from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ONBOARD = ROOT / ".agents" / "skills" / "yoke" / "onboard"


def _read(name: str) -> str:
    return (ONBOARD / name).read_text(encoding="utf-8")


def test_execution_profile_names_pack_prerequisites_before_confirmation() -> None:
    text = _read("profile-and-scaffold.md")

    prerequisite = text.index("Packs and their tool prerequisites")
    confirmation = text.index("Stop 1: no writes before the operator confirms.")

    assert prerequisite < confirmation


def test_missing_tool_bypass_needs_the_confirmed_profile() -> None:
    text = " ".join(_read("profile-and-scaffold.md").split())

    assert (
        "Use `--allow-missing-tools` only when the confirmed profile asks for it."
        in text
    )

"""Steering discovery surfaces agree on optional strategy document defaults."""

from runtime.api.skill_doc_regressions_test_helpers import REPO, _read


class TestNearTermPlanDefaultAcrossTeachingSurfaces:
    """Router, help, command reference, and packet teach the same default."""

    SURFACES = (
        REPO / ".agents" / "skills" / "yoke" / "SKILL.md",
        REPO / ".agents" / "skills" / "yoke" / "help" / "SKILL.md",
        REPO / "docs" / "public" / "reference" / "commands.md",
        REPO / ".yoke" / "docs" / "reference" / "commands.md",
        REPO / "docs" / "harness-bootstrap.md",
        REPO
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "domain"
        / "schema_api_context_commands_claims.py",
    )

    def test_no_surface_still_calls_the_strategy_doc_required(self):
        for path in self.SURFACES:
            text = " ".join(_read(path).split())
            assert "required strategy doc" not in text, path
            assert "a strategy doc is required" not in text, path

    def test_every_surface_names_the_default(self):
        for path in self.SURFACES:
            assert "CURRENT-PLAN" in _read(path), path

"""Doc regression for the strategize skill — ports ``test-strategize.sh``."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import SKILLS


# ---------------------------------------------------------------------------
# TestStrategize — test-strategize.sh
# ---------------------------------------------------------------------------


class TestStrategize:
    """Strategize entry surface must keep its phase files."""

    STRATEGIZE_DIR = SKILLS / "strategize"

    def test_strategize_skill_exists(self):
        assert (self.STRATEGIZE_DIR / "SKILL.md").is_file()

    def test_strategize_phase_files_present(self):
        """Strategize is decomposed into phase sub-files; at least one must exist."""
        skill_dir = self.STRATEGIZE_DIR
        assert skill_dir.is_dir()
        phase_files = [
            p for p in skill_dir.iterdir() if p.suffix == ".md" and p.name != "SKILL.md"
        ]
        assert phase_files, (
            "strategize/ must contain at least one phase sub-file "
            "(research / propose / approve)"
        )

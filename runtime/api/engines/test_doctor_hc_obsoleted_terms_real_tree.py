"""Live-tree cleanliness coverage for the retired-term scanner."""

from yoke_project_checks.check_obsoleted_terms import scan_repo
from .test_doctor_hc_obsoleted_terms_scan import REPO


def test_scan_repo_clean_on_real_main():
    """The live repo has no retired-term residue in any scanned
    surface. The widened scanner (``.py`` under ``runtime/`` plus slash-form
    normalisation) reports zero hits on main."""
    hits = scan_repo(REPO)
    assert hits == [], (
        "Live repo has retired-term residue. Fix the offending file or add "
        "a justified allow-list entry to doctor_hc_obsoleted_terms_allowlists.\n"
        + "\n".join(hits[:20])
    )

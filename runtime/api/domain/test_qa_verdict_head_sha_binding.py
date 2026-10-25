"""QA summaries disclose the scope of their proof reading."""

from yoke_core.domain.qa_gate_summary import _format_text


def test_gate_summary_text_discloses_that_it_skips_tree_freshness():
    text = _format_text(
        {
            "target": "YOK-1",
            "transition": "reviewed-implementation",
            "qa_tables_present": True,
            "no_requirements": False,
            "satisfied": True,
            "blocking_unsatisfied_count": 0,
            "browser_unsatisfied_count": 0,
            "e2e_unsatisfied_count": 0,
            "tree_freshness_checked": False,
            "requirements": [],
        }
    )

    assert "Tree freshness: not evaluated here" in text

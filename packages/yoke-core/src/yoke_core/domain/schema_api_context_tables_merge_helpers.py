"""Merge verification helper owners and diagnosed import mistakes."""

from __future__ import annotations


MERGE_HELPER_TABLES: dict[str, dict] = {
    "yoke_core.domain.qa_case_ci_entry_run": {
        "columns": [("prepare_ci_lane", "callable"), ("base_branch", "callable")],
        "notes": (
            "CI entry-run preparation stays in this domain module. Wrong guess: "
            "moving lane_base_update into engines also moves qa_case_ci_entry_run. "
            "Split combined imports so the lane updater and CI entry reader keep "
            "their own owners; watch_pytest_lane imports both."
        ),
    },
    "yoke_core.domain.qa_case_ci_covering_run": {
        "columns": [("find_run_for_tree", "callable"), ("classify", "callable")],
        "notes": (
            "Covering-run lookup stays in this domain module. Wrong guess: "
            "moving lane_base_update into engines also moves qa_case_ci_covering_run. "
            "Split combined imports, including the CI entry-run test consumer."
        ),
    },
}

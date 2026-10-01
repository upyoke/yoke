"""CI workflow readers selected when their non-Python subjects change."""

from __future__ import annotations


CI_WORKFLOW_CONTRACTS = (
    (
        "browser_runtime_workflow_contract",
        frozenset(
            {
                ".github/workflows/browser-runtime-tests.yml",
                ".github/workflows/yoke-ci.yml",
            }
        ),
        ("runtime/api/test_yoke_ci_browser_runtime.py",),
    ),
)

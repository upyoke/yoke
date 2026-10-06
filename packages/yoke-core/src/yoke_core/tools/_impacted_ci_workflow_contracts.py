"""CI workflow readers selected when their non-Python subjects change."""

from __future__ import annotations


CI_WORKFLOW_CONTRACTS = (
    (
        "workflow_concurrency_contract",
        frozenset(
            {
                ".github/workflows/yoke-ci.yml",
                ".github/workflows/yoke-release.yml",
                ".github/workflows/yoke-server-image.yml",
            }
        ),
        ("runtime/api/domain/test_ci_workflow_concurrency.py",),
    ),
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

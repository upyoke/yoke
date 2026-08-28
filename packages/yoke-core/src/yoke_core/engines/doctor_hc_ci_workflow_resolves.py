"""Doctor HC — a declared CI workflow file resolves in the project checkout.

``HC-projects-ci-workflow-resolves`` WARNs when a ``ci_workflow_file``
capability names a file that is absent from ``.github/workflows/`` on a
host that holds that project's checkout. The sibling configured-check
only asks whether a row exists; this one asks whether the named file
does. Empty ``workflow_file`` stays undeclared. A host without a mapped
checkout reports nothing — the declaration is unverified, not wrong.
"""

from __future__ import annotations

from yoke_core.domain.ci_workflow_declaration_reconcile import (
    STATUS_MISSING,
    reconcile_ci_workflow_declarations,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _table_exists,
)


CHECK_ID = "projects-ci-workflow-resolves"
CHECK_NAME = "Declared CI workflow resolves in checkout"


def hc_ci_workflow_declaration_resolves(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """HC-projects-ci-workflow-resolves."""
    if not (
        _table_exists(conn, "projects") and _table_exists(conn, "project_capabilities")
    ):
        return

    results = reconcile_ci_workflow_declarations(conn)
    missing = [row for row in results if row["status"] == STATUS_MISSING]
    if not missing:
        rec.record(
            CHECK_ID,
            CHECK_NAME,
            "PASS",
            "Every declared ci_workflow_file that this host can inspect "
            "resolves under .github/workflows/.",
        )
        return

    lines = [
        (
            f"{row['slug']}: declared workflow {row['workflow_file']!r} "
            f"is missing from the checkout"
            + (f" ({row['github_repo']})" if row["github_repo"] else "")
            + "."
        )
        for row in missing
    ]
    rec.record(
        CHECK_ID,
        CHECK_NAME,
        "WARN",
        "Declared ci_workflow_file does not resolve:\n  "
        + "\n  ".join(lines)
        + "\n  Create the workflow under .github/workflows/, or correct "
        "the project's ci_workflow_file declaration.",
    )


__all__ = [
    "CHECK_ID",
    "CHECK_NAME",
    "hc_ci_workflow_declaration_resolves",
]

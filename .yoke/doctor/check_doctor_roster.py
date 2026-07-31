"""Health checks over Yoke's own doctor roster.

These are source-dev invariants about the engine this project builds, not
statements about any project the engine is pointed at, so they live with the
project instead of shipping to every install.
"""

from __future__ import annotations

from yoke_core.engines.doctor_applicability import (
    CheckApplicability,
    PROJECT_SCOPE_SELF,
)
from yoke_core.engines.doctor_applicability_declarations import undeclared_slugs
from yoke_core.engines.doctor_registry import HEALTH_CHECKS

APPLICABILITY = CheckApplicability(
    project_scope=PROJECT_SCOPE_SELF, requires_source_checkout=True,
)


def hc_doctor_applicability_declaration(conn, args, rec) -> None:
    """Every engine check declares what it applies to."""
    check_id = "HC-doctor-applicability-declaration"
    name = "Every engine check declares what it applies to"
    missing = undeclared_slugs(hc.slug for hc in HEALTH_CHECKS)
    if not missing:
        rec.record(
            check_id, name, "PASS",
            f"{len(HEALTH_CHECKS)} checks declared",
        )
        return
    rec.record(
        check_id, name, "FAIL",
        f"{len(missing)} registered check(s) have no applicability "
        "declaration and fall back to running everywhere:\n"
        + "\n".join(f"  - {slug}" for slug in missing)
        + "\n  Remediation: add each slug to a shape group in "
        "`doctor_applicability_declarations._SHAPES`. A check that reads a "
        "source tree belongs in `_SRC` or `_SELF`; one that needs a "
        "capability belongs in a capability shape. Declaring it universal "
        "is a decision, not a default.",
    )

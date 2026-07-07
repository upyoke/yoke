"""HC-skill-recipe-execution — smoke-dispatch every yoke CLI recipe.

Wraps the verify_skill_recipes harness inside a doctor health check.
Two modes:

* ``args.quick=True`` — sample up to 30 recipes (first three of each
  parent directory) so the doctor stays under its quick-mode budget.
* ``args.quick=False`` (full mode) — every recipe found in the skill
  tree.

Result mapping:

* No recipes inspected (skill bodies not yet translated) → PASS with
  an informational note.
* All inspected recipes pass → PASS.
* Any failure → FAIL with the first three failures named in the detail.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.tools.verify_skill_recipes import (
    RecipeVerdict, count_recipes, verify_skill_root,
)


_QUICK_PER_DIRECTORY = 3
_DEFAULT_HC_NAME = "HC-skill-recipe-execution"
_DEFAULT_HC_DESCRIPTION = "Skill-body recipes smoke-dispatch through yoke CLI"


def _resolve_skill_root(args: DoctorArgs) -> Optional[Path]:
    override = os.environ.get("YOKE_SKILL_ROOT")
    if override:
        candidate = Path(override)
        return candidate if candidate.is_dir() else None
    from yoke_core.api.repo_root import find_repo_root

    try:
        repo_root = find_repo_root(Path(__file__))
    except RuntimeError:
        return None
    candidate = repo_root / ".agents" / "skills" / "yoke"
    if candidate.is_dir():
        return candidate
    return None


def _format_failures(verdicts: List[RecipeVerdict]) -> str:
    failures = [v for v in verdicts if not v.ok]
    if not failures:
        return ""
    head = failures[:3]
    lines = []
    for verdict in head:
        loc = f"{verdict.file}:{verdict.line_number}"
        lines.append(f"{loc} - {verdict.recipe}")
        if verdict.error:
            lines.append(f"  {verdict.error}")
    suffix = ""
    if len(failures) > len(head):
        suffix = f"\n(+{len(failures) - len(head)} more)"
    return "\n".join(lines) + suffix


def hc_skill_recipe_execution(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Run the verify_skill_recipes harness against the live skill tree."""
    skill_root = _resolve_skill_root(args)
    if skill_root is None:
        rec.record(
            _DEFAULT_HC_NAME, _DEFAULT_HC_DESCRIPTION, "PASS",
            "skill root not found; HC self-skipped",
        )
        return
    try:
        total_count = count_recipes(skill_root)
        verdicts = verify_skill_root(
            skill_root,
            quick_per_directory=_QUICK_PER_DIRECTORY if args.quick else None,
        )
    except Exception as exc:
        rec.record(
            _DEFAULT_HC_NAME, _DEFAULT_HC_DESCRIPTION, "FAIL",
            f"verify_skill_root raised: {type(exc).__name__}: {exc}",
        )
        return

    if args.quick:
        inspected = verdicts
        scope_label = f"quick sample ({len(inspected)} of {total_count} total recipes)"
    else:
        inspected = verdicts
        scope_label = f"full sweep ({len(inspected)} recipes)"

    if not inspected:
        rec.record(
            _DEFAULT_HC_NAME, _DEFAULT_HC_DESCRIPTION, "PASS",
            "no yoke <subcommand> recipes found in skill bodies; "
            "skill-recipe translation populates this HC",
        )
        return

    failure_detail = _format_failures(inspected)
    if failure_detail:
        rec.record(
            _DEFAULT_HC_NAME, _DEFAULT_HC_DESCRIPTION, "FAIL",
            f"{scope_label}\n{failure_detail}",
        )
    else:
        rec.record(
            _DEFAULT_HC_NAME, _DEFAULT_HC_DESCRIPTION, "PASS",
            f"{scope_label}; every recipe parsed + resolved + dispatched cleanly",
        )


__all__ = ["hc_skill_recipe_execution"]

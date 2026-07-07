"""Create / update the canonical Yoke lifecycle labels on a project's GitHub repo.

Idempotent: each label is POSTed; on 422 (already exists) the helper
PATCHes to converge color + description. Invoke it when a project's
GitHub labels need convergence; it reads colors from the project-local
``.yoke/labels`` policy seeded by ``yoke project install`` so operators can
override the default palette without editing this file.

Usage:
    python3 -m yoke_core.tools.init_canonical_labels --project yoke

Exit 0 on success (every label converged). Exit non-zero on auth
failure or unexpected transport error; per-label failures are reported
individually but do not abort the loop.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from yoke_contracts.project_contract.label_policy import read_labels_file
from yoke_core.domain import project_label_policy
from yoke_core.domain.backlog_github_label_sync_rest import ensure_label
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


# (name, description, policy-key, default-color)
_CANONICAL_LABELS = (
    ("status:idea",                       "Backlog item — raw capture",                       "label_color_status_idea",                       "D4C5F9"),
    ("status:refining-idea",              "Backlog item — idea under refinement",             "label_color_status_refining_idea",              "C5DEF5"),
    ("status:refined-idea",               "Backlog item — refined and ready for next routing","label_color_status_refined_idea",               "BFD4F2"),
    ("status:planning",                   "Epic — planning in progress",                       "label_color_status_planning",                   "A2EEEF"),
    ("status:refining-plan",              "Epic — technical plan under refinement",            "label_color_status_refining_plan",              "7FDBCA"),
    ("status:planned",                    "Epic — planned and ready for implementation",       "label_color_status_planned",                    "7FDBCA"),
    ("status:implementing",               "Backlog item — implementation in progress",         "label_color_status_implementing",               "0E8A16"),
    ("status:reviewing-implementation",   "Backlog item — implementation under review",        "label_color_status_reviewing_implementation",   "FBCA04"),
    ("status:reviewed-implementation",    "Backlog item — review complete",                    "label_color_status_reviewed_implementation",    "FEF2C0"),
    ("status:polishing-implementation",   "Backlog item — finishing pass in progress",         "label_color_status_polishing_implementation",   "5319E7"),
    ("status:implemented",                "Backlog item — implementation complete",            "label_color_status_implemented",                "0E8A16"),
    ("status:release",                    "Backlog item — in release/deploy flow",             "label_color_status_release",                    "6F42C1"),
    ("status:done",                       "Backlog item — finished",                           "label_color_status_done",                       "0E8A16"),
    ("status:failed",                     "Backlog item — failed",                             "label_color_status_failed",                     "D93F0B"),
    ("status:blocked",                    "Backlog item — blocked",                            "label_color_blocked",                           "B60205"),
    ("status:stopped",                    "Backlog item — stopped",                            "label_color_status_stopped",                    "E4E669"),
    ("status:cancelled",                  "Backlog item — cancelled",                          "label_color_status_cancelled",                  "BFD4F2"),
    ("type:epic",                         "Backlog item — epic",                               "label_color_type_epic",                         "5319E7"),
    ("type:task",                         "Backlog item — task",                               "label_color_type_task",                         "0E8A16"),
    ("type:integration-fix",              "Backlog item — integration fix",                    "label_color_type_integration_fix",              "D93F0B"),
    ("type:issue",                        "Backlog item — issue",                              "label_color_type_issue",                        "1D76DB"),
)


def _project_label_overrides() -> dict:
    """Read the target project's ``.yoke/labels`` overrides (operator tool runs
    in a checkout). Honors the explicit target-repo anchor used by cross-project
    label convergence; empty when no anchored checkout."""
    for key in (
        "YOKE_TARGET_REPO_ROOT",
        "CLAUDE_PROJECT_DIR",
        "CODEX_PROJECT_DIR",
        "YOKE_REPO_ROOT",
    ):
        root = (os.environ.get(key) or "").strip()
        if root:
            return read_labels_file(Path(root) / ".yoke" / "labels")
    return {}


def run(project: str) -> int:
    try:
        auth = resolve_project_github_auth(project)
    except ProjectGithubAuthError as exc:
        print(f"Error: cannot resolve GitHub auth for project '{project}': {exc}", file=sys.stderr)
        return 2

    overrides = _project_label_overrides()
    fail_count = 0
    for name, description, settings_key, default_color in _CANONICAL_LABELS:
        color = project_label_policy.get_color(
            settings_key, default_color, overrides=overrides
        )
        try:
            ensure_label(
                name, color, auth.repo,
                token=auth.token, description=description,
            )
            print(f"  ensured: {name}")
        except RestTransportError as exc:
            fail_count += 1
            print(f"  FAILED: {name}: {exc}", file=sys.stderr)

    if fail_count:
        print(f"\n{fail_count} label(s) failed to converge.", file=sys.stderr)
        return 1
    print(f"\nAll {len(_CANONICAL_LABELS)} canonical labels ensured on {auth.repo}.")
    return 0


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="init-canonical-labels",
        description="Create / update Yoke canonical lifecycle labels via REST",
    )
    parser.add_argument("--project", default="yoke")
    args = parser.parse_args(argv)
    sys.exit(run(args.project))


if __name__ == "__main__":
    main()

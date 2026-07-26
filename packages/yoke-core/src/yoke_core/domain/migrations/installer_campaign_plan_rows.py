"""Replace the Markdown installer catalog with one executable QA plan."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.schema_common import _table_exists


MIGRATION_NAME = "installer_campaign_plan_rows"
PLAN_SLUG = "installer-campaign"
EXPECTED_CASE_KEYS = (
    "cold-start-hosted",
    "cold-start-local",
    "hosted-connect",
    "path-repair",
    "welcome-frame",
    "connect-wait",
    "review-frame",
    "path-on-shell",
    "token-perms",
    "universe-born",
)
HOST_BASELINES = ["fresh-host", "shell-preconfigured"]
PUBLIC_INSTALL = "curl -fsSL https://upyoke.com/install | sh"


def _terminal_case(
    position: int,
    key: str,
    *,
    entry_surface: str,
    checkpoint: str,
    expect: str,
    expected: str,
    baselines: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "position": position,
        "case_key": key,
        "method_id": "terminal-check",
        "instructions": (
            f"Start at `{entry_surface}` on the Test Mac and reach the "
            f"`{checkpoint}` checkpoint without bypassing its parent process."
        ),
        "expected_outcome": expected,
        "method_config": {
            "steps": [{"key": checkpoint, "expect": expect}],
            "capture_checkpoints": [checkpoint],
        },
        "host_baselines": baselines or [],
        "entry_surface": entry_surface,
        "required_completion": checkpoint,
    }


def _inspection_case(
    position: int,
    key: str,
    *,
    checkpoint: str,
    expect: str,
    expected: str,
) -> dict[str, Any]:
    return {
        "position": position,
        "case_key": key,
        "method_id": "terminal-inspection",
        "instructions": (
            f"Drive `{PUBLIC_INSTALL}` to `{checkpoint}` and retain paired "
            "text and real Terminal evidence."
        ),
        "expected_outcome": expected,
        "method_config": {
            "steps": [{"key": checkpoint, "expect": expect}],
            "capture_checkpoints": [checkpoint],
        },
        "host_baselines": [],
        "entry_surface": PUBLIC_INSTALL,
        "required_completion": checkpoint,
    }


def _state_case(
    position: int,
    key: str,
    *,
    command: str,
    expected: str,
    baselines: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "position": position,
        "case_key": key,
        "method_id": "machine-state-check",
        "instructions": "Assert the installed host state through host_control.",
        "expected_outcome": expected,
        "method_config": {
            "assertions": [{"argv": ["/bin/sh", "-c", command]}],
        },
        "host_baselines": baselines or [],
        "entry_surface": None,
        "required_completion": None,
    }


INSTALLER_CAMPAIGN_CASES = (
    _terminal_case(
        1,
        "cold-start-hosted",
        entry_surface=PUBLIC_INSTALL,
        checkpoint="install-ready",
        expect="Yoke v",
        expected=(
            "The hosted installer reaches the installed-and-ready handoff "
            "under both supported PATH starting states."
        ),
        baselines=HOST_BASELINES,
    ),
    _terminal_case(
        2,
        "cold-start-local",
        entry_surface=PUBLIC_INSTALL,
        checkpoint="destination",
        expect="Where should this Yoke live?",
        expected="A clean install reaches the local-universe destination choice.",
    ),
    _terminal_case(
        3,
        "hosted-connect",
        entry_surface="yoke connect",
        checkpoint="approval-wait",
        expect="Waiting for browser approval",
        expected=(
            "Hosted connect reaches the browser-approval wait without exposing "
            "the resulting machine credential."
        ),
    ),
    _terminal_case(
        4,
        "path-repair",
        entry_surface="yoke path",
        checkpoint="path-choice",
        expect="Add it",
        expected=(
            "PATH repair names the exact product-derived startup-file change "
            "and offers a safe apply choice."
        ),
    ),
    _inspection_case(
        5,
        "welcome-frame",
        checkpoint="welcome",
        expect="Your operating system for software delivery",
        expected="The installer welcome frame matches the approved Terminal UX.",
    ),
    _inspection_case(
        6,
        "connect-wait",
        checkpoint="connect-wait",
        expect="Waiting for browser approval",
        expected=(
            "The hosted connection wait clearly sends the operator to the "
            "browser while keeping credential values out of the frame."
        ),
    ),
    _inspection_case(
        7,
        "review-frame",
        checkpoint="review",
        expect="Review",
        expected=(
            "The onboarding review frame groups every pending write before apply."
        ),
    ),
    _state_case(
        8,
        "path-on-shell",
        command='command -v yoke >/dev/null && test -n "$PATH"',
        expected=(
            "A fresh login shell resolves Yoke after installation under both "
            "declared starting states."
        ),
        baselines=HOST_BASELINES,
    ),
    _state_case(
        9,
        "token-perms",
        command=(
            'root="$HOME/.yoke/secrets"; test -d "$root"; '
            'test "$(stat -f %Lp "$root")" = 700'
        ),
        expected="The machine secret root exists with owner-only permissions.",
    ),
    _state_case(
        10,
        "universe-born",
        command=(
            'test -f "$HOME/.yoke/config.json"; '
            'yoke status >/dev/null'
        ),
        expected=(
            "The machine has a persisted universe connection and its active "
            "authority answers the registered status probe."
        ),
    ),
)


def apply(conn: Any) -> None:
    """Create or replace yoke's project-owned installer campaign."""
    required = (
        "projects",
        "qa_methods",
        "qa_plans",
        "qa_plan_cases",
    )
    missing = [table for table in required if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "installer campaign requires deployed QA tables: "
            + ", ".join(missing)
        )
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    project = conn.execute(
        "SELECT id FROM projects WHERE slug='yoke'"
    ).fetchone()
    if project is None:
        raise RuntimeError("installer campaign requires project 'yoke'")
    row = conn.execute(
        f"SELECT id FROM qa_plans WHERE project_id={marker} AND slug={marker}",
        (int(project[0]), PLAN_SLUG),
    ).fetchone()
    if row is None:
        created = create_plan(
            conn,
            project="yoke",
            slug=PLAN_SLUG,
            name="Installer campaign",
            description=(
                "Physical Test Mac proof for installer interaction, Terminal "
                "presentation, and post-install machine state."
            ),
        )
        plan_id = int(created["id"])
    else:
        plan_id = int(row[0])
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[dict(case) for case in INSTALLER_CAMPAIGN_CASES],
    )


def invariants(conn: Any) -> None:
    """Require one ten-case plan and twelve baseline-expanded requirements."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT c.case_key,c.method_id,c.host_baselines,c.entry_surface,"
        "c.required_completion "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "JOIN projects pr ON pr.id=p.project_id "
        f"WHERE pr.slug='yoke' AND p.slug={marker} ORDER BY c.position",
        (PLAN_SLUG,),
    ).fetchall()
    keys = tuple(str(row[0]) for row in rows)
    if keys != EXPECTED_CASE_KEYS:
        raise AssertionError(
            f"installer campaign case order differs: {keys!r}"
        )
    methods = [str(row[1]) for row in rows]
    if methods.count("terminal-check") != 4:
        raise AssertionError("installer campaign needs four Terminal checks")
    if methods.count("terminal-inspection") != 3:
        raise AssertionError("installer campaign needs three Terminal inspections")
    if methods.count("machine-state-check") != 3:
        raise AssertionError("installer campaign needs three machine-state checks")
    expanded_count = sum(
        max(1, len(json.loads(str(row[2] or "[]"))))
        for row in rows
    )
    if expanded_count != 12:
        raise AssertionError(
            f"installer campaign expands to {expanded_count}, expected 12"
        )
    if any(
        str(row[1]).startswith("terminal-") and (not row[3] or not row[4])
        for row in rows
    ):
        raise AssertionError(
            "every Terminal case declares entry surface and completion"
        )


__all__ = [
    "EXPECTED_CASE_KEYS",
    "HOST_BASELINES",
    "INSTALLER_CAMPAIGN_CASES",
    "MIGRATION_NAME",
    "PLAN_SLUG",
    "apply",
    "invariants",
]

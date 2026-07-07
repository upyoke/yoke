"""Refine-time dry-run validator for ``db_compatibility_attestation.rehearsal_commands``.

Parses each command for shape defects against the worktree filesystem
without executing it. The pure read-and-dry-run contract ("does not
modify any DB row, lease, or path-claim") is satisfied by construction:
the validator never spawns a subprocess, never connects to the control
plane, never touches the lease table. The known rehearsal failure modes
(literal ``<worktree>`` placeholder; wrong-path pytest argument) are
both path-existence failures and detect cleanly via shlex + os.path —
the executing-validator's "extra depth" was reproducing what the
production runner already does at implementation entry.

Detection shape — each command is :func:`shlex.split` and every token
is checked for:

* ``<...>`` substrings — operator placeholders the spec author never
  substituted (failure_reason ``unresolved_placeholder``);
* file-path tokens (``\\w./-`` + a recognised extension) whose target
  does not exist relative to the repo root unless the path is an exact
  planned path-claim target for the item (failure_reason
  ``missing_path``);
* shlex parse errors — unbalanced quotes that would also break shell
  execution (failure_reason ``shell_parse_error``).

Short-circuits — the validator returns an empty list (no work, no
side effects) when:

* ``items.db_mutation_profile.state != "declared"``,
* ``items.db_compatibility_attestation`` is absent / unparseable,
* the attestation's ``frozen_at`` is unset, or
* ``rehearsal_commands`` is empty.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_compatibility_attestation import (
    _safe_parse_dict as _parse_attestation,
)
from yoke_core.domain.db_mutation_profile import (
    STATE_DECLARED as _PROFILE_STATE_DECLARED,
)


ATTESTATION_REHEARSAL_COMMAND_FAILED = "ATTESTATION_REHEARSAL_COMMAND_FAILED"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"

# Operator placeholders that survived refine (e.g. ``<worktree>``) — the
# production runner can't substitute them and the shell either treats
# the `<` as redirection or carries the literal through to argv.
_PLACEHOLDER_RE = re.compile(r"<[^>\s]+>")

# Path-shaped tokens we'll stat. Restricted to recognised extensions so
# we don't false-positive on Python source strings (``-c "..."``) or
# dotted module references (``yoke_core.domain.x``).
_PATH_TOKEN_RE = re.compile(
    r"^[\w./\-]+\.(py|md|json|yaml|yml|toml|sql|txt|cfg|ini)$",
)

# Refine-time guard against the recursive self-call shape. The
# governed-migration runner (``migration_apply_rehearse._rehearse_inner``)
# re-executes every entry in ``rehearsal_commands`` as a child process
# against the validation surface — a child that itself invokes
# ``migration_apply rehearse|live-apply`` would recurse into the same
# runner with the validation authority bound, where the items
# row that named the command does not exist. The result is a confusing
# ``Item YOK-N not found`` failure deep in the runner. The rehearsal
# command must instead exercise the module's own surface (a focused
# pytest run, a schema probe, etc.).
_RECURSIVE_MIGRATION_APPLY_RE = re.compile(
    r"yoke_core\.domain\.migration_apply\s+(rehearse|live-apply)\b"
)


@dataclass
class ValidationOutcome:
    """One shape-check result per ``rehearsal_commands`` entry."""

    command: str
    passed: bool
    failure_reason: str = ""
    failure_token: str = ""


def _read_profile(conn: Any, item_id: int) -> Optional[Dict[str, Any]]:
    p = _p(conn)
    try:
        row = conn.execute(
            f"SELECT db_mutation_profile FROM items WHERE id = {p}", (item_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn=conn):
        return None
    if row is None or row[0] is None:
        return None
    return _parse_attestation(row[0])


def _read_attestation(
    conn: Any, item_id: int,
) -> Optional[Dict[str, Any]]:
    p = _p(conn)
    try:
        row = conn.execute(
            f"SELECT db_compatibility_attestation FROM items WHERE id = {p}",
            (item_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn=conn):
        return None
    if row is None or row[0] is None:
        return None
    return _parse_attestation(row[0])


def _resolve_repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return Path.cwd()


def _planned_claim_paths(conn: Any, item_id: int) -> Set[str]:
    p = _p(conn)
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT pt.path_string
            FROM path_claims pc
            JOIN path_claim_targets pct ON pct.claim_id = pc.id
            JOIN path_targets pt ON pt.id = pct.target_id
            WHERE pc.item_id = {p}
              AND pc.state IN ('planned', 'blocked', 'active')
              AND pt.materialization_state = 'planned'
            """,
            (item_id,),
        ).fetchall()
    except db_backend.operational_error_types(conn=conn):
        return set()
    return {str(row[0]) for row in rows if row[0]}


def _repo_relative_token(token: str) -> str:
    return token[2:] if token.startswith("./") else token


def _check_command_shape(
    command: str, repo_root: Path, planned_paths: Optional[Set[str]] = None,
) -> Optional[Tuple[str, str]]:
    """Return ``(failure_reason, failure_token)`` or ``None`` for PASS.

    Check order is: shell_parse_error -> per-token (unresolved_placeholder
    -> missing_path) -> recursive_migration_apply_self_call. Operator-
    actionable defects (typo'd path, un-substituted placeholder) surface
    before the semantic recursive-shape check so the matching remediation
    advice is the most specific one available.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return ("shell_parse_error", command)
    for token in tokens:
        if _PLACEHOLDER_RE.search(token):
            return ("unresolved_placeholder", token)
        if _PATH_TOKEN_RE.match(token):
            if not (repo_root / token).exists():
                rel_token = _repo_relative_token(token)
                if planned_paths and rel_token in planned_paths:
                    continue
                return ("missing_path", token)
    if _RECURSIVE_MIGRATION_APPLY_RE.search(command):
        return ("recursive_migration_apply_self_call", command)
    return None


def validate_attestation_rehearsal_commands(
    conn: Any, item_id: int,
) -> List[ValidationOutcome]:
    """Parse-and-stat every ``rehearsal_commands`` entry.

    Returns one :class:`ValidationOutcome` per command. An empty list
    means "no governed mutation declared, or nothing to validate" —
    callers treat that as PASS without further action.
    """
    profile = _read_profile(conn, item_id)
    if not profile or profile.get("state") != _PROFILE_STATE_DECLARED:
        return []

    attestation = _read_attestation(conn, item_id)
    if not attestation:
        return []
    if not attestation.get("frozen_at"):
        return []
    commands = attestation.get("rehearsal_commands") or []
    if not commands:
        return []

    repo_root = _resolve_repo_root()
    planned_paths = _planned_claim_paths(conn, item_id)
    results: List[ValidationOutcome] = []
    for cmd in commands:
        failure = _check_command_shape(str(cmd), repo_root, planned_paths)
        if failure is None:
            results.append(ValidationOutcome(command=str(cmd), passed=True))
            continue
        reason, token = failure
        results.append(ValidationOutcome(
            command=str(cmd), passed=False,
            failure_reason=reason, failure_token=token,
        ))
    return results


_FAILURE_MESSAGE_PREFIX = {
    "unresolved_placeholder": (
        "rehearsal command contains unresolved placeholder"
    ),
    "missing_path": "rehearsal command references missing path",
    "shell_parse_error": "rehearsal command fails to shell-parse",
    "recursive_migration_apply_self_call": (
        "rehearsal command re-invokes migration_apply rehearse/live-apply "
        "(runner would recurse into itself against the validation surface)"
    ),
}


def issue_payloads_for_item(
    conn: Any, item_id: int,
) -> List[Dict[str, Any]]:
    """Return one ``Issue``-shaped dict per failing rehearsal command."""
    payloads: List[Dict[str, Any]] = []
    for outcome in validate_attestation_rehearsal_commands(conn, item_id):
        if outcome.passed:
            continue
        prefix = _FAILURE_MESSAGE_PREFIX.get(
            outcome.failure_reason, "rehearsal command failed shape check",
        )
        payloads.append({
            "code": ATTESTATION_REHEARSAL_COMMAND_FAILED,
            "message": (
                f"{prefix} `{outcome.failure_token}`: {outcome.command}"
            ),
            "remediation": (
                "amend the attestation's rehearsal_commands via the "
                "db_claim.amend function id (CLI adapter: "
                "`python3 -m yoke_core.api.service_client db-claim-amend`) "
                "so each command shell-parses and every referenced "
                "in-repo path exists on the worktree"
            ),
            "context": {
                "command": outcome.command,
                "failure_reason": outcome.failure_reason,
                "failure_token": outcome.failure_token,
            },
        })
    return payloads


def verify_attestation_rehearsal_commands(conn: Any, item_id: int):
    """Thin facade that returns ``Issue`` rows for the readiness check.

    Lives here (not in :mod:`idea_readiness_check`) to keep the
    readiness file under its 350-line cap, which takes precedence
    over surface locality.
    Re-exported from :mod:`idea_readiness_check` for callers that
    expect the wrapper at its named location.
    """
    from yoke_core.domain.idea_readiness_check import Issue
    return [Issue(**p) for p in issue_payloads_for_item(conn, item_id)]


__all__ = [
    "ATTESTATION_REHEARSAL_COMMAND_FAILED",
    "ValidationOutcome",
    "issue_payloads_for_item",
    "validate_attestation_rehearsal_commands",
    "verify_attestation_rehearsal_commands",
]

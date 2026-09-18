"""Shape detection for ``db_compatibility_attestation.rehearsal_commands``.

The half of the rehearsal dry-run that reads nothing but the commands and
the tree they name: every token is parsed and stat-ed, never executed.
:mod:`attestation_rehearsal_dryrun` owns the other half — resolving which
commands an item declared — and the two are separate because the hosts
differ. A control plane holds the commands; only a machine with the item
project's checkout can stat the paths they reference.

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
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ATTESTATION_REHEARSAL_COMMAND_FAILED = "ATTESTATION_REHEARSAL_COMMAND_FAILED"

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
# migration rehearsal/apply command would recurse into the same
# runner with the validation authority bound, where the items
# row that named the command does not exist. The result is a confusing
# ``Item YOK-N not found`` failure deep in the runner. The rehearsal
# command must instead exercise the module's own surface (a focused
# pytest run, a schema probe, etc.).
_RECURSIVE_MIGRATION_APPLY_RE = re.compile(
    r"(?:yoke_core\.domain\.migration_apply|yoke\s+migration)"
    r"\s+(?:rehearse|live-apply)\b"
)

_FAILURE_MESSAGE_PREFIX = {
    "unresolved_placeholder": ("rehearsal command contains unresolved placeholder"),
    "missing_path": "rehearsal command references missing path",
    "shell_parse_error": "rehearsal command fails to shell-parse",
    "recursive_migration_apply_self_call": (
        "rehearsal command re-invokes migration rehearsal/apply "
        "(runner would recurse into itself against the validation surface)"
    ),
}


@dataclass
class ValidationOutcome:
    """One shape-check result per ``rehearsal_commands`` entry."""

    command: str
    passed: bool
    failure_reason: str = ""
    failure_token: str = ""


def _repo_relative_token(token: str) -> str:
    return token[2:] if token.startswith("./") else token


def check_command_shape(
    command: str,
    repo_root: Path,
    planned_paths: Optional[Set[str]] = None,
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


def validate_command_shapes(
    commands: List[str],
    *,
    repo_root: Path,
    planned_paths: Optional[Set[str]] = None,
) -> List[ValidationOutcome]:
    """Parse-and-stat already-resolved rehearsal commands against a tree."""
    results: List[ValidationOutcome] = []
    for cmd in commands:
        failure = check_command_shape(str(cmd), repo_root, planned_paths)
        if failure is None:
            results.append(ValidationOutcome(command=str(cmd), passed=True))
            continue
        reason, token = failure
        results.append(
            ValidationOutcome(
                command=str(cmd),
                passed=False,
                failure_reason=reason,
                failure_token=token,
            )
        )
    return results


def issue_payloads_for_commands(
    commands: List[str],
    *,
    repo_root: Path,
    planned_paths: Optional[Set[str]] = None,
    public_ref: str,
) -> List[Dict[str, Any]]:
    """Render failing-command issues without reading the control plane."""
    payloads: List[Dict[str, Any]] = []
    for outcome in validate_command_shapes(
        commands, repo_root=repo_root, planned_paths=planned_paths,
    ):
        if outcome.passed:
            continue
        prefix = _FAILURE_MESSAGE_PREFIX.get(
            outcome.failure_reason,
            "rehearsal command failed shape check",
        )
        payloads.append(
            {
                "code": ATTESTATION_REHEARSAL_COMMAND_FAILED,
                "message": (f"{prefix} `{outcome.failure_token}`: {outcome.command}"),
                "remediation": (
                    "amend the attestation's rehearsal_commands via the "
                    "db_claim.amend function id (CLI adapter: "
                    f'`yoke db-claim amend {public_ref} --reason "<why>" '
                    "--payload '<unified-claim-json>'`) "
                    "so each command shell-parses and every referenced "
                    "in-repo path exists on the worktree"
                ),
                "context": {
                    "command": outcome.command,
                    "failure_reason": outcome.failure_reason,
                    "failure_token": outcome.failure_token,
                },
            }
        )
    return payloads


__all__ = [
    "ATTESTATION_REHEARSAL_COMMAND_FAILED",
    "ValidationOutcome",
    "check_command_shape",
    "issue_payloads_for_commands",
    "validate_command_shapes",
]

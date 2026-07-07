"""Project test-command validation (render/display functions).

Extracted from ``yoke_core.domain.projects`` to keep the parent module
under 800 lines.  All public symbols are re-exported from the parent so
existing callers are unaffected.

Owner: ``yoke_core.domain.projects`` (orchestration layer).
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from yoke_core.domain import command_definitions as cmd_defs
from yoke_core.domain.db_helpers import connect, query_one
from yoke_core.domain.project_checkout_locations import checkout_for_project
from yoke_core.domain.project_identity import resolve_project


# ---------------------------------------------------------------------------
# validate-test-commands
# ---------------------------------------------------------------------------
#
# These helpers detect broken project test commands before they are handed to
# agents as authoritative.  The CLI output contract is ``project=<slug>`` header
# followed by ``<scope>=<status>|<detail>`` lines, one per canonical scope
# (``quick``, ``full``, ``e2e``, ``smoke``).  ``scope`` maps directly to the
# ``command_definitions`` family keyed_set entry key.

# Interpreter wrappers whose next token is expected to be a script path.
_INTERPRETER_WRAPPERS = ("sh", "bash", "python", "python3", "node")

# Package-manager commands that require a ``package.json`` in the effective cwd.
_PACKAGE_MANAGERS = ("npm", "npx", "yarn")

# Canonical output-line order for validator output.
# Order matches the four-tier test model:
#   quick = fast unit-ish suite, full = everything, e2e = real-deployment,
#   smoke = shallow real-stack checks.
_VALIDATION_SCOPES: Tuple[str, ...] = cmd_defs.SCOPES


@dataclass
class TestCommandResult:
    """Validation outcome for one ``command_definitions`` scope.

    The ``scope`` field is one of the canonical values exported from
    :mod:`yoke_core.domain.command_definitions`: ``quick``, ``full``,
    ``e2e``, ``smoke``.
    """

    # Prevent pytest from collecting this dataclass as a test class by name.
    __test__ = False

    scope: str
    status: str  # "valid" | "invalid" | "empty"
    detail: str  # human-readable reason when status != "valid"


def _split_command_chain(value: str) -> List[str]:
    """Split a chained command string on ``&&`` and ``;``, trimming each piece.

    Mirrors the shell owner's segmenting behavior so ``cd app && npm test`` is
    walked segment-by-segment with working-directory tracking between steps.
    """
    segments = re.split(r"\s*(?:&&|;)\s*", value)
    return [seg.strip() for seg in segments if seg.strip()]


def _resolve_under_cwd(path: str, cwd: str) -> str:
    """Resolve *path* against *cwd* unless it is already absolute."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))


def _validate_test_command(
    scope: str,
    value: Optional[str],
    repo_path: str,
) -> TestCommandResult:
    """Validate a command string for a single ``command_definitions`` scope.

    * Empty/null/whitespace-only ⇒ ``empty``.
    * Chained commands are split on ``&&`` and ``;`` and evaluated in order.
    * ``cd <dir>`` updates the effective working directory and fails if the
      target directory is missing.
    * ``python3 -m <module>`` / ``python -m <module>`` are valid when the
      interpreter itself is on ``PATH``; they do not require a script file.
    * ``sh/bash/python/python3/node <script>`` fail when the referenced script
      file is missing relative to the effective cwd.
    * ``npm``/``npx``/``yarn`` fail when the effective cwd has no
      ``package.json``.
    * Bare executables validate via ``PATH`` lookup or an executable file under
      the effective cwd.
    * The ``setup-venv.sh`` bootstrap allowance: after ``sh app/scripts/setup-venv.sh``
      succeeds, ``.venv/bin/python3`` relative to the enclosing app directory is
      treated as resolvable for later segments.
    """
    if value is None:
        return TestCommandResult(scope, "empty", "")
    stripped = value.strip()
    if not stripped or stripped == "null":
        return TestCommandResult(scope, "empty", "")

    cwd = repo_path
    synthetic_execs: List[str] = []

    for seg in _split_command_chain(stripped):
        tokens = seg.split()
        if not tokens:
            continue
        first = tokens[0]

        # cd <dir>
        if first == "cd":
            if len(tokens) < 2:
                return TestCommandResult(
                    scope, "invalid", "cd without target directory"
                )
            target = tokens[1]
            abs_dir = _resolve_under_cwd(target, cwd)
            if not os.path.isdir(abs_dir):
                return TestCommandResult(
                    scope, "invalid", f"directory not found: {target}"
                )
            cwd = abs_dir
            continue

        # python3 -m <module> / python -m <module>
        if first in ("python3", "python") and len(tokens) >= 3 and tokens[1] == "-m":
            if shutil.which(first) is None:
                return TestCommandResult(
                    scope, "invalid", f"executable not found: {first}"
                )
            continue

        # Interpreter wrappers that take a script argument.
        if first in _INTERPRETER_WRAPPERS and len(tokens) >= 2:
            script = tokens[1]
            abs_script = _resolve_under_cwd(script, cwd)
            if not os.path.isfile(abs_script):
                return TestCommandResult(
                    scope, "invalid", f"script not found: {script}"
                )
            if os.path.basename(abs_script) == "setup-venv.sh":
                # After setup-venv.sh runs, .venv/bin/python3 relative to the
                # app directory (one level above scripts/) is considered
                # available for downstream segments.
                app_dir = os.path.dirname(os.path.dirname(abs_script))
                synthetic_execs.append(
                    os.path.normpath(os.path.join(app_dir, ".venv/bin/python3"))
                )
            continue

        # Package managers require package.json in the effective cwd.
        if first in _PACKAGE_MANAGERS:
            if not os.path.isfile(os.path.join(cwd, "package.json")):
                return TestCommandResult(
                    scope, "invalid", f"no package.json in {cwd}"
                )
            continue

        # Generic executable resolution: PATH → cwd-relative file → synthetic.
        if shutil.which(first) is not None:
            continue
        abs_exec = _resolve_under_cwd(first, cwd)
        if os.path.isfile(abs_exec) and os.access(abs_exec, os.X_OK):
            continue
        if abs_exec in synthetic_execs:
            continue

        return TestCommandResult(
            scope, "invalid", f"executable not found: {first}"
        )

    return TestCommandResult(scope, "valid", "")


def validate_project_test_commands(
    project_id: str,
    db_path: Optional[str] = None,
) -> List[TestCommandResult]:
    """Validate every command_definitions scope for *project_id*.

    Raises:
        LookupError: when the project row does not exist.

    Returns results in canonical scope order (``quick``, ``full``, ``e2e``,
    ``smoke``). If this machine has no mapped checkout, every scope is
    reported as ``invalid`` with an actionable detail so the caller does not
    silently skip the project.
    """
    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project_id, required=True)
        assert ident is not None
        repo_path = str(checkout) if (
            checkout := checkout_for_project(conn, project_id)
        ) is not None else ""
        if not repo_path:
            detail = f"project '{project_id}' has no machine-local checkout mapping"
            return [TestCommandResult(s, "invalid", detail)
                    for s in _VALIDATION_SCOPES]
        if not os.path.isdir(repo_path):
            detail = (
                f"project '{project_id}' mapped checkout not a directory: {repo_path}"
            )
            return [TestCommandResult(s, "invalid", detail)
                    for s in _VALIDATION_SCOPES]
    finally:
        conn.close()

    commands = cmd_defs.list_commands(project_id, db_path=db_path)
    return [
        _validate_test_command(scope, commands.get(scope), repo_path)
        for scope in _VALIDATION_SCOPES
    ]


def format_validation_block(
    project_id: str,
    results: Sequence[TestCommandResult],
) -> str:
    """Format validation results using the canonical parseable contract.

    Output shape::

        project=<slug>
        <scope>=<status>|<detail>
        ...

    ``scope`` is one of ``quick``, ``full``, ``e2e``, ``smoke``.
    """
    lines = [f"project={project_id}"]
    for result in results:
        lines.append(f"{result.scope}={result.status}|{result.detail}")
    return "\n".join(lines)


def cmd_validate_test_commands(
    project_id: Optional[str] = None,
    all_projects: bool = False,
    db_path: Optional[str] = None,
) -> Tuple[str, int]:
    """Run the test-command validator.

    Returns (output, exit_code).  Exit code ``0`` means every reported field is
    ``valid`` or ``empty``; ``1`` means at least one field is ``invalid``.
    Usage errors are surfaced by raising ``ValueError`` (caller maps to 2).
    """
    from yoke_core.domain.db_helpers import connect as _connect, query_rows as _query_rows

    if all_projects and project_id:
        raise ValueError("validate-test-commands: pass <project-id> OR --all, not both")
    if not all_projects and not project_id:
        raise ValueError("validate-test-commands: missing <project-id> (or --all)")

    blocks: List[str] = []
    any_invalid = False

    if all_projects:
        conn = _connect(db_path)
        try:
            rows = _query_rows(conn, "SELECT slug FROM projects ORDER BY slug")
        finally:
            conn.close()
        for row in rows:
            pid = row["slug"]
            try:
                results = validate_project_test_commands(pid, db_path=db_path)
            except LookupError:
                continue
            blocks.append(format_validation_block(pid, results))
            if any(r.status == "invalid" for r in results):
                any_invalid = True
        return "\n".join(blocks), (1 if any_invalid else 0)

    assert project_id is not None  # guarded above
    results = validate_project_test_commands(project_id, db_path=db_path)
    output = format_validation_block(project_id, results)
    exit_code = 1 if any(r.status == "invalid" for r in results) else 0
    return output, exit_code

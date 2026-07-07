"""Shared helpers for the zero-shell-proof regression guards."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DOC = REPO_ROOT / "AGENTS.md"
CODEX_DOC = REPO_ROOT / "CODEX.md"
HOOK_PARITY_DOC = REPO_ROOT / "docs" / "hook-parity-map.md"
TEST_INVENTORY_DOC = REPO_ROOT / ".yoke" / "test-inventory.md"

API_ROOT = REPO_ROOT / "runtime" / "api"

# Phase D: regression guard for production-Python shell
# dispatch. The spec names three classes of offender that must never
# return to the production Python surface:
#
#   1. Direct ``subprocess.run(["sh", ...])`` / ``subprocess.Popen(["sh", ...])``
#   2. Helper wrappers that dispatch to a retired Yoke script name —
#      ``_run_shell("foo.sh", ...)``, ``delegate_shell(..., "foo.sh", ...)``,
#      ``_run_yoke_db(...)`` and friends
#   3. ``subprocess.run([sys.executable, "-m", <mod>, ...])`` against a
#      retired shell script name passed in as a positional arg
#
# The guard walks every ``runtime/api/**/*.py`` file that is NOT a test
# and NOT an allowlisted user-command surface, and greps for each
# pattern. Allowlisted sites are exactly the places where Yoke
# deliberately exposes ``sh -c <user-command>`` as a runtime surface
# (executors.py and merge_worktree's user-supplied test_cmd hook).


def _python_sources() -> List[Path]:
    """Every production Python file under ``runtime/api/``.

    Excludes test files, the zero-shell-proof test itself, the shell
    inventory tool (which legitimately enumerates historical shell
    filenames), and the migrate-to-sqlite historical tool.
    """
    skip_basenames = {
        "shell_inventory.py",
        "shell_inventory_classify.py",
        "shell_inventory_report.py",
        "shell_inventory_rules.py",
        "shell_inventory_scan.py",
        "shell_inventory_closeout.py",
        "migrate_to_sqlite.py",
    }
    out: List[Path] = []
    for path in sorted(API_ROOT.rglob("*.py")):
        name = path.name
        if name.startswith("test_"):
            continue
        if path.name == "test_zero_shell_proof.py":
            continue
        if name in skip_basenames:
            continue
        out.append(path)
    return out


#: Allowlist for ``subprocess.run(["sh", ...])`` — these are the only
#: sites in production Python where an explicit user-supplied shell
#: command is forwarded to ``sh -c``. No other file is permitted to
#: construct an ``["sh", ...]`` argv.
_DIRECT_SH_ALLOWLIST: frozenset = frozenset({
    "runtime/api/tools/executors.py",
    "runtime/api/engines/merge_worktree.py",
})

#: Helper-name patterns that historically wrapped Yoke shell scripts.
#: Any production-Python match of these helpers is a regression.
_HELPER_WRAPPER_NAMES: Tuple[str, ...] = (
    "_run_shell",
    "delegate_shell",
    "_run_yoke_db",
)

#: Retired Yoke shell script names — if any one of these appears as a
#: positional argument to ``subprocess.run``/``subprocess.Popen`` or as
#: a string literal threaded into a helper-wrapper, it is a regression.
_RETIRED_SCRIPT_NAMES: Tuple[str, ...] = (
    "yoke-db.sh",
    "project-db.sh",
    "resolve-paths.sh",
    "schema-db.sh",
    "shepherd-db.sh",
    "rebuild-board.sh",
    "render-body.sh",
    "service-client.sh",
    "config-helper.sh",
    "flow-db.sh",
    "env-db.sh",
    "release-notes-db.sh",
    "merge-worktree.sh",
    "backup-db.sh",
    "discovery-scan.sh",
    "bootstrap-project.sh",
    "done-transition.sh",
    "update-status.sh",
    "qa-gate-check.sh",
    "backlog-registry.sh",
    "observe-tool.sh",
    "lint-test-pipe.sh",
    "preview-board-art.sh",
    "migrate-to-sqlite.sh",
    # restored behavior lives at
    # ``yoke_core.domain.projects validate-test-commands``.
    "validate-test-commands.sh",
)


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _iter_offenders(
    sources: Iterable[Path],
    pattern: "re.Pattern[str]",
    *,
    allowlist: frozenset = frozenset(),
) -> List[Tuple[str, int, str]]:
    """Return ``[(rel_path, lineno, line)]`` for every production-Python
    hit of *pattern*. Files in *allowlist* are skipped entirely."""
    offenders: List[Tuple[str, int, str]] = []
    for src in sources:
        rel = _relative(src)
        if rel in allowlist:
            continue
        try:
            text = src.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append((rel, lineno, line.strip()))
    return offenders


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Skill-file regression guard helpers
# ---------------------------------------------------------------------------

SKILLS_ROOT = REPO_ROOT / ".agents" / "skills" / "yoke"

#: Intentional-boundary inventory: skill files where ``mktemp`` is legitimate
#: for output capture (binary files, test harness output, multi-step pipelines).
#: Any mktemp usage outside this set is a regression — content writes should
#: use ``--stdin`` or ``--body-file`` instead.
_MKTEMP_ALLOWLIST: frozenset = frozenset({
    "advance/preflight-checks.md",
    "advance/browser-qa-fallback.md",
    "advance/implementing/implementation.md",
    "conduct/dispatch-context-prompts.md",
    "conduct/dispatch-context-verify.md",
    "conduct/engineer-tester-dispatch.md",
    "conduct/entry-activation.md",
    "conduct/SKILL.md",
    "usher/collect.md",
})


def _skill_files() -> List[Path]:
    """Every ``.md`` file under the skills root."""
    return sorted(SKILLS_ROOT.rglob("*.md"))


def _skill_relative(path: Path) -> str:
    """Return path relative to the skills root (e.g. ``do/loop.md``)."""
    return path.relative_to(SKILLS_ROOT).as_posix()


def _live_doc_files() -> List[Path]:
    """Markdown docs that define live operator/prompt contracts."""
    docs_root = REPO_ROOT / "docs"
    files = [
        AGENTS_DOC,
        REPO_ROOT / ".yoke" / "strategy" / "PROMPTS.md",
        REPO_ROOT / "runtime" / "harness" / "codex" / "SMOKE-TEST.md",
    ]
    files.extend(path for path in docs_root.rglob("*.md") if "archive" not in path.parts)
    files.extend(_skill_files())
    return sorted(files)

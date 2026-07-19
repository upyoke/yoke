"""Path allow-lists for ``doctor_hc_obsoleted_terms``.

Three kinds of allow-list live here:

* :data:`EXEMPT_PATH_SEGMENTS` — directory-name segments that exempt any
  path containing the segment from the scan entirely. Historical record
  trees (``archive``, ``ouroboros``, ``wrapup_reports``, ``qa-artifacts``,
  ``legacy-plan-artifacts``) and dependency / build trees go here.

* :data:`PATH_ALLOWLIST_ALL_PATTERNS` — files exempt from EVERY pattern.
  Used for audit code, residue tests, and pattern-shape tests that
  exhaustively enumerate retired surfaces and would otherwise require an
  entry against each pattern they touch.

* :data:`YOKE_DB_AUDIT_PATHS` and :data:`CODEX_HOOKS_AUDIT_PATHS` — file
  prefixes that ``doctor_hc_obsoleted_terms`` composes into
  ``_PER_PATTERN_PATH_ALLOWLIST`` for the specific pattern they apply to.
  Per-pattern exemptions stay narrow: the file is only excused from the
  specific retired-surface it legitimately enumerates.

Matching is prefix-based: an entry like
``runtime/api/tools/shell_inventory`` covers every
``shell_inventory_*.py`` sibling, while ``runtime/api/domain/observe.py``
matches that exact path as a prefix of itself.

Splitting the constants out of ``doctor_hc_obsoleted_terms.py`` keeps the
scanner module under the 350-line file-line-limit budget while keeping the
scan-scope logic close to the registry.
"""

from __future__ import annotations


# Directory-name segments whose presence in a path exempts the file from
# the scan entirely. Covers historical record trees and dependency /
# build trees.
EXEMPT_PATH_SEGMENTS: tuple[str, ...] = (
    "archive",
    "ouroboros",
    "wrapup_reports",
    "qa-artifacts",
    # Historical authoring evidence / planning snapshots for completed
    # cloud-runtime tickets. See docs/archive/legacy-plan-artifacts/atlas-boundary-inventory/atlas-evidence/README.md
    # — same conceptual role as docs/archive/ (record, not live prose).
    "legacy-plan-artifacts",
    "node_modules",
    ".venv",
    "venv",
    # Package build output (``pip wheel`` / setuptools ``build/`` and ``dist/``
    # trees). Regenerable copies of source that carry legacy-compat references;
    # scanning them re-reports residue from stale built copies of files the
    # tracked source has already retired, and their presence mid-suite makes
    # the scan test order-dependent under xdist.
    "build",
    "dist",
    # Nested git-worktree checkouts (the Claude harness materialises one at
    # ``.claude/worktrees/<branch>/`` — a full second copy of the repo). Their
    # content is governed by the worktree's own branch, not by main; scanning
    # ``.claude/`` would otherwise re-scan that whole copy and report residue
    # from strategy/test/ouroboros files that the worktree legitimately carries.
    "worktrees",
)


# Files exempt from EVERY pattern. Each entry is a repo-relative prefix.
PATH_ALLOWLIST_ALL_PATTERNS: tuple[str, ...] = (
    # This module itself enumerates retired surface names in its rationale
    # comments — a per-pattern allow-list of audit infrastructure cannot
    # avoid naming the surfaces it lists allow-list paths for.
    "runtime/api/engines/doctor_hc_obsoleted_terms_allowlists.py",
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_obsoleted_terms_allowlists.py",
    # Absence guards legitimately name retired hook modules in Path("...")
    # literals so the test can assert they remain deleted.
    "runtime/harness/test_hook_runner_session_dispatch.py",
    # Residue + pattern-shape tests: residue grep assertions, fixture
    # builders, and scan-widening regression tests enumerate retired terms
    # across every pattern family in their docstrings and test bodies.
    "runtime/api/engines/test_doctor_hc_obsoleted_terms.py",
    # Scan-behaviour tests: synthetic-tree fixtures and docstrings enumerate
    # retired terms across every pattern family to verify scan + allow-list
    # semantics.
    "runtime/api/engines/test_doctor_hc_obsoleted_terms_scan.py",
    # Pattern-shape tests: assert each registry pattern compiles and matches
    # its intended bare term; the test bodies necessarily name the retired
    # terms literally.
    "runtime/api/engines/test_doctor_hc_obsoleted_terms_patterns.py",
    # This declaration module intentionally names every Pack-era retirement
    # in its labels while keeping the main registry within its line budget.
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_obsoleted_terms_packs.py",
)


# Path prefixes exempt from the ``yoke-db.sh`` pattern only.
YOKE_DB_AUDIT_PATHS: tuple[str, ...] = (
    # The DB-command detectors and their tests name the retired
    # yoke-db.sh wrapper literally so the lint can identify legacy
    # command shapes in tracked content.
    "runtime/api/domain/lint_db_rules",
    "runtime/api/domain/test_lint_db_cmd",
    # tc-label test passes the retired script name to a checker to assert
    # the numeric-HC filename rule rejects it.
    "runtime/api/domain/test_lint_tc_label.py",
    # observe.py parses cmdlines that historically used yoke-db.sh and
    # strips it; the parser test fixtures use the literal shape.
    "runtime/api/domain/observe.py",
    "packages/yoke-core/src/yoke_core/domain/observe.py",
    # runs.py docstring names the retired ``yoke-db.sh runs find-by-item``
    # command as background for the current canonical surface.
    "runtime/api/domain/runs.py",
    "packages/yoke-core/src/yoke_core/domain/runs.py",
    # agent_stop_test_helpers docstring contrasts the new helper with the
    # retired ``sh yoke-db.sh epic task-get`` wrapper.
    "runtime/api/domain/agent_stop_test_helpers.py",
    "packages/yoke-core/src/yoke_core/domain/agent_stop_test_helpers.py",
    # Doctor HC for agent prompts detects yoke-db.sh references in the
    # tracked prompt files; the detector code names the substring it looks
    # for.
    "runtime/api/engines/doctor_hc_agents_prompts.py",
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_agents_prompts.py",
    # test_doctor_filesystem_full_repo synthesizes prompts that contain
    # the retired wrapper so the doctor HC tests can fire.
    "runtime/api/engines/test_doctor_filesystem_full_repo.py",
    # Observe parser regression tests feed cmdlines that begin with
    # ``sh yoke-db.sh`` to verify the parser's retired-wrapper handling.
    "runtime/api/test_observe_full_refs.py",
    # Conduct simulation regression test references the retired shape as
    # part of a skill-doc residue check.
    "runtime/api/test_skill_doc_regressions_conduct_simulation.py",
    # Zero-shell proof inventory and helpers enumerate retired shell
    # wrappers (including yoke-db.sh) to prove they remain absent.
    "runtime/api/test_zero_shell_proof",
    # Shell-inventory audit code and its rules enumerate retired shell
    # wrappers by name.
    "runtime/api/tools/shell_inventory",
    "packages/yoke-core/src/yoke_core/tools/shell_inventory",
)


# Path prefixes exempt from the ``runtime.harness.codex.codex_hooks\b``
# pattern only.
CODEX_HOOKS_AUDIT_PATHS: tuple[str, ...] = (
    # test_tracked_claude_hooks docstring names the retired codex_hooks
    # module as the canonical example of a non-Python-resolved hook
    # command. The docstring reference is part of that hook-runner audit,
    # not drift.
    "runtime/api/test_tracked_claude_hooks.py",
)

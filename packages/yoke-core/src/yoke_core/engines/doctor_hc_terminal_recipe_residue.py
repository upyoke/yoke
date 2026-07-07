"""HC-terminal-recipe-residue: flag retired terminal-soup recipes in live prose.

The Yoke-functions epic replaces a family of shell recipes
with first-class typed function calls. Every CLI adapter in the parity
inventory remains ``adapter_status="live"`` because it stays a legitimate
operator surface, so an ``adapter_status="retired"`` keyed HC would be a
no-op for this epic. Instead, this HC scans live guidance surfaces against
two layered checks:

1. **Banned-literal residue** — :data:`RECIPE_RESIDUE_PATTERNS` (sourced
   from :mod:`yoke_core.domain.lint_structured_field_transform_shell_messages`)
   names canonical historical terminal-soup shapes. A match in any live
   guidance surface outside the allowlist is a FAIL.

2. **Registry-aware adapter abuse** — the HC also consults the CLI
   adapter inventory (:mod:`yoke_core.api.service_client_structured_api_adapter_inventory`)
   and FAILs when a registered Yoke adapter appears wrapped with shell
   choreography (``2>&1``, ``; echo $?``, command substitution, pipe-to-tee,
   heredoc, shell-variable capture) in live guidance surfaces. The HC fails on unclassified terminal
   soup, not only on a static banned-literal list.

Allowlist (per the spec's `Watch Out For`):

* ``docs/archive/**`` — historical decision records and removed surfaces.
* ``docs/db-reference/**`` — operator CLI reference with sanctioned adapter
  examples.
* ``runtime/api/**/test_*.py`` — test fixtures including regression-guard
  fixtures.

Scanned surfaces:

* ``.agents/skills/yoke/**``
* ``runtime/agents/**``
* ``runtime/harness/{claude,codex}/agents/**``
* ``docs/**``
* ``AGENTS.md``, ``CLAUDE.md``, ``CODEX.md``

The HC self-skips when the repo root cannot be resolved.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Tuple

from yoke_core.domain.lint_structured_field_transform_shell_messages import (
    RECIPE_RESIDUE_PATTERNS,
)
from yoke_core.engines.doctor_hc_terminal_recipe_residue_scan import (
    iter_scan_paths,
    path_in_allowlist,
    registry_choreography_findings,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


_HC_SLUG = "HC-terminal-recipe-residue"
_HC_DESC = "Retired terminal-soup recipes in live guidance surfaces"

_PATH_ALLOWLIST: Tuple[str, ...] = (
    "docs/archive/",
    "docs/db-reference/",
)

# Test files under runtime/api/** that intentionally inject recipe residue
# for regression-guard fixtures are also allowlisted.
_TEST_FILE_RE = re.compile(r"runtime/api/.*test_.*\.py$")


def _scan_recipe_residue(
    repo_root: Path,
    patterns: Iterable[str] = RECIPE_RESIDUE_PATTERNS,
) -> List[str]:
    """Return ``path:line: text`` findings for banned-literal matches.

    Each pattern in :data:`RECIPE_RESIDUE_PATTERNS` is a substring (not a
    regex). The HC reports a FAIL the moment a hit appears outside the
    allowlist; ordering and dedupe are best-effort.
    """
    findings: List[str] = []
    pattern_list = list(patterns)
    for path in iter_scan_paths(repo_root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = path.resolve().relative_to(repo_root.resolve())
        except ValueError:
            rel = path
        rel_str = str(rel)
        if path_in_allowlist(rel_str, _PATH_ALLOWLIST):
            continue
        if _TEST_FILE_RE.search(rel_str):
            continue
        # Don't flag the source-of-truth module that DEFINES the patterns,
        # nor the HC scan module that LISTS them as a checked vocabulary.
        if (
            rel_str.endswith(
                "lint_structured_field_transform_shell_messages.py"
            )
            or rel_str.endswith("doctor_hc_terminal_recipe_residue.py")
            or rel_str.endswith("doctor_hc_terminal_recipe_residue_scan.py")
        ):
            continue
        lines = text.splitlines()
        for line_no, line in enumerate(lines, start=1):
            for pat in pattern_list:
                if pat in line:
                    snippet = line.rstrip()[:160]
                    findings.append(f"{rel_str}:{line_no}: {snippet}")
                    break  # one hit per line is enough.
    return findings


def hc_terminal_recipe_residue(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """HC-terminal-recipe-residue: fail-closed on retired recipe shapes."""
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(
            _HC_SLUG, _HC_DESC, "PASS",
            "No repo root resolved — skipping.",
        )
        return
    repo_root = Path(repo_root_str)

    findings: List[str] = []
    findings.extend(_scan_recipe_residue(repo_root))
    findings.extend(
        registry_choreography_findings(
            repo_root, allowlist=_PATH_ALLOWLIST,
            test_file_re=_TEST_FILE_RE,
        )
    )

    if findings:
        rec.record(
            _HC_SLUG, _HC_DESC, "FAIL",
            "Retired terminal-soup recipes detected in live guidance "
            "surfaces. Each hit names the file:line:snippet of the "
            "match. The function-call surface "
            "(``yoke_function_dispatch`` + the adapter ``--json`` flag) "
            "replaces these shapes. Allowlisted surfaces remain "
            "docs/archive/**, docs/db-reference/**, and "
            "runtime/api/**/test_*.py.\n\n"
            + "\n".join(findings[:40]),
        )
    else:
        rec.record(_HC_SLUG, _HC_DESC, "PASS", "")


__all__ = [
    "hc_terminal_recipe_residue",
    "_scan_recipe_residue",
]

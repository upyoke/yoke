"""HC-obsoleted-terms: flag retired surface names that have leaked into live files.

Background
----------
When a column, table, module, CLI command, helper, or file is retired, its name
must not linger in tracked content. A stale reference teaches future agents (and
humans) a surface that no longer works, and the fix for the resulting confusion
is another wasted turn. The Obsoleted Terms Hard Rule in ``AGENTS.md`` formalises
this; ``HC-obsoleted-terms`` is the check that enforces it.

Maintenance
-----------
Every retirement of a surface must add one entry to ``OBSOLETED_TERM_PATTERNS``
in the *same commit* that removes or supersedes the surface. Patterns are stored
as regex fragments with escaped separators for symbol-form names; this keeps the
residue checks that operators run from the shell from matching the pattern
declaration in this file, while still compiling to a regex that matches the
bare retired surface in scanned files. Add a short human-readable label in
:data:`OBSOLETED_TERM_LABELS` so the doctor report names the term clearly.

Posture
-------
The check ships at ``severity=warn`` for the first release, matching the posture
of ``HC-historical-yok-n-cruft``. Doctor exits nonzero only on FAILs; warnings
surface in the report so owners can sweep prose on their schedule without
blocking unrelated work.

Scope policy: ``docs/archive/**`` and structured backlog fields on items in
terminal statuses are excluded as intentional historical provenance, per
``docs/archive/decisions/historical-obsoleted-hook-refs.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.engines.doctor_hc_obsoleted_terms_allowlists import (
    CODEX_HOOKS_AUDIT_PATHS,
    EXEMPT_PATH_SEGMENTS,
    PATH_ALLOWLIST_ALL_PATTERNS,
    YOKE_DB_AUDIT_PATHS,
)
from yoke_core.engines.doctor_hc_obsoleted_terms_backlog import scan_backlog_fields
from yoke_core.engines import doctor_hc_obsoleted_terms_packs as _pack_terms
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)

# Obsoleted-term declarations

_RETIRED_PARENT_EPIC_SYMBOL_PATTERN = r"items" + r"\." + "epic"
_RETIRED_PARENT_EPIC_CLI_PATTERN = r"items\s+(get|update|set)\s+\S+\s+" + "epic" + r"\b"
# SQL form: catches ``items WHERE epic = …`` and the screenshot-shape
# ``items WHERE epic_id IN (…)``. Tight enough that ``epic_tasks WHERE epic_id``
# (no leading ``items`` token) and ``id={epic-id-…}`` placeholders (``epic``
# preceded by ``{`` or ``-``, not by a SQL delimiter) do not trigger.
_RETIRED_PARENT_EPIC_SQL_PATTERN = (
    r"\bitems\b" + r"[^\n]*" + r"\bWHERE\b" + r"[^\n]*"
    + r"[\s,(]" + "epic" + r"(_id)?[\s)=;]"
)
# SQL select-list form: catches ``SELECT epic_id FROM items ...``. Keep this
# separate from the WHERE-clause form so each stale shape has a focused label.
_RETIRED_PARENT_EPIC_SQL_SELECT_PATTERN = (
    r"\bSELECT\b" + r"[^\n]*" + r"[\s,(]" + "epic" + r"(_id)?[\s,)]"
    + r"[^\n]*" + r"\bFROM\s+items\b"
)
# Prose form: catches ``the `epic` field on a backlog item`` and bare
# ``epic field on the item``. Optional backticks bracket the field token.
_RETIRED_EPIC_FIELD_PROSE_PATTERN = (
    r"`?" + "epic" + r"`?\s*field\s+on\s+(?:a|the)\s+(?:backlog\s+)?item\b"
)
# Backlog ontology prose: ``child issue`` / ``child issues``. The retired ontology
# implied items had a parent-child relationship in ``items``; today they are flat
# rows. GitHub-side parent issues are sync metadata for ``epic_tasks``, not items.
_RETIRED_CHILD_ISSUE_PATTERN = r"\b" + "child" + r"\s+" + "issue" + r"s?\b"
# Backlog ontology prose: the ``type=issue with an epic parent`` shape, which
# explicitly named the retired item-level parent link. Tolerant of backtick
# wrapping around either token.
_RETIRED_TYPE_ISSUE_EPIC_PARENT_PATTERN = (
    r"type" + r"\s*=\s*" + "issue" + r"\b[^\n]+" + "epic" + r"[^\n]{0,5}" + "parent"
)

# Coalesced patterns for the hook-runner cutover. Each grouped pattern covers
# a family of retired sibling module slugs whose individual identification is
# preserved by the matched line text rendered in the doctor report; the family
# label below names the shared retirement.
_RETIRED_CODEX_HOOKS_SIBLINGS_PATTERN = (
    r"runtime\.harness\.codex\.codex_hooks_"
    r"(tool_events|session_start|stop|prompt_submit|service_bridge)\b"
)
_RETIRED_SESSION_HOOKS_PER_EVENT_PATTERN = (
    r"\bsession_hooks_(denial|telemetry|side_effects|payload|identity|"
    r"orientation_checks|orientation_content|session_start|session_end|"
    r"user_prompt_submit|plan_render|target_resolution|service_client)\b"
)
# Routed-ownership rename: retired telemetry + field names. Three
# explicit patterns so each obsoleted token is named individually in the
# label registry per AGENTS.md "Obsoleted terms must not appear" rule.
_RETIRED_RECENT_OWNER_EXCLUSIONS_PATTERN = r"\brecent_owner_exclusions\b"
_RETIRED_EXCLUDED_RECENT_OWNER_COUNT_PATTERN = r"\bexcluded_recent_owner_count\b"
_RETIRED_EXCLUDED_RECENT_OWNER_PATTERN = r"\bexcluded_recent_owner\b"

# Workspace-based project resolvers are retired in favor of the canonical
# session project-scope resolver. Both names register as obsoleted so future
# references trip the HC.
_RETIRED_WORKSPACE_RESOLVER_CLI_PATTERN = r"\bresolve_project_from_workspace_cli\b"
_RETIRED_WORKSPACE_RESOLVER_HTTP_PATTERN = r"\b_resolve_project_from_workspace\b"
_RETIRED_PRODUCT_NAME_PATTERN = r"\b[Ss]unday\b"
# Retired product domain token (URL compounds like ``api.<domain>.com`` defeat
# the bare-name boundary) and retired item-id prefix. The ``[s]`` class and the
# ``\d+`` escape keep each declaration from matching itself, like ``[Ss]unday``.
_RETIRED_PRODUCT_DOMAIN_PATTERN = r"(?i)\b[s]undaydo\b"
_RETIRED_ITEM_PREFIX_PATTERN = r"\bSUN-\d+\b"

OBSOLETED_TERM_PATTERNS: tuple[str, ...] = (
    _RETIRED_PARENT_EPIC_SYMBOL_PATTERN,
    # CLI-argument form of the same retired parent-epic item field. The shape is
    # deliberately tight — ``items (get|update|set)`` must be followed by actual
    # whitespace, then a single non-whitespace ID token, then another whitespace,
    # then the bare field name at a word boundary. This stops prose that mentions
    # ``items update`` and the field name in separate clauses on one line.
    _RETIRED_PARENT_EPIC_CLI_PATTERN,
    _RETIRED_PARENT_EPIC_SQL_PATTERN,
    _RETIRED_PARENT_EPIC_SQL_SELECT_PATTERN,
    _RETIRED_EPIC_FIELD_PROSE_PATTERN,
    _RETIRED_CHILD_ISSUE_PATTERN,
    _RETIRED_TYPE_ISSUE_EPIC_PARENT_PATTERN,
    r"yoke_core\.domain\.doctor",
    r"yoke-db\.sh",
    # Hook-runner cutover: the per-harness front-door modules and their
    # per-event sibling modules were collapsed into the unified
    # ``runtime.harness.hook_runner`` chain. References must not reappear.
    r"runtime\.harness\.session_hooks\b",
    r"runtime\.harness\.codex\.codex_hooks\b",
    _RETIRED_CODEX_HOOKS_SIBLINGS_PATTERN,
    r"runtime\.harness\.session_hooks_register\b",
    r"runtime\.harness\.hook_helpers_executor\b",
    _RETIRED_SESSION_HOOKS_PER_EVENT_PATTERN,
    _RETIRED_RECENT_OWNER_EXCLUSIONS_PATTERN,
    _RETIRED_EXCLUDED_RECENT_OWNER_COUNT_PATTERN,
    _RETIRED_EXCLUDED_RECENT_OWNER_PATTERN,
    _RETIRED_WORKSPACE_RESOLVER_CLI_PATTERN,
    _RETIRED_WORKSPACE_RESOLVER_HTTP_PATTERN,
    _RETIRED_PRODUCT_NAME_PATTERN,
    _RETIRED_PRODUCT_DOMAIN_PATTERN,
    _RETIRED_ITEM_PREFIX_PATTERN,
    *_pack_terms.PACK_RETIREMENT_PATTERNS,
)

OBSOLETED_TERM_LABELS: dict[str, str] = {
    _RETIRED_PARENT_EPIC_SYMBOL_PATTERN: "retired parent-epic item field (symbol form)",
    _RETIRED_PARENT_EPIC_CLI_PATTERN: "retired parent-epic item field (CLI form)",
    _RETIRED_PARENT_EPIC_SQL_PATTERN: "retired parent-epic item field (SQL form)",
    _RETIRED_PARENT_EPIC_SQL_SELECT_PATTERN: "retired parent-epic item field (SQL select-list form)",
    _RETIRED_EPIC_FIELD_PROSE_PATTERN: "retired parent-epic item field (prose form)",
    _RETIRED_CHILD_ISSUE_PATTERN: "retired backlog ontology phrase (child issue)",
    _RETIRED_TYPE_ISSUE_EPIC_PARENT_PATTERN: "retired backlog ontology phrase (type=issue with epic parent)",
    r"yoke_core\.domain\.doctor": "yoke_core.domain.doctor (nonexistent module path)",
    r"yoke-db\.sh": "yoke-db.sh (retired shell wrapper)",
    r"runtime\.harness\.session_hooks\b": "runtime.harness.session_hooks (retired — collapsed into runtime.harness.hook_runner)",
    r"runtime\.harness\.codex\.codex_hooks\b": "runtime.harness.codex.codex_hooks (retired — collapsed into runtime.harness.hook_runner)",
    _RETIRED_CODEX_HOOKS_SIBLINGS_PATTERN: "runtime.harness.codex.codex_hooks_<event> sibling (retired — collapsed into runtime.harness.hook_runner)",
    r"runtime\.harness\.session_hooks_register\b": "runtime.harness.session_hooks_register (retired — renamed to runtime.harness.hook_runner_register)",
    r"runtime\.harness\.hook_helpers_executor\b": "runtime.harness.hook_helpers_executor (retired — renamed to runtime.harness.hook_helpers_identity)",
    _RETIRED_SESSION_HOOKS_PER_EVENT_PATTERN: "session_hooks_<event> (retired per-event sibling)",
    _RETIRED_RECENT_OWNER_EXCLUSIONS_PATTERN: "recent_owner_exclusions (retired — renamed to routed_ownership_exclusions)",
    _RETIRED_EXCLUDED_RECENT_OWNER_COUNT_PATTERN: "excluded_recent_owner_count (retired telemetry key — renamed to excluded_routed_ownership_count)",
    _RETIRED_EXCLUDED_RECENT_OWNER_PATTERN: "excluded_recent_owner (retired telemetry prefix — renamed to excluded_routed_ownership)",
    _RETIRED_WORKSPACE_RESOLVER_CLI_PATTERN: "resolve_project_from_workspace_cli (retired workspace resolver — replaced by resolve_session_project_scope)",
    _RETIRED_WORKSPACE_RESOLVER_HTTP_PATTERN: "_resolve_project_from_workspace (retired workspace resolver — replaced by resolve_session_project_scope)",
    _RETIRED_PRODUCT_NAME_PATTERN: "Sunday/sunday (retired product name — replaced by Yoke/yoke)",
    _RETIRED_PRODUCT_DOMAIN_PATTERN: "sundaydo (retired product domain token — replaced by upyoke.com)",
    _RETIRED_ITEM_PREFIX_PATTERN: "SUN-<digits> (retired item prefix — replaced by YOK-<digits>)",
    **_pack_terms.PACK_RETIREMENT_LABELS,
}

# Scan scope

# Scan operator-facing prose plus live runtime Python, so stale retired
# hook/module references in doctor code cannot reach main unnoticed.
# JSON/TOML/YAML stay out of scope by design (auto-generated from Python/TS
# inputs). Audit code that intentionally names retired surfaces is allow-listed
# by path below.
_SCAN_DIRS_BY_EXT: dict[str, tuple[str, ...]] = {
    ".md": (
        "docs",
        ".agents",
        ".claude",
        "packs",
        "projects",
        ".yoke/strategy",
    ),
    ".py": (
        "packages",
        "runtime",
    ),
}

_SCAN_ROOT_FILES: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
)

# Per-pattern path allow-list. Each entry is a repo-relative path string;
# matching is prefix-based so a single entry covers a file family. Audit-
# infrastructure prefixes live in :mod:`doctor_hc_obsoleted_terms_allowlists`
# alongside the broader per-file exemption; the dict below composes those
# tuples with the strategic-prose exemptions defined here.
_PER_PATTERN_PATH_ALLOWLIST: dict[str, tuple[str, ...]] = {
    _RETIRED_CHILD_ISSUE_PATTERN: (
        # WISP-15 in WISPS.md is a deliberately preserved Generation-7
        # deferral whose rule explicitly forbids locking in a parent/child schema
        # before managed parallel execution exists. Removing the entry would
        # destroy a strategic deferral artifact.
        ".yoke/strategy/WISPS.md",
    ),
    r"yoke-db\.sh": YOKE_DB_AUDIT_PATHS,
    r"runtime\.harness\.codex\.codex_hooks\b": CODEX_HOOKS_AUDIT_PATHS,
}

_SELF_PATH = Path(__file__).resolve()


def _is_exempt(path: Path) -> bool:
    if path.resolve() == _SELF_PATH:
        return True
    # Synthetic copies of the registry file (used by HC self-exemption tests)
    # carry the same filename but live under a tmp_path tree. The exemption
    # tracks the registry's identity, not its absolute location.
    if path.name == _SELF_PATH.name:
        return True
    for part in path.parts:
        if part in EXEMPT_PATH_SEGMENTS:
            return True
    return False


def _path_in_allowlist(rel_str: str, allow: tuple[str, ...]) -> bool:
    """Return True when ``rel_str`` is covered by any allow-list entry.

    Matching is prefix-based: an entry like ``runtime/api/tools/shell_inventory``
    covers every ``shell_inventory_*.py`` sibling, while an entry like
    ``.yoke/strategy/WISPS.md`` still matches the exact path as a prefix of itself.
    """
    return any(rel_str.startswith(entry) for entry in allow)


def _needs_slash_normalization(pattern_src: str) -> bool:
    """Return True when ``pattern_src`` targets a dotted Python module path.

    Slash-to-dot translation of the haystack lets a single dotted pattern
    catch both ``runtime.harness.codex.codex_hooks_tool_events`` and the
    string-literal ``runtime/harness/codex/codex_hooks_tool_events.py``.
    Patterns whose match is a field name, prose phrase, or shell wrapper
    stay original-only to avoid false positives on legitimate slash-form
    path lists (``items/epic_tasks/events``, ``path/file overlap``, etc).
    """
    return pattern_src.startswith((r"runtime\.", r"yoke_"))


def _iter_scan_paths(repo_root: Path):
    for name in _SCAN_ROOT_FILES:
        candidate = repo_root / name
        if candidate.is_file() and not _is_exempt(candidate):
            yield candidate
    for ext, dirs in _SCAN_DIRS_BY_EXT.items():
        for rel in dirs:
            base = repo_root / rel
            if not base.is_dir():
                continue
            for f in base.rglob(f"*{ext}"):
                if _is_exempt(f):
                    continue
                yield f


def scan_repo(repo_root: Path) -> list[str]:
    """Return ``path:line: text`` strings where an obsoleted term matched.

    Exposed so tests and operator tooling can run the same scan used by the HC.

    The registry stores module-path patterns in dotted form
    (``runtime\\.harness\\.session_hooks``). Live-code regressions often appear
    in slash form — string-literal paths like
    ``"runtime/harness/codex/codex_hooks_tool_events.py"`` — so for those
    patterns each line is matched against both the original text and its
    slash-to-dot translation. The reported text is always the original line.
    """
    hits: list[str] = []
    compiled = [(pat, re.compile(pat)) for pat in OBSOLETED_TERM_PATTERNS]
    for f in _iter_scan_paths(repo_root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        try:
            rel = f.resolve().relative_to(repo_root.resolve())
        except ValueError:
            rel = f
        rel_str = str(rel)
        if _path_in_allowlist(rel_str, PATH_ALLOWLIST_ALL_PATTERNS):
            continue
        for pattern_src, compiled_pattern in compiled:
            allow = _PER_PATTERN_PATH_ALLOWLIST.get(pattern_src, ())
            if _path_in_allowlist(rel_str, allow):
                continue
            normalize = _needs_slash_normalization(pattern_src)
            label = OBSOLETED_TERM_LABELS.get(pattern_src, pattern_src)
            for i, line in enumerate(lines, start=1):
                if compiled_pattern.search(line):
                    hits.append(f"{rel}:{i}: [{label}] {line.rstrip()[:160]}")
                elif normalize and compiled_pattern.search(line.replace("/", ".")):
                    hits.append(f"{rel}:{i}: [{label}] {line.rstrip()[:160]}")
    return hits


def hc_obsoleted_terms(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-obsoleted-terms: obsoleted surface names in live prose."""
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(
            "HC-obsoleted-terms",
            "Obsoleted terms in live files",
            "PASS",
            "No repo root resolved — skipping.",
        )
        return
    repo_root = Path(repo_root_str)
    hits = scan_repo(repo_root)
    hits.extend(scan_backlog_fields(conn, OBSOLETED_TERM_PATTERNS, OBSOLETED_TERM_LABELS))
    if hits:
        rec.record(
            "HC-obsoleted-terms",
            "Obsoleted terms in live files",
            "WARN",
            "\n".join(hits[:40]),
        )
    else:
        rec.record(
            "HC-obsoleted-terms",
            "Obsoleted terms in live files",
            "PASS",
            "",
        )

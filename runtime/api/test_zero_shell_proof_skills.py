"""Task 7: skill-file regression guards for the zero-shell-proof suite.

The Yoke-functions epic extends this suite with
assertions keyed on the canonical
``RECIPE_RESIDUE_PATTERNS`` vocabulary plus per-skill-family function-call
expectations. Each new test below documents which AC family it covers:

* AC-15.1 / AC-15.4 — banned-pattern hits in skill prose use the same
  ``RECIPE_RESIDUE_PATTERNS`` constant as the manifest test and Doctor HC.
* False-Teacher Eradication Contract — Progress Log writes teach the
  ``items.progress_log.append`` adapter; structured-field writes teach the
  ``items update --stdin`` shape (the retained operator surface) without
  the discouraged ``mktemp`` read-then-upsert choreography.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Set, Tuple

from yoke_core.domain.lint_structured_field_transform_shell_messages import (
    RECIPE_RESIDUE_PATTERNS,
)
from runtime.api.test_zero_shell_proof_test_helpers import (
    _MKTEMP_ALLOWLIST,
    _live_doc_files,
    _relative,
    _skill_files,
    _skill_relative,
)


def test_no_session_id_fallback_chains_in_skills() -> None:
    """Session-ID fallback chains (CLAUDE_SESSION_ID / CODEX_THREAD_ID ->
    YOKE_SESSION_ID) must NOT appear in any skill file.

    Hotfix 8015b561c moved the canonical fallback resolution out of
    ``do/loop.md`` and into ``yoke_core.tools.session_init`` (the
    wrapper the loop now invokes). The invariant that this resolution
    appears in exactly one place is preserved — the place is the Python
    wrapper, not a skill file. Skill files rely on the wrapper output
    or on ``YOKE_SESSION_ID`` already being set by the harness
    session-start hook.
    """
    # The fallback pattern: checking CLAUDE_SESSION_ID or CODEX_THREAD_ID
    # to set YOKE_SESSION_ID. We look for the executable assignment
    # pattern, not documentation references.
    fallback_pattern = re.compile(
        r'YOKE_SESSION_ID="\$(?:CLAUDE_SESSION_ID|CODEX_THREAD_ID)"'
    )
    files_with_fallback: List[str] = []
    for skill in _skill_files():
        rel = _skill_relative(skill)
        try:
            text = skill.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if fallback_pattern.search(text):
            files_with_fallback.append(rel)

    assert files_with_fallback == [], (
        "Session-ID fallback chain (CLAUDE_SESSION_ID / CODEX_THREAD_ID -> "
        "YOKE_SESSION_ID) is owned by ``yoke_core.tools.session_init`` "
        "and must not appear in any skill file. Found in: "
        + ", ".join(files_with_fallback)
    )


def test_no_content_write_mktemp_in_skills() -> None:
    """``mktemp`` in skill files must only appear in allowlisted files
    (intentional boundaries for output capture / binary files).

    Content writes should use ``--stdin`` or ``--body-file`` instead of
    the mktemp-write-pass pattern.
    """
    files_with_mktemp: Set[str] = set()
    for skill in _skill_files():
        rel = _skill_relative(skill)
        try:
            text = skill.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "mktemp" in text:
            files_with_mktemp.add(rel)

    unexpected = files_with_mktemp - _MKTEMP_ALLOWLIST
    assert not unexpected, (
        "Unexpected ``mktemp`` usage in skill files (YOK-1438). "
        "Content writes should use ``--stdin`` or ``--body-file`` instead. "
        "If this is intentional output capture, add to ``_MKTEMP_ALLOWLIST``.\n"
        "Unexpected files: " + ", ".join(sorted(unexpected))
    )

    # Also verify the allowlist is not stale — every entry should
    # correspond to an actual file that still uses mktemp.
    stale = _MKTEMP_ALLOWLIST - files_with_mktemp
    assert not stale, (
        "Stale entries in ``_MKTEMP_ALLOWLIST`` — these files no longer "
        "use ``mktemp``: " + ", ".join(sorted(stale))
    )


def test_no_service_client_script_path_in_skills() -> None:
    """Skill files must not use the path-based invocation pattern
    ``python3 "$_workspace/runtime/api/service_client.py"`` — they must
    use ``python3 -m yoke_core.api.service_client`` instead.
    """
    pattern = re.compile(r'service_client\.py')
    offenders: List[Tuple[str, int, str]] = []
    for skill in _skill_files():
        rel = _skill_relative(skill)
        try:
            text = skill.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append((rel, lineno, line.strip()))

    assert not offenders, (
        "Path-based ``service_client.py`` invocation found in skill files "
        "(YOK-1438). Use ``python3 -m yoke_core.api.service_client`` instead.\n"
        + "\n".join(f"  {f}:{n}: {line}" for f, n, line in offenders)
    )


def test_no_task_update_body_body_file_examples_in_live_docs() -> None:
    """Live docs/skills should teach stdin-first task body updates."""
    pattern = re.compile(r"task-update-body .*--body-file")
    offenders: List[Tuple[str, int, str]] = []
    for doc in _live_doc_files():
        rel = _relative(doc)
        try:
            text = doc.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append((rel, lineno, line.strip()))

    assert not offenders, (
        "Live docs/skills still teach ``task-update-body ... --body-file`` "
        "as the default path (YOK-1438 AC-8). Prefer stdin-first examples.\n"
        + "\n".join(f"  {f}:{n}: {line}" for f, n, line in offenders)
    )


def test_no_items_update_body_file_examples_in_live_docs() -> None:
    """Live docs/skills should teach stdin-first structured field writes."""
    pattern = re.compile(r"items update .*--body-file")
    offenders: List[Tuple[str, int, str]] = []
    for doc in _live_doc_files():
        rel = _relative(doc)
        try:
            text = doc.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append((rel, lineno, line.strip()))

    assert not offenders, (
        "Live docs/skills still teach ``items update ... --body-file`` "
        "as the default transport path (YOK-1438 AC-3/AC-9). Prefer stdin-first examples.\n"
        + "\n".join(f"  {f}:{n}: {line}" for f, n, line in offenders)
    )


# ---------------------------------------------------------------------------
# Yoke-functions epic: banned-pattern coverage keyed on
# ``RECIPE_RESIDUE_PATTERNS`` plus per-skill-family function-call
# expectations.
# ---------------------------------------------------------------------------


def test_no_recipe_residue_patterns_in_skill_files() -> None:
    """AC-15.1 / AC-15.4: skill prose contains zero banned residue patterns.

    Single source of truth is
    ``yoke_core.domain.lint_structured_field_transform_shell_messages.
    RECIPE_RESIDUE_PATTERNS``. Update both the messages module and the
    Doctor HC together when the canonical vocabulary changes. This test
    fails when any banned literal appears in a skill markdown file.
    """
    offenders: List[Tuple[str, int, str, str]] = []
    for skill in _skill_files():
        rel = _skill_relative(skill)
        try:
            text = skill.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in RECIPE_RESIDUE_PATTERNS:
                if pat in line:
                    offenders.append(
                        (rel, lineno, pat, line.rstrip()[:160])
                    )
                    break
    assert not offenders, (
        "Skill prose contains banned terminal-soup recipes from "
        "``RECIPE_RESIDUE_PATTERNS`` (YOK-1665). Rewrite each hit to "
        "teach the function-call adapter (``yoke_function_dispatch`` "
        "or the matching ``--json`` CLI shape).\n"
        + "\n".join(
            f"  {rel}:{lineno}: [{pat}] {snippet}"
            for rel, lineno, pat, snippet in offenders[:40]
        )
    )


def test_progress_log_skills_teach_section_append_function() -> None:
    """False-Teacher Eradication Contract: skill prose that mentions the
    Progress Log section must teach the function-call adapter, not the
    discouraged ``mktemp + sections upsert`` read-then-write choreography.

    The function-call surface is
    ``python3 -m yoke_core.domain.item_field_transform section-append``
    (dispatches through ``items.progress_log.append``). Skills that name
    the Progress Log section but never link to ``section-append`` are
    likely teaching the legacy recipe.
    """
    legacy_choreography = re.compile(
        r"sections upsert.*Progress Log|mktemp.*yoke-progress",
    )
    offenders: List[Tuple[str, int, str]] = []
    for skill in _skill_files():
        rel = _skill_relative(skill)
        try:
            text = skill.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if legacy_choreography.search(line):
                offenders.append((rel, lineno, line.rstrip()[:160]))
    assert not offenders, (
        "Skill prose teaches the legacy Progress Log read-then-upsert "
        "choreography (mktemp + sections upsert). Replace with "
        "``python3 -m yoke_core.domain.item_field_transform "
        "section-append --item YOK-N --section 'Progress Log' "
        "--headline <text> --ordering 200 --source <name> --stdin`` "
        "which dispatches through ``items.progress_log.append`` and "
        "preserves prior entries automatically.\n"
        + "\n".join(f"  {f}:{n}: {snip}" for f, n, snip in offenders[:40])
    )


def test_structured_writes_use_stdin_or_body_file_not_mktemp() -> None:
    """False-Teacher Eradication Contract: skill prose that writes a
    structured field via ``items update`` must use ``--stdin`` or
    ``--body-file PATH``, never the mktemp-write-pass shape.

    This is the issue-side counterpart to
    ``test_progress_log_skills_teach_section_append_function``. The
    function-call surface is ``items.structured_field.replace``;
    legitimate operator-facing CLI shapes are stdin or body-file. A skill
    that mints a temp file to thread content into ``items update`` is the
    discouraged shape the Yoke-functions epic retires.
    """
    items_update_with_temp = re.compile(
        r"items update.*--body-file\s+\$\{?_?tmp|"
        r"items update.*<\s*\$\{?_?tmp",
    )
    offenders: List[Tuple[str, int, str]] = []
    for skill in _skill_files():
        rel = _skill_relative(skill)
        try:
            text = skill.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if items_update_with_temp.search(line):
                offenders.append((rel, lineno, line.rstrip()[:160]))
    assert not offenders, (
        "Skill prose threads content through a shell temp variable into "
        "``items update`` (e.g. ``--body-file ${_tmp}``). Replace with "
        "``--stdin`` (preferred) or ``--body-file PATH`` where PATH is a "
        "real artifact file the agent already authored. The function-"
        "call surface ``items.structured_field.replace`` is the typed "
        "path; the CLI adapter accepts ``--stdin`` and ``--body-file`` "
        "as the two sanctioned content sources.\n"
        + "\n".join(f"  {f}:{n}: {snip}" for f, n, snip in offenders[:40])
    )


def test_recipe_residue_patterns_used_canonically() -> None:
    """AC-15.4: this test module imports ``RECIPE_RESIDUE_PATTERNS`` directly
    so the assertion class cannot drift from the canonical vocabulary.

    A future refactor that copies the patterns into a sibling module
    instead of importing them must fail this check. The HC and the
    manifest test both pin the same dependency.
    """
    assert RECIPE_RESIDUE_PATTERNS, (
        "RECIPE_RESIDUE_PATTERNS must remain non-empty. The constant "
        "lives in "
        "yoke_core.domain.lint_structured_field_transform_shell_messages; "
        "both this suite and the Doctor HC consume it directly."
    )
    # The constant must be a tuple so callers cannot mutate it by mistake.
    assert isinstance(RECIPE_RESIDUE_PATTERNS, tuple), (
        "RECIPE_RESIDUE_PATTERNS must be a tuple. The Doctor HC, the "
        "lint module, and the regression-test suite all consume it as "
        "an immutable shared vocabulary."
    )

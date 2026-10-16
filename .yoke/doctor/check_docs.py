"""Documentation health checks — doc drift, doc health, AGENTS.md drift.

HC functions for detecting documentation drift, auditing doc health,
and checking AGENTS.md (shared doctrine) semantic consistency. The
historical HC identifier ``claudemd-drift`` is preserved for report
consumers; the canonical shared instruction file is AGENTS.md.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def _emit_hc_progress(hc_id: str, stage: str) -> None:
    print(f"running {hc_id} {stage}", flush=True)


def hc_doc_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-doc-drift: Documentation drift (source changes without doc updates)."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-doc-drift", "Documentation drift", "PASS", "")
        return

    r = _base._run(
        ["git", "-C", repo_root, "log", "--format=COMMIT %H", "--name-only", "-30"],
        timeout=15,
    )
    if r.returncode != 0:
        rec.record("HC-doc-drift", "Documentation drift", "PASS", "")
        return

    src_exts = (
        ".agents/skills/yoke/scripts/",
        "runtime/harness/claude/agents/yoke-",
        ".agents/skills/yoke/",
        "runtime/harness/claude/rules/",
    )
    doc_exts = (
        "docs/",
        "AGENTS.md",
        "CLAUDE.md",
        "runtime/harness/claude/agents/yoke-",
        "/SKILL.md",
    )

    issues: List[str] = []
    cur_hash = ""
    cur_src = ""
    cur_doc = False

    def _flush():
        nonlocal cur_hash, cur_src, cur_doc
        if cur_hash and cur_src and not cur_doc:
            issues.append(
                f"- Commit {cur_hash[:7]} changed source without doc update: {cur_src}"
            )

    for line in r.stdout.splitlines():
        if line.startswith("COMMIT "):
            _flush()
            cur_hash = line[7:]
            cur_src = ""
            cur_doc = False
            continue
        if not line.strip():
            continue
        is_src = any(line.startswith(p) or p in line for p in src_exts)
        is_doc = any(line.startswith(p) or p in line for p in doc_exts)
        # A `.md` file under `.agents/skills/yoke/` IS its own teaching
        # surface; treat it as a doc update too so an in-skill prose fix
        # without a paired `docs/` edit doesn't false-positive. Scripts
        # under `.agents/skills/yoke/scripts/` keep their src-only
        # classification because they end in `.py`, not `.md`.
        if line.startswith(".agents/skills/yoke/") and line.endswith(".md"):
            is_doc = True
        if is_src:
            cur_src = f"{cur_src}, {line}" if cur_src else line
        if is_doc:
            cur_doc = True
    _flush()

    if issues:
        rec.record("HC-doc-drift", "Documentation drift", "WARN", "\n".join(issues))
    else:
        rec.record("HC-doc-drift", "Documentation drift", "PASS", "")


def hc_doc_health(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Public corpus and copies fail closed; contributor links are review notes."""
    from yoke_core.domain.documentation_links import validate_links
    from yoke_core.domain.documentation_residue import scan_retired_references
    from yoke_core.domain.install_bundle_docs_validation import (
        CorpusRefusal,
        validate_public_corpus,
        validate_published_copies,
    )

    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-doc-health", "Documentation health audit", "PASS", "")
        return
    repo = Path(repo_root)
    _emit_hc_progress("HC-doc-health", "validate-complete-public-corpus")
    failures = validate_public_corpus(repo / "docs/public")
    failures.extend(validate_published_copies(repo))
    failures.extend(scan_retired_references(repo))
    if not (repo / "README.md").is_file():
        failures.append(
            CorpusRefusal(
                "CORPUS_ROOT_MISSING",
                "README.md",
                "missing orientation",
                "restore the repository README",
            )
        )
    tracked = _base._run(["git", "-C", str(repo), "ls-files", "--", "docs"], timeout=15)
    if tracked.returncode:
        failures.append(
            CorpusRefusal(
                "CORPUS_READ_FAILED",
                "docs",
                "tracked pages unavailable",
                "restore readable git metadata and retry",
            )
        )
    pages = [
        p
        for p in tracked.stdout.splitlines()
        if p.endswith(".md") and not p.startswith(("docs/public/", "docs/archive/"))
    ]
    _emit_hc_progress("HC-doc-health", f"validate-contributor-links {len(pages)} pages")
    notes = validate_links(repo, pages)
    rec.record(
        "HC-doc-health",
        "Documentation health audit",
        "FAIL" if failures else "WARN" if notes else "PASS",
        "\n".join([str(r) for r in failures] + [f"REVIEW {r}" for r in notes]),
    )


def hc_claudemd_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-claudemd-drift: AGENTS.md semantic drift.

    Historical HC identifier is retained for report-consumer compatibility.
    AGENTS.md is the canonical harness-neutral doctrine file; CLAUDE.md is
    a compatibility symlink that resolves to the same content.
    """
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-claudemd-drift", "AGENTS.md semantic drift", "PASS", "")
        return

    issues: List[str] = []
    doctrine_path = Path(repo_root) / "AGENTS.md"
    if not doctrine_path.is_file():
        # Legacy checkouts may only have CLAUDE.md — fall back to that.
        legacy_path = Path(repo_root) / "CLAUDE.md"
        if legacy_path.is_file():
            doctrine_path = legacy_path
    if doctrine_path.is_file():
        text = doctrine_path.read_text(errors="replace")
        if re.search(
            r"sed/awk/grep.*JSON|JSON.*sed/awk/grep|sed/awk/grep.*\(no jq", text
        ):
            issues.append(
                "- AGENTS.md references sed/awk/grep for JSON — should reference json-helper.sh"
            )
        if "no jq dependency" in text:
            issues.append(
                "- AGENTS.md says 'no jq dependency' — helpers now use Python 3"
            )

    if issues:
        rec.record(
            "HC-claudemd-drift", "AGENTS.md semantic drift", "WARN", "\n".join(issues)
        )
    else:
        rec.record("HC-claudemd-drift", "AGENTS.md semantic drift", "PASS", "")


# Slug and display name are the ones this check has always reported under.
from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ("doc-drift", "Documentation drift", hc_doc_drift),
    ("doc-health", "Documentation health audit", hc_doc_health),
    ("claudemd-drift", "AGENTS.md semantic drift", hc_claudemd_drift),
)

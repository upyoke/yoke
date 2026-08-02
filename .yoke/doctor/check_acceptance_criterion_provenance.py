"""HC-acceptance-criterion-provenance: work-item criterion labels in live prose.

Background
----------
The Codebase-reader naming rule in ``AGENTS.md`` says live content must
describe its current function and never explain itself by pointing at the
planning artifact that motivated it. A reader who only has the repository
cannot resolve a bare criterion label: it names a checkbox in a work item
they will never see. The label is also pure noise, because the sentence it
prefixes almost always already says what the code or test does.

This module deliberately never spells a literal criterion token in its own
prose. It scans ``.yoke/doctor/`` along with every other live tree, so an
illustrative example here would make the check flag itself — the same
self-reference trap ``HC-obsoleted-terms`` avoids by escaping the separator
in its pattern declarations.

``HC-obsoleted-terms`` covers retired surface names and
``HC-historical-yok-n-cruft`` covers work-item references. Neither covers
acceptance-criterion labels, which is why they accumulated unchecked in test
prose long after live modules were swept clean.

Exemptions
----------
``AC-N`` is not always provenance. Four categories are legitimate and are
declared as structured path/line rules rather than a prose allowlist:

``LABEL_FORMAT_SURFACES``
    Files that emit or teach the canonical ``- [ ] AC-N: {description}``
    acceptance-criteria format — the PRD validator, the preflight gate, the
    Product Manager / Architect / Boss agent bodies, and the skill prose that
    parses or templates that format. This is runtime data the product itself
    produces and consumes, which the naming rule explicitly excepts.

``GENERATED_MIRRORS``
    Byte-exact snapshots rendered from a canonical source. Editing them
    directly would only be undone by the next render; fix the source and
    re-render instead.

``ARCHIVE_ROOTS``
    ``docs/archive/**`` is the sanctioned home for historical provenance.

``_CHECKBOX_LABEL``
    Any line carrying the checkbox format itself, wherever it appears —
    including a test's own synthetic item-body fixtures.

Posture
-------
FAIL. Its two sibling prose checks ship at warn because each still has a
residue to sweep; this one does not — the tree is clean, so every hit is a
new introduction and blocking is the whole point. The exemption model was
validated against the full tree: it separated 541 real labels from the
handful of legitimate ones without a hand-maintained baseline.
"""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)

_HC_SLUG = "acceptance-criterion-provenance"
_HC_NAME = "No acceptance-criterion provenance in live prose"

#: One criterion token. Covers the bare number, a dotted sub-number, a
#: trailing letter, a parenthesized variant, and a project-prefixed form.
_TOKEN = r"(?:[A-Z]{2,4}-)?AC-\d+(?:\.\d+)?[a-z]?(?:\([a-z]\))?"
_PROVENANCE = re.compile(_TOKEN)

#: The acceptance-criteria label format the product emits and parses. A line
#: carrying it is data, not provenance, wherever it appears.
_CHECKBOX_LABEL = re.compile(r"-\s*\[[ xX]\]\s*(?:[A-Z]{2,4}-)?AC-\d")

#: Files that emit or teach the checkbox format above.
LABEL_FORMAT_SURFACES: tuple[str, ...] = (
    "packages/yoke-core/src/yoke_core/domain/prd_validate.py",
    "packages/yoke-core/src/yoke_core/engines/"
    "advance_implementation_preflight_gates.py",
    "runtime/agents/",
    "runtime/harness/claude/agents/",
    "runtime/harness/codex/agents/",
    ".agents/skills/yoke/shepherd/boss-verdict-transitions.md",
    ".agents/skills/yoke/polish/review.md",
    "runtime/api/domain/test_data/browser_qa_inference/",
)

#: Byte-exact snapshots; fix the canonical source and re-render.
GENERATED_MIRRORS: tuple[str, ...] = (
    "packages/yoke-core/build/",
    "packages/yoke-core/src/yoke_core/install_bundle_tree/",
)

#: Sanctioned historical provenance.
ARCHIVE_ROOTS: tuple[str, ...] = ("docs/archive/",)

#: Tests whose SUBJECT is the label format or the naming rule itself. Here the
#: token is the assertion, not a description of one: rewriting it would invert
#: what the test proves. Same category as the emitters above — these verify the
#: format rather than merely mentioning it.
LABEL_FORMAT_UNDER_TEST: tuple[str, ...] = (
    # Asserts the naming rule enumerates a criterion label among the forbidden
    # provenance classes; the literal is the expected rule text.
    "runtime/api/domain/test_codebase_reader_naming_doctrine.py",
    # Feeds synthetic source to the item-ref scanner to prove a criterion label
    # is not mistaken for a work-item reference.
    "runtime/api/domain/test_lint_item_ref_construction.py",
    # Exercises the label normalizer; asserts exactly one label was minted.
    "runtime/api/domain/test_normalize_ac_labels.py",
    # Seeds an acceptance-criteria section the file-budget parser must skip.
    "runtime/api/test_idea_readiness_check_claim_consistency.py",
)

_EXEMPT_PREFIXES = (
    LABEL_FORMAT_SURFACES
    + LABEL_FORMAT_UNDER_TEST
    + GENERATED_MIRRORS
    + ARCHIVE_ROOTS
)

#: Trees whose prose this check owns.
_SCAN_ROOTS: tuple[str, ...] = (
    "runtime",
    "packages",
    "docs",
    ".agents",
    ".yoke/doctor",
    "tests",
)
_SCAN_SUFFIXES = frozenset({".py", ".md", ".toml"})


def _is_exempt(relative_path: str) -> bool:
    return any(relative_path.startswith(prefix) for prefix in _EXEMPT_PREFIXES)


def scan_acceptance_criterion_provenance(repo_root: Path) -> list[str]:
    """Return ``path:line: text`` for every non-exempt criterion label."""
    hits: list[str] = []
    for root_name in _SCAN_ROOTS:
        root = repo_root / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in _SCAN_SUFFIXES or not path.is_file():
                continue
            relative = path.relative_to(repo_root).as_posix()
            if _is_exempt(relative):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "AC-" not in text:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if _CHECKBOX_LABEL.search(line):
                    continue
                if _PROVENANCE.search(line):
                    hits.append(f"{relative}:{number}: {line.strip()[:110]}")
    return hits


def hc_acceptance_criterion_provenance(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-acceptance-criterion-provenance: criterion labels in live prose."""
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(_HC_SLUG, _HC_NAME, "PASS", "No repo root resolved — skipping.")
        return
    hits = scan_acceptance_criterion_provenance(Path(repo_root_str))
    if not hits:
        rec.record(_HC_SLUG, _HC_NAME, "PASS", "")
        return
    files = len({hit.split(":", 1)[0] for hit in hits})
    rec.record(
        _HC_SLUG,
        _HC_NAME,
        "FAIL",
        f"{len(hits)} line(s) across {files} file(s) explain themselves with a "
        "work-item acceptance-criterion label. A reader who only has the "
        "repository cannot resolve it; the sentence after the label usually "
        "already says what the code does, so deleting the label is the fix.\n"
        + "\n".join(hits[:40])
        + (f"\n... and {len(hits) - 40} more" if len(hits) > 40 else ""),
    )


__all__ = [
    "hc_acceptance_criterion_provenance",
    "scan_acceptance_criterion_provenance",
]

from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        _HC_SLUG,
        _HC_NAME,
        hc_acceptance_criterion_provenance,
    ),
)

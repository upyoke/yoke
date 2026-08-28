"""Render harness wake capability into the surfaces that teach it.

Four teaching surfaces used to assert independently what each harness can do,
and two of the four had drifted into stating the opposite of the measured
answer. The facts now live once, in
:mod:`yoke_contracts.harness_wake_capability`; the substrate renderer copies
them into each ``runtime/harness/<harness_id>/manifest.json`` under
``agent_wake``, and this module renders the same entries into every markdown
surface that shows the capability to a reader.

Markers — content between is REPLACED on every run::

    <!-- BEGIN GENERATED: harness-wake-capability -->
    <!-- END GENERATED: harness-wake-capability -->

A surface that only *explains a consequence* of a capability carries no block.
It cites the manifest fact instead, and :func:`uncited_capability_claims`
refuses any wake claim written without that citation, so the next stale
sentence fails a check instead of teaching an agent something untrue.

CLI: ``python3 -m yoke_core.tools.render_harness_capability_inline
                [--check] [--target-root PATH]``
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Sequence

from yoke_contracts.harness_wake_capability import (
    HARNESS_WAKE_CAPABILITIES,
    HarnessWakeCapability,
)
from yoke_core.domain.agents_render_workspace import resolve_target_root_for_cli
from yoke_core.tools.generated_block_render import (
    RenderResult,
    begin_marker,
    end_marker,
    format_drift_summary,
    render_blocks,
)


SLUG: str = "harness-wake-capability"
BEGIN_MARKER: str = begin_marker(SLUG)
END_MARKER: str = end_marker(SLUG)

MANIFEST_FIELD: str = "agent_wake"
MANIFEST_PATH_TEMPLATE: str = "runtime/harness/<harness_id>/manifest.json"
CANONICAL_MODULE: str = "yoke_contracts.harness_wake_capability"
REPAIR_COMMAND: str = (
    "python3 -m yoke_core.tools.render_harness_capability_inline"
)

# Surfaces carrying the full table: the reference documents a reader consults
# to learn the capability itself.
TABLE_SURFACES: tuple[str, ...] = (
    "docs/hook-parity-map.md",
)

# Surfaces carrying the compact list: working documents where an agent needs
# the answer in passing, not a reference table.
COMPACT_SURFACES: tuple[str, ...] = (
    ".agents/skills/yoke/steer/loop.md",
    "runtime/harness/claude/rules/session.md",
)

INVENTORY: tuple[str, ...] = TABLE_SURFACES + COMPACT_SURFACES

# Surfaces scanned for wake claims written outside a generated block. Every
# inventory surface qualifies, plus the documents that reason about wake
# behavior without rendering it.
CITATION_SCAN_SURFACES: tuple[str, ...] = INVENTORY + (
    "docs/harness-cursor-assessment.md",
    "docs/harness-bootstrap.md",
    "AGENTS.md",
)

# A line naming both a harness family and a wake primitive is making a wake
# claim, and must carry the citation token that points at the owning fact.
# The names are the manifest ids, deliberately not the bare product word: a
# Claude-only rules file says "Claude" in every other sentence, and a rule
# about using a primitive is not a claim about who has one.
_HARNESS_NAMES = tuple(HARNESS_WAKE_CAPABILITIES)
_WAKE_PRIMITIVES = ("Monitor", "ScheduleWakeup", "notify_on_output")
_CITATION_TOKENS = (MANIFEST_FIELD, "manifest.json", CANONICAL_MODULE)

_HARNESS_RE = re.compile(
    "|".join(re.escape(name) for name in _HARNESS_NAMES), re.IGNORECASE,
)
_PRIMITIVE_RE = re.compile(
    "|".join(re.escape(name) for name in _WAKE_PRIMITIVES),
)
# Only an assertion about the capability counts. A line that merely uses a
# primitive ("arm a standing `Monitor` on a fleet-delta probe") states no
# cross-harness fact and needs no citation.
_ASSERTION_RE = re.compile(
    r"\b(no equivalent|has no|have no|lacks?|cannot|can't|unable|"
    r"absent|only|never|rely on|relies on|no [a-z-]+ primitive)\b",
    re.IGNORECASE,
)


def _wake_phrase(wake: str, mechanism: str) -> str:
    if wake == "supported" and mechanism:
        return f"supported (`{mechanism}`)"
    return wake


def _harness_line(harness_id: str, cap: HarnessWakeCapability) -> str:
    idle = _wake_phrase(cap.idle_wake, cap.idle_wake_mechanism)
    timer = _wake_phrase(cap.timer_wake, cap.timer_wake_mechanism)
    verified = cap.verified_on_surface or "not verified"
    return (
        f"- `{harness_id}` — idle wake: {idle}; timer wake: {timer}. "
        f"Verified on {verified}."
    )


def _provenance_lines() -> list[str]:
    return [
        f"Wake capability is a manifest fact, not prose. Source of truth:",
        f"`{MANIFEST_FIELD}` in `{MANIFEST_PATH_TEMPLATE}`, rendered from",
        f"`{CANONICAL_MODULE}`. Change the contract and re-render; never",
        f"restate one of these facts on a document's own authority.",
    ]


def build_compact_block() -> str:
    """Return the short per-harness list used by working documents."""
    lines = [*_provenance_lines(), ""]
    for harness_id, cap in HARNESS_WAKE_CAPABILITIES.items():
        lines.append(_harness_line(harness_id, cap))
    return "\n".join(lines) + "\n"


def build_table_block() -> str:
    """Return the full table plus per-harness evidence for reference docs."""
    lines = [
        *_provenance_lines(),
        "",
        "| Harness | Idle wake (resume an ended turn) | Timer wake "
        "| Verified on |",
        "|---|---|---|---|",
    ]
    for harness_id, cap in HARNESS_WAKE_CAPABILITIES.items():
        idle = _wake_phrase(cap.idle_wake, cap.idle_wake_mechanism)
        timer = _wake_phrase(cap.timer_wake, cap.timer_wake_mechanism)
        verified = cap.verified_on_surface or "not verified"
        lines.append(
            f"| `{harness_id}` | {idle} | {timer} | `{verified}` |"
        )
    lines.append("")
    lines.append("Evidence behind each row:")
    lines.append("")
    for harness_id, cap in HARNESS_WAKE_CAPABILITIES.items():
        lines.append(f"- `{harness_id}` — {cap.evidence}")
    return "\n".join(lines) + "\n"


def content_for_path(rel_path: str) -> str:
    """Return the block body one inventory surface should carry."""
    if rel_path in TABLE_SURFACES:
        return build_table_block()
    return build_compact_block()


def render(
    target_root: pathlib.Path, *, check: bool = False,
) -> RenderResult:
    """Render the capability block into every inventory surface."""
    return render_blocks(
        target_root,
        slug=SLUG,
        inventory=INVENTORY,
        content_for_path=content_for_path,
        check=check,
    )


def format_render_drift(result: RenderResult, *, check: bool) -> str:
    """Render this family's drift report with its label and repair command."""
    return format_drift_summary(
        result,
        check=check,
        family_label="harness wake capability",
        repair_command=REPAIR_COMMAND,
    )


def uncited_capability_claims(
    target_root: pathlib.Path,
) -> tuple[str, ...]:
    """Return every wake claim written outside a block without a citation.

    A line asserting what a harness can or cannot do with a wake primitive is
    the exact shape that went stale. Outside a generated block it must name
    the owning fact — ``agent_wake``, the manifest path, or the contract
    module — so a capability change is traceable from the sentence that
    depends on it.
    """
    findings: list[str] = []
    for rel_path in CITATION_SCAN_SURFACES:
        abs_path = target_root / rel_path
        if not abs_path.exists():
            continue
        inside_block = False
        for number, line in enumerate(
            abs_path.read_text(encoding="utf-8").splitlines(), start=1,
        ):
            if BEGIN_MARKER in line:
                inside_block = True
                continue
            if END_MARKER in line:
                inside_block = False
                continue
            if inside_block:
                continue
            if not _PRIMITIVE_RE.search(line):
                continue
            if not _HARNESS_RE.search(line):
                continue
            if not _ASSERTION_RE.search(line):
                continue
            if any(token in line for token in _CITATION_TOKENS):
                continue
            findings.append(f"{rel_path}:{number}: {line.strip()[:120]}")
    return tuple(findings)


def format_uncited_summary(findings: Sequence[str]) -> str:
    """Render the operator-facing report for uncited wake claims."""
    if not findings:
        return ""
    lines = [
        f"ERROR: {len(findings)} wake-capability claim(s) written outside a "
        f"`{SLUG}` block without naming the owning fact:",
    ]
    lines.extend(f"  - {finding}" for finding in findings)
    lines.append("")
    lines.append(
        f"Cite `{MANIFEST_FIELD}` in `{MANIFEST_PATH_TEMPLATE}` on the line, "
        f"or move the claim inside a generated block and run "
        f"`{REPAIR_COMMAND}`."
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render_harness_capability_inline",
        description=(
            "Render harness wake capability into every generated-block "
            "marker surface, and refuse wake claims written elsewhere "
            "without naming the owning manifest fact. Use --check in CI / "
            "pre-commit to fail on drift."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: report drift and exit non-zero on any required change.",
    )
    parser.add_argument(
        "--target-root",
        default=None,
        help="Repo root to render against (default: git toplevel or cwd).",
    )
    args = parser.parse_args(argv)

    try:
        target_root = resolve_target_root_for_cli(args.target_root)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    result = render(target_root, check=args.check)
    summary = format_render_drift(result, check=args.check)
    if summary:
        sys.stderr.write(summary)

    findings = uncited_capability_claims(target_root)
    uncited = format_uncited_summary(findings)
    if uncited:
        sys.stderr.write(uncited)

    if not result.ok or findings:
        return 1
    if args.check and result.changed:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

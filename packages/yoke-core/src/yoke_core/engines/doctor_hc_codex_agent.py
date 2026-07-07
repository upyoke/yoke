"""HCs covering the Codex sub-agent surface.

* ``HC-codex-agent-adapter-drift`` — every ``.codex/agents/yoke-*.toml``
  matches the canonical body at ``runtime/agents/{role}.md`` plus the
  per-role subdir fragments (``runtime/agents/{role}/*.md``), AND carries
  the current Codex custom-subagent schema rather than retired adapter
  fields. The schema-residue scan fails the HC when an adapter still
  carries a legacy top-level ``prompt`` field, a Claude-style string tool
  allowlist, a turn-budget field, or a stale cross-provider model pin —
  defense-in-depth beyond byte parity, so a hand-edit or renderer
  regression that reintroduces the old shape is caught even if it parses.
  PASS-with-note when the native ``.codex/agents/`` surface is not yet
  provisioned.
* ``HC-codex-subagent-surface-truth`` — ``SAFE_OPERATOR_SURFACE``, both
  manifests, and the operator-facing docs (``CODEX.md``, ``docs/agents.md``)
  agree on which Yoke commands Codex supports — specifically the
  ``/yoke conduct`` claim is consistently dual-harness.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)
from yoke_core.domain.agents_render_codex import render_codex_agent


_CANONICAL_AGENTS_DIR = Path("runtime/agents")
_CODEX_AGENTS_DIR = Path(".codex/agents")
_CLAUDE_MANIFEST = Path("runtime/harness/claude/manifest.json")
_CODEX_MANIFEST = Path("runtime/harness/codex/manifest.json")
_CODEX_DOC = Path("CODEX.md")
_AGENTS_DOC = Path("docs/agents.md")

# Canonical agents for which Codex adapter parity is meaningful.
_CANONICAL_AGENTS = (
    "product-manager", "product-designer", "architect",
    "engineer", "tester", "simulator", "boss",
)


def _root_path(rel: Path) -> Path:
    root = _resolve_repo_root()
    return Path(root) / rel if root else rel


def _expected_codex_body(agent: str) -> str:
    base = _root_path(_CANONICAL_AGENTS_DIR / f"{agent}.md")
    body = base.read_text(encoding="utf-8") if base.exists() else ""
    extras: List[str] = []
    subdir = _root_path(_CANONICAL_AGENTS_DIR / agent)
    if subdir.is_dir():
        for fragment in sorted(subdir.glob("*.md")):
            extras.append(fragment.read_text(encoding="utf-8"))
    return "\n".join([body, *extras])


# Claude model nicknames have no Codex meaning; a Codex adapter pinning one
# is stale cross-provider residue. A legitimate future Codex pin names a real
# Codex model id, which these patterns do not match.
_CLAUDE_MODEL_NICKNAMES = ("opus", "sonnet", "haiku")

# Line-prefix patterns for retired Codex adapter schema fields. Text-based
# (not a TOML parse) so the scan is robust against partially-rendered or
# hand-corrupted adapters the parity check handles separately.
_RESIDUE_PATTERNS = (
    (re.compile(r"(?m)^\s*prompt\s*="),
     "legacy `prompt` field (use `developer_instructions`)"),
    (re.compile(r"(?m)^\s*tools\s*="),
     "legacy Claude-style string `tools` allowlist"),
    (re.compile(r"(?m)^\s*max_turns\s*="),
     "legacy `max_turns` turn-budget field"),
    (re.compile(
        r'(?m)^\s*model\s*=\s*"(?:' + "|".join(_CLAUDE_MODEL_NICKNAMES) + r')"'),
     "stale cross-provider model pin"),
)


def _schema_residue(adapter_text: str) -> List[str]:
    """Return human-readable issues for retired Codex adapter schema fields."""
    return [msg for pat, msg in _RESIDUE_PATTERNS if pat.search(adapter_text)]


# ---------------------------------------------------------------------------
# HC-codex-agent-adapter-drift
# ---------------------------------------------------------------------------


def hc_codex_agent_adapter_drift(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    name = "HC-codex-agent-adapter-drift"
    desc = "Codex agent adapters match canonical bodies"
    codex_dir = _root_path(_CODEX_AGENTS_DIR)
    if not codex_dir.is_dir():
        rec.record(
            name, desc, "PASS",
            f"{_CODEX_AGENTS_DIR} not provisioned yet; "
            "Codex sub-agent surface absent — nothing to compare",
        )
        return

    drifted: List[str] = []
    missing: List[str] = []
    extras: List[str] = []
    residue: List[str] = []
    seen_files = set()

    for agent in _CANONICAL_AGENTS:
        adapter = codex_dir / f"yoke-{agent}.toml"
        if not adapter.exists():
            missing.append(str(_CODEX_AGENTS_DIR / f"yoke-{agent}.toml"))
            continue
        seen_files.add(adapter.name)
        adapter_text = adapter.read_text(encoding="utf-8")
        try:
            expected_adapter = render_codex_agent(_root_path(_CANONICAL_AGENTS_DIR), agent)
        except FileNotFoundError:
            expected_body = _expected_codex_body(agent)
            drifted_body = bool(expected_body.strip()) and expected_body.strip() not in adapter_text
        else:
            drifted_body = adapter_text != expected_adapter
        if drifted_body:
            drifted.append(str(_CODEX_AGENTS_DIR / f"yoke-{agent}.toml"))
        agent_residue = _schema_residue(adapter_text)
        if agent_residue:
            residue.append(f"yoke-{agent}.toml: " + "; ".join(agent_residue))

    # Surface unexpected files (helps catch stale adapters that survived a
    # canonical role rename).
    expected_names = {f"yoke-{a}.toml" for a in _CANONICAL_AGENTS}
    for path in sorted(codex_dir.glob("yoke-*.toml")):
        if path.name not in expected_names:
            extras.append(path.name)

    issues: List[str] = []
    if missing:
        issues.append("missing adapters: " + ", ".join(missing))
    if drifted:
        issues.append("canonical body drift: " + ", ".join(drifted))
    if extras:
        issues.append("unexpected adapter files: " + ", ".join(extras))
    if residue:
        issues.append("stale Codex adapter schema: " + " | ".join(residue))

    if issues:
        rec.record(name, desc, "FAIL", "\n".join(issues))
    else:
        rec.record(
            name, desc, "PASS",
            f"all {len(_CANONICAL_AGENTS)} Codex adapters match canonical body",
        )


# ---------------------------------------------------------------------------
# HC-codex-subagent-surface-truth
# ---------------------------------------------------------------------------


def _claude_supports_conduct() -> bool | None:
    from yoke_core.domain.harness_capability_registry import SAFE_OPERATOR_SURFACE
    for entry in SAFE_OPERATOR_SURFACE:
        if entry.entrypoint == "/yoke conduct":
            return "claude-code" in entry.harness_support
    return None


def _codex_supports_conduct() -> bool | None:
    from yoke_core.domain.harness_capability_registry import SAFE_OPERATOR_SURFACE
    for entry in SAFE_OPERATOR_SURFACE:
        if entry.entrypoint == "/yoke conduct":
            return "codex" in entry.harness_support
    return None


def _manifest_disables_conduct(path: Path) -> bool | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    supports = data.get("supports") or {}
    disabled = supports.get("disabled_entrypoints") or []
    return "/yoke conduct" in [str(x) for x in disabled]


def _doc_mentions_codex_conduct_supported(text: str) -> bool:
    """Heuristic: docs positively state Codex can run conduct."""
    if not text:
        return False
    lowered = text.lower()
    return (
        "codex" in lowered
        and "conduct" in lowered
        and (
            "including `/yoke conduct`" in lowered
            or "full tier 1" in lowered
            or "conduct dispatches the same" in lowered
            or "codex dispatches" in lowered
            or "runs on codex" in lowered
        )
    )


def _doc_mentions_codex_conduct_unsupported(text: str) -> bool:
    """Heuristic: docs still carry the retired Claude-only conduct story."""
    if not text:
        return False
    lowered = text.lower()
    return (
        "conduct" in lowered
        and "codex" in lowered
        and ("not supported" in lowered or "unsupported" in lowered
             or "claude-code only" in lowered or "claude only" in lowered
             or "codex has no equivalent" in lowered
             or "does not run conduct" in lowered)
    )


def hc_codex_subagent_surface_truth(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    name = "HC-codex-subagent-surface-truth"
    desc = "Operator surface, manifests, and docs agree on conduct support"

    claude = _claude_supports_conduct()
    codex = _codex_supports_conduct()
    if claude is None or codex is None:
        rec.record(
            name, desc, "FAIL",
            "/yoke conduct missing from SAFE_OPERATOR_SURFACE",
        )
        return

    facts = [f"SAFE_OPERATOR_SURFACE conduct support: claude={claude} codex={codex}"]
    issues: List[str] = []

    # conduct is a dual-harness operator surface supported on both harnesses.
    expected_codex = True
    if codex != expected_codex:
        issues.append(
            "registry says Codex does not support /yoke conduct, but the "
            "the substrate contract requires dual-harness conduct support",
        )

    codex_manifest_disable = _manifest_disables_conduct(_root_path(_CODEX_MANIFEST))
    facts.append(f"codex manifest disables conduct: {codex_manifest_disable}")
    if codex_manifest_disable is True:
        issues.append("Codex manifest disables /yoke conduct — registry says it is supported")
    claude_manifest_disable = _manifest_disables_conduct(_root_path(_CLAUDE_MANIFEST))
    facts.append(f"claude manifest disables conduct: {claude_manifest_disable}")
    if claude_manifest_disable is True:
        issues.append("Claude manifest disables /yoke conduct — registry says it is supported")

    # Docs alignment: docs must not retain the old Claude-only conduct story,
    # and at least one operator-facing doc should positively state the new
    # dual-harness truth once the docs lane has landed.
    codex_doc = _root_path(_CODEX_DOC)
    agents_doc = _root_path(_AGENTS_DOC)
    codex_text = codex_doc.read_text(encoding="utf-8", errors="ignore") if codex_doc.exists() else ""
    agents_text = agents_doc.read_text(encoding="utf-8", errors="ignore") if agents_doc.exists() else ""
    docs_support = (
        _doc_mentions_codex_conduct_supported(codex_text)
        or _doc_mentions_codex_conduct_supported(agents_text)
    )
    docs_unsupported = (
        _doc_mentions_codex_conduct_unsupported(codex_text)
        or _doc_mentions_codex_conduct_unsupported(agents_text)
    )
    facts.append(f"docs state Codex conduct support: {docs_support}")
    facts.append(f"docs retain unsupported Codex conduct prose: {docs_unsupported}")
    if docs_unsupported:
        issues.append("operator docs still describe Codex conduct as unsupported")
    if not docs_support and (codex_doc.exists() or agents_doc.exists()):
        issues.append("operator docs do not state Codex conduct support")

    if issues:
        rec.record(name, desc, "FAIL", "\n".join(issues + facts))
    else:
        rec.record(name, desc, "PASS", "\n".join(facts))

"""Unit tests for HC-progressive-disclosure-direction.

Monkeypatches :func:`iter_tier_paths` + ``_resolve_repo_root`` so the
suite is fully self-contained — no live tier surfaces are read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Iterator, Tuple

import pytest

from yoke_core.engines import doctor_hc_progressive_disclosure_direction as mod
from yoke_core.engines.doctor_hc_progressive_disclosure_direction import (
    HC_SLUG,
    TIER_DIRECTION_RULES,
    VAGUE_DENIAL_MARKERS,
    hc_progressive_disclosure_direction,
)
from yoke_core.engines.doctor_registry_tier_discipline import (
    REQUIRED_FUNCTION_IDS,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_CONDUCT_SKILL = ".agents/skills/yoke/conduct/SKILL.md"
_ENGINEER_AGENT = "runtime/agents/engineer.md"
_ARCHITECT_AGENT = "runtime/agents/architect.md"
_FN_INVENTORY = "docs/atlas.md"


@pytest.fixture
def conn():
    """The HC under test scans tier files only; it never reads *conn*."""
    return None


def _materialize(tmp_path: Path, files: Dict[str, str]) -> Path:
    for rel, content in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def _install_iter(
    monkeypatch: pytest.MonkeyPatch,
    repo_root: Path,
    tier_for: Dict[str, int],
) -> None:
    def fake_iter(
        repo: Path, tiers: Iterable[int] = (0, 2, 4, 5)
    ) -> Iterator[Tuple[int, Path]]:
        tier_set = set(tiers)
        for rel, tier in sorted(tier_for.items()):
            if tier in tier_set:
                yield tier, repo_root / rel

    monkeypatch.setattr(mod, "iter_tier_paths", fake_iter)
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(repo_root))


def _setup(tmp_path, monkeypatch, files, tier_for):
    _materialize(tmp_path, files)
    _install_iter(monkeypatch, tmp_path, tier_for)


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_progressive_disclosure_direction(conn, DoctorArgs(), rec)
    return rec


def _detail(rec: RecordCollector) -> str:
    return rec.results[0].detail


def test_check_a_positive_tier_0_cites_tier_5_skill(tmp_path, monkeypatch, conn):
    """Tier 0 file citing a Tier 5 SKILL.md fires backward-reference."""

    _setup(
        tmp_path,
        monkeypatch,
        {
            "AGENTS.md": f"See the [conduct skill]({_CONDUCT_SKILL}).\n",
            _CONDUCT_SKILL: "# conduct\n",
        },
        {"AGENTS.md": 0, _CONDUCT_SKILL: 5},
    )
    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert rec.results[0].check_id == HC_SLUG
    detail = _detail(rec)
    assert "tier 0 file references backward tier 5" in detail
    assert "conduct/SKILL.md" in detail


@pytest.mark.parametrize(
    "files, tier_for",
    [
        # Tier 0 -> Tier 3 forward
        (
            {
                "AGENTS.md": f"See [inv]({_FN_INVENTORY}).\n",
                _FN_INVENTORY: "# inventory\n",
            },
            {"AGENTS.md": 0, _FN_INVENTORY: 3},
        ),
        # Tier 5 -> Tier 4 allowed
        (
            {
                _CONDUCT_SKILL: f"Dispatch [engineer]({_ENGINEER_AGENT}).\n",
                _ENGINEER_AGENT: "# engineer\n",
            },
            {_CONDUCT_SKILL: 5, _ENGINEER_AGENT: 4},
        ),
        # Tier 4 -> Tier 4 same-tier
        (
            {
                _ENGINEER_AGENT: f"With [arch]({_ARCHITECT_AGENT}).\n",
                _ARCHITECT_AGENT: "# architect\n",
            },
            {_ENGINEER_AGENT: 4, _ARCHITECT_AGENT: 4},
        ),
        # .py source citation exempt
        (
            {"AGENTS.md": "See runtime/api/engines/doctor.py.\n"},
            {"AGENTS.md": 0},
        ),
    ],
    ids=["tier-0-to-3", "tier-5-to-4", "tier-4-same", "py-exempt"],
)
def test_check_a_negative_allowed_citations(
    tmp_path, monkeypatch, conn, files, tier_for
):
    """Forward / same-tier / .py citations all PASS Check A."""

    _setup(tmp_path, monkeypatch, files, tier_for)
    detail = _detail(_run(conn))
    assert "backward tier" not in detail
    assert "is not classified" not in detail


def test_check_b_positive_vague_denial_without_function_id(
    tmp_path, monkeypatch, conn
):
    """Vague-denial phrase without a registered function id fires."""

    _setup(
        tmp_path,
        monkeypatch,
        {_CONDUCT_SKILL: "When mutating, use function dispatch.\n"},
        {_CONDUCT_SKILL: 5},
    )
    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "vague-denial phrase used without a concrete registered" in _detail(rec)


@pytest.mark.parametrize(
    "body",
    [
        f"Use function dispatch (e.g., {REQUIRED_FUNCTION_IDS[0]}).\n",
        "Use function dispatch — no registered function id exists yet.\n",
    ],
    ids=["names-function-id", "explicit-absence-note"],
)
def test_check_b_negative_vague_denial_exemptions(
    tmp_path, monkeypatch, conn, body
):
    """Line names a concrete id OR carries the absence note — PASSES."""

    _setup(tmp_path, monkeypatch, {_CONDUCT_SKILL: body}, {_CONDUCT_SKILL: 5})
    assert "vague-denial" not in _detail(_run(conn))


def test_archive_path_does_not_fire(tmp_path, monkeypatch, conn):
    """``docs/archive/`` content is exempt by default (NFR-5)."""

    rel = "docs/archive/decisions/legacy.md"
    body = f"use function dispatch.\nSee [conduct]({_CONDUCT_SKILL}).\n"
    _materialize(tmp_path, {rel: body, _CONDUCT_SKILL: "# conduct\n"})
    monkeypatch.setattr(
        mod, "iter_tier_paths", lambda repo, tiers=(0, 2, 4, 5): iter([(6, repo / rel)])
    )
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(tmp_path))

    assert _run(conn).results[0].result == "PASS"


def test_unclassified_path_one_warn_per_unique(tmp_path, monkeypatch, conn):
    """Two citations of the same unclassified path emit one WARN."""

    unknown = "docs/unknown/area.md"
    _setup(
        tmp_path,
        monkeypatch,
        {
            _ENGINEER_AGENT: f"See [unknown]({unknown}) for context.\n",
            _ARCHITECT_AGENT: f"Also referenced: [unknown]({unknown}).\n",
        },
        {_ENGINEER_AGENT: 4, _ARCHITECT_AGENT: 4},
    )
    rec = _run(conn)
    detail = _detail(rec)
    assert detail.count("is not classified") == 1
    assert unknown in detail


def test_self_skips_when_repo_root_unresolvable(monkeypatch, conn):
    """Falsy ``_resolve_repo_root`` → PASS with "skip" detail."""

    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: None)
    rec = _run(conn)
    assert rec.results[0].result == "PASS"
    assert "skip" in rec.results[0].detail.lower()


def test_required_function_ids_consumed_from_upstream():
    """HC consumes REQUIRED_FUNCTION_IDS from the Task 001 scaffold."""

    from yoke_core.engines import doctor_registry_tier_discipline as up

    assert mod.REQUIRED_FUNCTION_IDS is up.REQUIRED_FUNCTION_IDS


def test_tier_direction_rules_shape():
    """TIER_DIRECTION_RULES has the documented tiers and forward shape."""

    assert set(TIER_DIRECTION_RULES) == {0, 2, 4, 5, 6}
    for tier in (0, 2, 4, 5):
        assert tier in TIER_DIRECTION_RULES[tier]  # same-tier allowed
        assert 1 in TIER_DIRECTION_RULES[tier]  # Tier 1 (in-memory) reachable
    assert 4 in TIER_DIRECTION_RULES[5]  # skill -> agent allowed
    assert 5 not in TIER_DIRECTION_RULES[0]  # AGENTS.md cannot cite skill


def test_vague_denial_markers_contains_canonical_phrases():
    """Module-level constant exposes the spec-canonical phrases."""

    assert "use function dispatch" in VAGUE_DENIAL_MARKERS
    assert "via the function-call surface" in VAGUE_DENIAL_MARKERS

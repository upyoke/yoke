"""Unit tests for HC-packet-tier-completeness.

Tests monkeypatch ``SKILL_SCAN_TARGETS``, ``render_role_packet``, and
``_resolve_repo_root`` so fixtures are self-contained. One negative
test exercises the live packet via real ``render_role_packet``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.engines import doctor_hc_packet_tier_completeness as mod
from yoke_core.engines.doctor_hc_packet_tier_completeness import (
    HC_SLUG,
    SKILL_SCAN_TARGETS,
    hc_packet_tier_completeness,
)
from yoke_core.engines.doctor_registry_tier_discipline import (
    REQUIRED_FUNCTION_IDS,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


# --- Fixtures and helpers ---


@pytest.fixture
def conn():
    """The HC under test scans files and packets only; it never reads *conn*."""
    return None


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_packet_tier_completeness(conn, DoctorArgs(), rec)
    return rec


def _detail(rec: RecordCollector) -> str:
    return rec.results[0].detail


def _install_repo(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(repo_root))


def _install_targets(
    monkeypatch: pytest.MonkeyPatch, targets: dict[str, tuple[str, ...]]
) -> None:
    monkeypatch.setattr(mod, "SKILL_SCAN_TARGETS", targets)


def _install_packet(
    monkeypatch: pytest.MonkeyPatch, role_to_text: dict[str, str]
) -> None:
    def fake(role: str) -> str:
        return role_to_text.get(role, "")

    monkeypatch.setattr(mod, "render_role_packet", fake)


def _write(tmp_path: Path, rel: str, body: str) -> None:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


# Canonical complete-envelope packet body the live packet exposes.
# Used by tests that need Check B to PASS so they can isolate Check A.
_GOOD_ENVELOPE_BLOCK = (
    "actor / session_id / actor_id / preconditions / options envelope. "
    f"Function id: {REQUIRED_FUNCTION_IDS[0]}.\n"
)


def _packet_section(topic: str, table_bullets: list[tuple[str, str]]) -> str:
    """Render one section header + its table bullets.

    ``table_bullets`` is a list of (table_name, bullet_body) where
    ``bullet_body`` is the prose after the canonical bullet head.
    """
    lines = [f"### DB Quick Reference — {topic} (test fixture)\n"]
    for table, body in table_bullets:
        lines.append(f"- **`{table}`** — {body}")
    return "".join(lines) + "\n"


# --- AC-7 Check A: anchor-positive case ---


def test_check_a_anchor_positive_qa_requirements_required(
    tmp_path, monkeypatch, conn
):
    """qa bullet omits ``required`` referenced by skill prose — HC fires."""

    rel = ".agents/skills/yoke/test/dummy.md"
    _write(tmp_path, rel, "Set qa_requirements.required = True before run.\n")
    _install_repo(monkeypatch, tmp_path)
    _install_targets(monkeypatch, {"main_agent": (rel,)})
    packet = _GOOD_ENVELOPE_BLOCK + _packet_section(
        "qa", [("qa_requirements", "`id, item_id, qa_kind`\n")]
    )
    _install_packet(monkeypatch, {"main_agent": packet})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert HC_SLUG == rec.results[0].check_id
    assert "missing column qa_requirements.required" in _detail(rec)


# --- AC-7 Anchor distinguisher (column in neighbouring bullet, not target) ---


def test_check_a_anchor_distinguisher_worktree_in_epic_tasks_bullet(
    tmp_path, monkeypatch, conn
):
    """`worktree` lives in epic_tasks bullet, not items bullet — fire."""

    rel = ".agents/skills/yoke/test/dummy.md"
    _write(tmp_path, rel, "Inspect items.worktree when activating.\n")
    _install_repo(monkeypatch, tmp_path)
    _install_targets(monkeypatch, {"main_agent": (rel,)})
    packet = _GOOD_ENVELOPE_BLOCK + _packet_section(
        "core",
        [
            ("items", "`id, title, status`\n"),
            ("epic_tasks", "`id, epic_id, task_num, worktree`\n"),
        ],
    )
    _install_packet(monkeypatch, {"main_agent": packet})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "missing column items.worktree" in _detail(rec)


# --- AC-7 Check B (main_agent envelope) ---


def test_check_b_envelope_missing_actor(tmp_path, monkeypatch, conn):
    """Envelope omits ``actor`` — HC fires."""

    _install_repo(monkeypatch, tmp_path)
    _install_targets(monkeypatch, {"main_agent": ()})
    bad = (
        "session_id / actor_id / preconditions / options envelope. "
        f"Function id: {REQUIRED_FUNCTION_IDS[0]}.\n"
    )
    _install_packet(monkeypatch, {"main_agent": bad})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "envelope field 'actor' missing" in _detail(rec)


def test_check_b_envelope_missing_function_id(tmp_path, monkeypatch, conn):
    """Packet omits every REQUIRED_FUNCTION_IDS substring — HC fires."""

    _install_repo(monkeypatch, tmp_path)
    _install_targets(monkeypatch, {"main_agent": ()})
    bad = "actor / session_id / actor_id / preconditions / options.\n"
    _install_packet(monkeypatch, {"main_agent": bad})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert "REQUIRED_FUNCTION_IDS" in _detail(rec)


# --- AC-7 Check B negative: live packet passes ---


def test_check_b_negative_live_main_agent_packet_passes_envelope(
    tmp_path, monkeypatch, conn
):
    """Live ``render_role_packet('main_agent')`` passes Check B."""

    _install_repo(monkeypatch, tmp_path)
    _install_targets(monkeypatch, {"main_agent": ()})

    rec = _run(conn)
    detail = _detail(rec)
    assert "envelope field" not in detail
    assert "REQUIRED_FUNCTION_IDS" not in detail


# --- AC-7 Edge: missing skill files emit staleness WARN (not FAIL) ---


def test_missing_skill_file_emits_staleness_warn(tmp_path, monkeypatch, conn):
    """Missing path → distinct WARN, not a FAIL."""

    _install_repo(monkeypatch, tmp_path)
    rel = ".agents/skills/yoke/missing/SKILL.md"
    _install_targets(monkeypatch, {"main_agent": (rel,)})
    _install_packet(monkeypatch, {"main_agent": _GOOD_ENVELOPE_BLOCK})

    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    detail = _detail(rec)
    assert "SKILL_SCAN_TARGETS contains missing skill path" in detail
    assert rel in detail


def test_missing_skill_file_emits_one_finding_per_path(
    tmp_path, monkeypatch, conn
):
    """One staleness finding per missing path."""

    _install_repo(monkeypatch, tmp_path)
    rel_a = ".agents/skills/yoke/missing-a/SKILL.md"
    rel_b = ".agents/skills/yoke/missing-b/SKILL.md"
    _install_targets(monkeypatch, {"main_agent": (rel_a, rel_b)})
    _install_packet(monkeypatch, {"main_agent": _GOOD_ENVELOPE_BLOCK})

    rec = _run(conn)
    detail = _detail(rec)
    assert detail.count("missing skill path") == 2
    assert rel_a in detail and rel_b in detail


# --- AC-7 Edge: empty SKILL_SCAN_TARGETS[role] skips role cleanly ---


def test_empty_targets_for_role_skips_cleanly(tmp_path, monkeypatch, conn):
    """Empty SKILL_SCAN_TARGETS[role] adds no Check A findings."""

    _install_repo(monkeypatch, tmp_path)
    _install_targets(monkeypatch, {"main_agent": (), "engineer_agent": ()})
    _install_packet(
        monkeypatch,
        {"main_agent": _GOOD_ENVELOPE_BLOCK, "engineer_agent": ""},
    )

    rec = _run(conn)
    detail = _detail(rec)
    assert "missing column" not in detail
    assert "missing skill path" not in detail


# --- AC-6: other roles skip Check B ---


def test_engineer_agent_does_not_trigger_envelope_check(
    tmp_path, monkeypatch, conn
):
    """Check B is main_agent only."""

    _install_repo(monkeypatch, tmp_path)
    _install_targets(monkeypatch, {"engineer_agent": ()})
    _install_packet(
        monkeypatch,
        {"main_agent": _GOOD_ENVELOPE_BLOCK, "engineer_agent": "irrelevant"},
    )

    rec = _run(conn)
    detail = _detail(rec)
    assert "envelope field" not in detail
    assert "REQUIRED_FUNCTION_IDS" not in detail

def test_self_skips_when_repo_root_unresolvable(monkeypatch, conn):
    """Falsy ``_resolve_repo_root`` → PASS with "skip" detail."""

    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: None)
    rec = _run(conn)
    assert rec.results[0].result == "PASS"
    assert "skip" in rec.results[0].detail.lower()

def test_skill_scan_targets_covers_every_role():
    """Every role in ROLE_TOPICS has an entry in SKILL_SCAN_TARGETS."""

    from yoke_core.domain.schema_api_context_seed import ROLE_TOPICS

    for role in ROLE_TOPICS:
        assert role in SKILL_SCAN_TARGETS, f"missing SKILL_SCAN_TARGETS[{role}]"


def test_required_function_ids_consumed_from_upstream():
    """HC consumes REQUIRED_FUNCTION_IDS from the Task 001 scaffold."""

    from yoke_core.engines import doctor_registry_tier_discipline as up

    assert mod.REQUIRED_FUNCTION_IDS is up.REQUIRED_FUNCTION_IDS


def test_required_function_ids_are_registered():
    """Every required function id resolves through the live function registry."""
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_registry import lookup

    register_all_handlers()
    assert all(lookup(fn) is not None for fn in REQUIRED_FUNCTION_IDS)

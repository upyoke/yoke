"""HC-skill-entrypoint-disclosure regressions plus the live corpus measurement.

The bad shapes are injected into a tmp skill tree so the rules are exercised
without depending on the real corpus staying broken. One test then runs the
same scan over this repo's own `.agents/skills/yoke`, which is both the gate
and the recorded before/after measurement for the entrypoint channel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from yoke_contracts.startup_context_budget import SKILL_ENTRYPOINT_BYTES
from yoke_project_checks import check_skill_entrypoint_disclosure as mod
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


REPO_ROOT = Path(__file__).resolve().parents[3]

_ROUTING_ENTRYPOINT = """# /yoke sample

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1. Start | Invoked | [`first.md`](first.md) |
"""


def _materialize(root: Path, files: Dict[str, str]) -> Path:
    skills = root / mod.SKILL_ROOT
    for rel, content in files.items():
        target = skills / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def _scan(root: Path) -> list[str]:
    findings, _ = mod._scan(root)
    return findings


def test_entrypoint_within_budget_and_routing_passes(tmp_path: Path) -> None:
    root = _materialize(tmp_path, {
        "sample/SKILL.md": _ROUTING_ENTRYPOINT,
        "sample/first.md": "# first\n\nDo the thing.\n",
    })
    assert _scan(root) == []


def test_oversized_entrypoint_is_reported_with_its_budget(tmp_path: Path) -> None:
    root = _materialize(tmp_path, {
        "sample/SKILL.md": _ROUTING_ENTRYPOINT + "x" * SKILL_ENTRYPOINT_BYTES,
        "sample/first.md": "# first\n",
    })
    findings = _scan(root)
    assert len(findings) == 1
    assert "entrypoint spends" in findings[0]
    assert str(SKILL_ENTRYPOINT_BYTES) in findings[0]


def test_phase_references_without_a_phase_map_are_reported(tmp_path: Path) -> None:
    root = _materialize(tmp_path, {
        "sample/SKILL.md": "# /yoke sample\n\nSee [`first.md`](first.md).\n",
        "sample/first.md": "# first\n",
    })
    findings = _scan(root)
    assert len(findings) == 1
    assert "no phase map" in findings[0]


def test_ordering_a_reference_read_completely_is_reported(tmp_path: Path) -> None:
    root = _materialize(tmp_path, {
        "sample/SKILL.md": (
            _ROUTING_ENTRYPOINT + "\nRead [`first.md`](first.md) completely.\n"
        ),
        "sample/first.md": "# first\n",
    })
    findings = _scan(root)
    assert len(findings) == 1
    assert "read 'completely' from the entrypoint" in findings[0]


def test_orphaned_reference_is_reported(tmp_path: Path) -> None:
    root = _materialize(tmp_path, {
        "sample/SKILL.md": _ROUTING_ENTRYPOINT,
        "sample/first.md": "# first\n",
        "sample/stranded.md": "# stranded\n",
    })
    findings = _scan(root)
    assert len(findings) == 1
    assert "cited by nothing in its own command" in findings[0]


def test_entrypoint_only_command_needs_no_phase_map(tmp_path: Path) -> None:
    root = _materialize(tmp_path, {"sample/SKILL.md": "# /yoke sample\n\nAll of it.\n"})
    assert _scan(root) == []


def test_live_corpus_is_within_budget_and_reports_its_measurement() -> None:
    """The gate over this repo, and the number the condensation is measured by."""
    findings, measurements = mod._scan(REPO_ROOT)
    assert findings == [], "\n".join(findings)
    sizes = {entry.split("=")[0]: int(entry.split("=")[1]) for entry in measurements}
    assert sizes, "no /yoke commands discovered"
    assert max(sizes.values()) <= SKILL_ENTRYPOINT_BYTES
    # The condensed corpus measured 112182 bytes across 26 entrypoints; the
    # ceiling leaves room for ordinary prose edits without inviting regrowth.
    assert sum(sizes.values()) <= 130_000, sorted(sizes.items())


def test_check_records_a_pass_with_the_measurement(monkeypatch, tmp_path: Path) -> None:
    root = _materialize(tmp_path, {
        "sample/SKILL.md": _ROUTING_ENTRYPOINT,
        "sample/first.md": "# first\n",
    })
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(root))
    rec = RecordCollector()
    mod.hc_skill_entrypoint_disclosure(None, DoctorArgs(), rec)
    (record,) = [r for r in rec.results if r.check_id == mod.HC_SLUG]
    assert record.result == "PASS"
    assert "sample=" in record.detail

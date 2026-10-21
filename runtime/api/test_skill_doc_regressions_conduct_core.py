"""Conduct activation gate scoping and phase-file layout contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    REPO,
    SKILLS,
    _count_invocations,
    _read,
)


# ---------------------------------------------------------------------------
# TestConductActivationGate — test-conduct-activation-gate.sh
# ---------------------------------------------------------------------------


class TestConductActivationGate:
    """Conduct start gate must pass ``--gate-point activation``.

    The conduct entry gate (``conduct/entry-gates.md``) must use the
    activation-scoped hard-block check so integration/closure edges don't
    block conduct dispatch.
    """

    @pytest.fixture
    def conduct_dir(self) -> Path:
        d = SKILLS / "conduct"
        assert d.is_dir()
        return d

    def test_skill_has_no_unscoped_hard_blocks_call(self, conduct_dir: Path):
        text = _read(conduct_dir / "entry-gates.md")
        _, unscoped = _count_invocations(text, "check_hard_blocks")
        assert unscoped == 0, (
            f"conduct/SKILL.md has {unscoped} unscoped check_hard_blocks call(s); "
            "all must use --gate-point"
        )

    def test_entry_activation_has_no_unscoped_hard_blocks_call(self, conduct_dir: Path):
        text = _read(conduct_dir / "entry-activation.md")
        _, unscoped = _count_invocations(text, "check_hard_blocks")
        assert unscoped == 0


# ---------------------------------------------------------------------------
# TestConductPhasedRead
# ---------------------------------------------------------------------------


class TestConductPhasedRead:
    """Conduct router must have phased-read plan and bounded phase files."""

    @pytest.fixture
    def conduct_dir(self) -> Path:
        d = SKILLS / "conduct"
        assert d.is_dir()
        return d

    PHASE_FILES = (
        "entry-activation.md",
        "engineer-tester-loop.md",
        "simulation-gate.md",
        "cleanup-report.md",
    )

    def test_all_phase_files_exist(self, conduct_dir: Path):
        missing = [f for f in self.PHASE_FILES if not (conduct_dir / f).is_file()]
        assert not missing, f"conduct phase files missing: {missing}"

    def test_phase_files_under_400_lines(self, conduct_dir: Path):
        over = []
        for f in self.PHASE_FILES:
            lines = len(_read(conduct_dir / f).splitlines())
            if lines > 400:
                over.append(f"{f} ({lines} lines)")
        assert not over, f"phase files over 400 lines: {over}"

    def test_router_is_the_only_phase_index(self, conduct_dir: Path):
        """One phase table, on the entrypoint. A second copy drifts."""
        assert not (conduct_dir / "single-item.md").exists()
        router = _read(conduct_dir / "SKILL.md")
        assert len(router.splitlines()) < 120, (
            "the entrypoint routes, it does not teach"
        )
        for phase_file in self.PHASE_FILES:
            assert phase_file in router, phase_file


# ---------------------------------------------------------------------------
# TestConductFanOutEntryPath — task-level fan-out restoration
# ---------------------------------------------------------------------------


class TestConductFanOutEntryPath:
    """The fan-out decision record stays on file."""

    DECISION = REPO / "docs/archive/decisions/conduct-task-fanout-restore.md"

    def test_decision_record_exists(self):
        assert self.DECISION.is_file(), f"missing {self.DECISION}"

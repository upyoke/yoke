"""Doc regressions for conduct router activation, phased read, and sync cleanup.

Covers ``test-conduct-activation-gate.sh`` plus the phased-read and
sync-cleanup regressions that share the conduct skill directory. The
simulation-readback class lives in
``test_skill_doc_regressions_conduct_simulation.py`` to keep this file under
the 350-line cap.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    REPO,
    SKILLS,
    _count_invocations,
    _read,
    _read_dispatch_context,
)


# ---------------------------------------------------------------------------
# TestConductActivationGate — test-conduct-activation-gate.sh
# ---------------------------------------------------------------------------


class TestConductActivationGate:
    """Conduct start gate must pass ``--gate-point activation``.

    Both conduct entry surfaces (``conduct/SKILL.md`` and
    ``conduct/entry-activation.md``) must use activation-scoped hard-block
    checks so integration/closure edges don't block conduct dispatch.
    """

    @pytest.fixture
    def conduct_dir(self) -> Path:
        d = SKILLS / "conduct"
        assert d.is_dir()
        return d

    def test_skill_has_activation_gate_point(self, conduct_dir: Path):
        text = _read(conduct_dir / "SKILL.md")
        assert "--gate-point activation" in text, (
            "conduct/SKILL.md missing --gate-point activation"
        )

    def test_skill_has_no_unscoped_hard_blocks_call(self, conduct_dir: Path):
        text = _read(conduct_dir / "SKILL.md")
        _, unscoped = _count_invocations(text, "check_hard_blocks")
        assert unscoped == 0, (
            f"conduct/SKILL.md has {unscoped} unscoped check_hard_blocks call(s); "
            "all must use --gate-point"
        )

    def test_entry_activation_has_activation_gate_point(self, conduct_dir: Path):
        text = _read(conduct_dir / "entry-activation.md")
        assert "--gate-point activation" in text

    def test_entry_activation_has_no_unscoped_hard_blocks_call(self, conduct_dir: Path):
        text = _read(conduct_dir / "entry-activation.md")
        _, unscoped = _count_invocations(text, "check_hard_blocks")
        assert unscoped == 0

    def test_no_legacy_all_blockers_wording(self, conduct_dir: Path):
        """drop the old 'all blockers must reach done' phrasing."""
        pattern = re.compile(r"All blockers must reach.*done.*before")
        for rel in ("SKILL.md", "entry-activation.md"):
            assert not pattern.search(
                _read(conduct_dir / rel)
            ), f"legacy 'all blockers must reach done' wording found in conduct/{rel}"


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

    def test_router_has_phased_read_plan(self, conduct_dir: Path):
        text = _read(conduct_dir / "SKILL.md")
        assert "Phased-Read Plan" in text
        assert "entry-activation.md" in text
        assert "engineer-tester-loop.md" in text
        assert "simulation-gate.md" in text
        assert "cleanup-report.md" in text

    def test_router_has_offset_limit_guidance(self, conduct_dir: Path):
        text = _read(conduct_dir / "SKILL.md")
        assert "offset" in text.lower()
        assert "limit" in text.lower()

    def test_router_has_successor_owner_map(self, conduct_dir: Path):
        text = _read(conduct_dir / "SKILL.md")
        assert "Successor owner map" in text
        # Verify the owner-map points at the real phase files, not legacy
        # ticket breadcrumbs.
        for owner_file in (
            "engineer-tester-loop.md",
            "dispatch-context.md",
            "entry-activation.md",
            "cleanup-report.md",
            "simulation-gate.md",
        ):
            assert owner_file in text, f"Successor owner map missing {owner_file}"

    def test_dispatch_context_has_section_index(self, conduct_dir: Path):
        text = _read(conduct_dir / "dispatch-context.md")
        assert "Section Index" in text
        assert "Safe-read guidance" in text

    def test_single_item_is_thin_index(self, conduct_dir: Path):
        text = _read(conduct_dir / "single-item.md")
        lines = len(text.splitlines())
        assert lines < 60, (
            f"single-item.md should be a thin index (<60 lines), got {lines}"
        )


# ---------------------------------------------------------------------------
# TestConductSyncCleanupRegressions
# ---------------------------------------------------------------------------


class TestConductSyncCleanupRegressions:
    """Conduct auto-sync and cleanup must not assume tracked worktree diffs."""

    CONDUCT = SKILLS / "conduct"
    STATUS_READY = "status " + "ready"
    PLANNED_TO_READY = "planned to " + "ready"
    RESOLVE_PATHS_HELPER = "resolve-paths" + ".sh"

    def test_dispatch_context_no_stale_ready_wording(self):
        """dispatch-context.md must not reference stale ready-era wording."""
        text = _read(self.CONDUCT / "dispatch-context.md")
        assert self.STATUS_READY not in text, (
            f"dispatch-context.md still contains stale '{self.STATUS_READY}' wording (YOK-1212 AC-2)"
        )
        assert self.PLANNED_TO_READY not in text, (
            f"dispatch-context.md still contains stale '{self.PLANNED_TO_READY}' wording (YOK-1212 AC-2)"
        )

    def test_dispatch_context_uses_implementing_lifecycle(self):
        """dispatch-context.md auto-sync must use 'implementing', not 'ready'."""
        text = _read_dispatch_context(self.CONDUCT / "dispatch-context.md")
        assert "status implementing" in text, (
            "dispatch-context.md auto-sync should advance to 'implementing' (YOK-1212 AC-2)"
        )

    def test_entry_activation_no_stale_ready_wording(self):
        """entry-activation.md must not reference stale ready-era wording in auto-sync."""
        text = _read(self.CONDUCT / "entry-activation.md")
        assert self.PLANNED_TO_READY not in text, (
            f"entry-activation.md still contains stale '{self.PLANNED_TO_READY}' wording (YOK-1212)"
        )

    def test_entry_activation_documents_no_diff_success(self):
        """entry-activation.md must document that no tracked diff is a valid sync outcome."""
        text = _read(self.CONDUCT / "entry-activation.md")
        assert "no tracked" in text.lower() or "nothing to commit" in text.lower(), (
            "entry-activation.md must document that DB-only sync with no tracked diff is valid (YOK-1212 AC-1)"
        )

    def test_dispatch_context_documents_no_diff_success(self):
        """dispatch-context.md must document that no tracked diff is a valid sync outcome."""
        text = _read_dispatch_context(self.CONDUCT / "dispatch-context.md")
        assert "no tracked" in text.lower() or "nothing to commit" in text.lower(), (
            "dispatch-context.md must document that DB-only sync with no tracked diff is valid (YOK-1212 AC-1)"
        )

    def test_sync_paths_forbid_staging_legacy_root_db_files(self):
        """Auto-sync paths must explicitly forbid staging legacy DB files."""
        for fname in ("entry-activation.md", "dispatch-context.md"):
            text = _read(self.CONDUCT / fname)
            assert "legacy root db files" in text.lower(), (
                f"{fname} must mention legacy root DB staging prohibition"
            )

    def test_cleanup_uses_main_root_not_rev_parse(self):
        """cleanup-report.md must use MAIN_ROOT, not git rev-parse --show-toplevel in code blocks."""
        text = _read(self.CONDUCT / "cleanup-report.md")
        # Extract code blocks and check that none use rev-parse for root resolution
        in_code = False
        for line in text.splitlines():
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code and "git rev-parse --show-toplevel" in line:
                raise AssertionError(
                    "cleanup-report.md code block uses git rev-parse --show-toplevel "
                    "instead of MAIN_ROOT (YOK-1212 AC-4)"
                )
        assert "MAIN_ROOT" in text, (
            "cleanup-report.md must reference MAIN_ROOT for main-repo-root resolution (YOK-1212 AC-4)"
        )

    def test_cleanup_temp_loop_is_null_safe(self):
        """cleanup-report.md temp cleanup must avoid shell-glob nomatch failures."""
        text = _read(self.CONDUCT / "cleanup-report.md")
        assert 'find "$_yoke_dir" -maxdepth 1 -type f' in text, (
            "cleanup-report.md temp cleanup must use find-based matching for zsh/bash safety (YOK-1212 AC-5)"
        )
        assert '[ -f "$_tmp" ] || continue' not in text, (
            "cleanup-report.md should not rely on [ -f ] shell-glob fallback for null-safety (YOK-1212 AC-5)"
        )

    def test_no_resolve_paths_sh_reference(self):
        """Conduct docs must not reference the retired path-helper script."""
        for fname in self.CONDUCT.iterdir():
            if fname.suffix == ".md":
                text = _read(fname)
                assert self.RESOLVE_PATHS_HELPER not in text, (
                    f"{fname.name} references retired {self.RESOLVE_PATHS_HELPER} (YOK-1212 AC-8)"
                )


# ---------------------------------------------------------------------------
# TestConductFanOutEntryPath — task-level fan-out restoration
# ---------------------------------------------------------------------------


class TestConductFanOutEntryPath:
    """Entry path and dispatch protocol must agree about parallelism."""

    CONDUCT = SKILLS / "conduct"
    DECISION = REPO / "docs/archive/decisions/conduct-task-fanout-restore.md"
    LEGACY_FLOW = "Epic Single-Item Flow"

    def test_decision_record_exists(self):
        assert self.DECISION.is_file(), f"missing {self.DECISION} (AC-1)"

    def test_entry_resolution_and_loop_route_fan_out(self):
        texts = [_read(self.CONDUCT / name) for name in (
            "entry-activation.md", "entry-activation-resolution.md", "engineer-tester-loop.md"
        )]
        required = (
            "Epic Task Fan-Out Flow", "_task_ids", "_batch_size",
            "_worktree_branch_${_task_id}", "_worktree_path_${_task_id}",
            "dispatch-context-dispatch.md", "dispatch-context-prompts.md",
            "Dispatched by conduct (task fan-out)",
        )
        missing = [n for n in required if not any(n in text for text in texts)]
        assert not missing, f"AC-2/AC-7/AC-10 missing {missing}"
        joined = "\n".join(texts)
        assert self.LEGACY_FLOW not in joined, "AC-7/AC-11"
        assert "Dispatched by conduct (single-item)" not in joined, "AC-7/AC-11"
        assert "If dispatchable task found: proceed with `_task_id`." not in joined, "AC-2"

    def test_dispatch_context_and_prompts_match_fan_out(self):
        context = _read(self.CONDUCT / "dispatch-context.md")
        prompts = _read(self.CONDUCT / "dispatch-context-prompts.md")
        epic_prompts = prompts.split("### Issue Item Tester Prompt Template", 1)[0]
        for needle in ("Epic Fan-Out Enumeration", "_task_ids", "_worktree_path_${_task_id}"):
            assert needle in context, f"AC-3/AC-10 missing {needle}"
        for needle in ("Implement YOK-{N} task {_task_id}", "Validate YOK-{N} task {_task_id}", "epic-task body-get --epic {_epic_id} --task-num {_task_id}"):
            assert needle in epic_prompts, f"AC-2 missing {needle}"
        for needle in (
            "Anticipated path coverage (pre-authorized)",
            "_anticipated_paths_block_{_task_id}",
            "## Anticipated Paths",
        ):
            assert needle in epic_prompts, f"YOK-1697 AC-5 missing {needle}"
        assert "If a dispatchable task is found: use its local ID" not in context, "AC-3"
        assert "Implement YOK-{_id}" not in epic_prompts, "AC-2"
        assert "items get YOK-{_id} spec" not in epic_prompts, "AC-2"

    def test_dispatch_protocol_remains_live(self):
        dispatch = _read(self.CONDUCT / "dispatch-context-dispatch.md")
        prompts = _read(self.CONDUCT / "dispatch-context-prompts.md")
        assert "Parallel Engineer Dispatch" in dispatch, "AC-3"
        assert "Parallel Tester Dispatch" in dispatch, "AC-3"
        assert "Dispatch ALL Engineers in parallel" in prompts, "AC-3"

    def test_legacy_flow_name_only_in_decision_record(self):
        offenders = [f.name for f in sorted(self.CONDUCT.glob("*.md")) if self.LEGACY_FLOW in _read(f)]
        assert not offenders, f"AC-11: legacy in conduct prose: {offenders}"


# TestConductPerTaskClaims — AC-5/AC-6/AC-7/AC-17 per-task epic_task wiring


class TestConductPerTaskClaims:
    CONDUCT = SKILLS / "conduct"

    def test_dispatch_acquires_per_task_claim(self):
        text = _read(self.CONDUCT / "engineer-tester-dispatch.md")
        for needle in ("yoke claims work acquire", "--epic-id",
                       "--task-num", "engineer dispatch",
                       "target_kind='epic_task'",
                       "HALT: engineer dispatch", "HALT: tester dispatch"):
            assert needle in text, f"dispatch.md missing: {needle}"

    def test_closeout_releases_per_task_claim(self):
        text = _read(self.CONDUCT / "engineer-tester-closeout.md")
        for needle in ("yoke claims work release", "--epic-id",
                       "--task-num", "tester return",
                       "never touches the parent"):
            assert needle in text.lower() or needle in text, (
                f"closeout.md missing: {needle}"
            )

    def test_loop_teaches_per_task_reentry_semantics(self):
        text = _read(self.CONDUCT / "engineer-tester-loop.md")
        for needle in ("Per-task work-claim re-entry semantics",
                       "Same-session re-acquire", "Other-session-held",
                       "Stale-by-absent-session", "chain_head_freshness",
                       "claim_conflict"):
            assert needle in text, f"loop.md missing: {needle}"

    def test_no_item_level_sibling_worktree_regression(self):
        # Per-task replacement, not item-level sibling inheritance.
        for fname in ("engineer-tester-dispatch.md",
                      "engineer-tester-closeout.md",
                      "engineer-tester-loop.md"):
            text = _read(self.CONDUCT / fname).lower()
            assert "sibling task worktree" not in text, (
                f"AC-17: {fname} references 'sibling task worktree'"
            )

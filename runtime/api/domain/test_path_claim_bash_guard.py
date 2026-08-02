"""Bash guard coverage — wrong-cwd vs out-of-claim narratives + AC checks."""

from __future__ import annotations

from typing import Dict

from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
from yoke_core.domain.path_claim_bash_guard import (
    decide_for_record,
    evaluate_payload,
)


def _claim_dict(
    *,
    claim_id: int = 99,
    integration_target: str = "main",
    state: str = "active",
    covered_paths: tuple = ("runtime/api/domain",),
    worktree_path: str = "/tmp/yoke-worktrees/YOK-1577",
    item_ref: str | None = None,
) -> Dict:
    claim = {
        "id": claim_id,
        "item_id": 1577,
        "integration_target": integration_target,
        "state": state,
        "covered_paths": covered_paths,
        "worktree_path": worktree_path,
    }
    if item_ref is not None:
        claim["item_ref"] = item_ref
    return claim


def _payload(*, command: str, cwd: str, session_id: str = "sess-A") -> Dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
        "session_id": session_id,
    }


class TestOutOfClaim:
    def test_rm_outside_coverage(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        payload = _payload(
            command="rm docs/oof.md",
            cwd=str(worktree),
        )
        verdict = evaluate_payload(payload, claim=claim)
        assert verdict.outcome == "deny"
        assert verdict.failure_mode == "out-of-claim"
        assert (
            "yoke claims path widen --claim-id 99 "
            '--add-paths docs/oof.md --reason "cover target path" '
            "--item YOK-1577"
        ) in verdict.narrative

    def test_out_of_claim_uses_resolved_public_ref(self, tmp_path):
        worktree = tmp_path / "item-worktree"
        worktree.mkdir()
        claim = _claim_dict(
            worktree_path=str(worktree),
            item_ref="BUZ-7",
        )
        verdict = evaluate_payload(
            _payload(command="rm docs/oof.md", cwd=str(worktree)),
            claim=claim,
        )
        assert "--item BUZ-7" in verdict.narrative
        assert "--item YOK-1577" not in verdict.narrative


class TestWrongCwd:
    def test_target_in_main_checkout_with_worktree_claim(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        main_repo = tmp_path / "main"
        (main_repo / "runtime/api/domain").mkdir(parents=True)
        target = main_repo / "runtime/api/domain/foo.py"
        target.write_text("# placeholder\n")
        claim = _claim_dict(worktree_path=str(worktree))
        payload = _payload(command="rm runtime/api/domain/foo.py", cwd=str(main_repo))
        verdict = evaluate_payload(payload, claim=claim)
        assert verdict.outcome == "deny"
        assert verdict.failure_mode == "wrong-cwd"
        assert "Wrong working tree" in verdict.narrative
        assert str(worktree) in verdict.narrative
        assert "yoke claims path widen --claim-id 99" in verdict.narrative
        assert "--add-paths runtime/api/domain/foo.py" in verdict.narrative
        assert "--item YOK-1577" in verdict.narrative


class TestInClaim:
    def test_rm_inside_worktree_coverage(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        (worktree / "runtime/api/domain").mkdir(parents=True)
        claim = _claim_dict(worktree_path=str(worktree))
        payload = _payload(
            command="rm runtime/api/domain/foo.py",
            cwd=str(worktree),
        )
        verdict = evaluate_payload(payload, claim=claim)
        assert verdict.outcome == "allow"


class TestTempScratch:
    def test_mktemp_variable_read_is_outside_claim_domain(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        payload = _payload(
            command=(
                "_ac_output_file=$(mktemp /tmp/advance-ac-check.XXXXXX); "
                'cat "$_ac_output_file"'
            ),
            cwd=str(worktree),
        )
        verdict = evaluate_payload(payload, claim=claim)
        assert verdict.outcome == "allow"


class TestAmbiguousFailClosed:
    def test_eval_ambiguous(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        payload = _payload(
            command="eval 'rm runtime/api/domain/foo.py'",
            cwd=str(worktree),
        )
        verdict = evaluate_payload(payload, claim=claim)
        assert verdict.outcome == "deny"
        assert (
            "Compound" in verdict.narrative or "ambiguous" in verdict.narrative.lower()
        )


class TestSuppression:
    def test_token_records_audit_evidence_and_allows(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        payload = _payload(
            command="rm docs/oof.md  # lint:no-worktree-path-check",
            cwd=str(worktree),
        )
        verdict = evaluate_payload(payload, claim=claim)
        assert verdict.outcome == "suppressed"


class TestNoClaim:
    def test_no_claim_allows_freely(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        payload = _payload(
            command="rm docs/anything.md",
            cwd=str(worktree),
        )
        verdict = evaluate_payload(payload, claim=None)
        assert verdict.outcome == "allow"


class TestReadOnlyInspection:
    def test_read_only_commands_allow_out_of_claim_paths(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        for command in (
            'grep -n "a\\|b" docs/outside.md',
            "rg needle docs",
            "sed -n '1,80p' docs/outside.md",
            "ls docs",
            "python3 -m yoke_core.domain.worktree_preflight --help",
            "git diff --name-only main...HEAD",
            "test -f docs/outside.md",
        ):
            verdict = evaluate_payload(
                _payload(command=command, cwd=str(worktree)),
                claim=claim,
            )
            assert verdict.outcome == "allow", command

    def test_read_with_write_redirection_still_blocks(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        verdict = evaluate_payload(
            _payload(
                command="grep needle docs/input.md > docs/out.txt",
                cwd=str(worktree),
            ),
            claim=claim,
        )
        assert verdict.outcome == "deny"
        assert verdict.bash_verb == "redirect"


class TestPipelineAdapter:
    def test_decide_for_record_routes_to_evaluate(self):
        from yoke_core.domain.observe_normalization import (
            TOOL_KIND_BASH,
            ToolEventRecord,
        )

        record = ToolEventRecord(
            tool_kind=TOOL_KIND_BASH,
            command="ls",
            session_id="sess-A",
            cwd="/tmp/somewhere",
        )
        # No claim resolved (live DB query won't find one for sess-A).
        assert decide_for_record(record) is None

    def test_decide_for_record_skips_other_kinds(self):
        from yoke_core.domain.observe_normalization import (
            TOOL_KIND_EDIT,
            ToolEventRecord,
        )

        record = ToolEventRecord(
            tool_kind=TOOL_KIND_EDIT, changed_paths=["x"], session_id="sess-A"
        )
        assert decide_for_record(record) is None


class TestHookOrdering:
    def test_lint_session_cwd_precedes_bash_guard(self):
        chain = ordered_pipeline_for("PreToolUse", "Bash")
        # lint_session_cwd must come before path_claim_bash_guard.
        assert "yoke_core.domain.lint_session_cwd" in chain
        assert "yoke_core.domain.path_claim_bash_guard" in chain
        cwd_idx = chain.index("yoke_core.domain.lint_session_cwd")
        bash_idx = chain.index("yoke_core.domain.path_claim_bash_guard")
        assert cwd_idx < bash_idx

    def test_pre_edit_chain_orders_session_cwd_before_path_claim(self):
        edit_chain = ordered_pipeline_for("PreToolUse", "Edit")
        write_chain = ordered_pipeline_for("PreToolUse", "Write")
        for chain in (edit_chain, write_chain):
            assert "yoke_core.domain.lint_session_cwd" in chain
            assert "yoke_core.domain.path_claim_pre_edit_guard" in chain
            cwd_idx = chain.index("yoke_core.domain.lint_session_cwd")
            edit_idx = chain.index("yoke_core.domain.path_claim_pre_edit_guard")
            assert cwd_idx < edit_idx


class TestEventRegistrySeed:
    def test_event_names_registered_in_seed(self):
        from yoke_core.domain.event_registry_seed_path_claim_session_cwd import (
            seeded_event_names,
        )

        names = seeded_event_names()
        assert "PathClaimEditGuardDenied" in names
        assert "PathClaimBashGuardDenied" in names

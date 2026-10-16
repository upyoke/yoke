"""Bash path-claim targets resolve where the command really runs.

Relative targets join the command's execution directory (declared workdir,
then leading ``cd``) and any ``git -C`` directory before coverage is checked.
"""

from __future__ import annotations

from runtime.api.domain.test_path_claim_bash_guard import _claim_dict, _payload
from runtime.api.domain.test_path_claim_pre_edit_guard import _record
from yoke_contracts.hook_runner.session_cwd import client_machine_home_fact
from yoke_core.domain import path_claim_pre_edit_guard
from yoke_core.domain.path_claim_bash_guard import evaluate_payload
from yoke_core.domain.path_claim_bash_parser import extract_mutations


def _targets(command: str) -> list[str]:
    return [m.target_path for m in extract_mutations(command)]


class TestGitDirectoryOption:
    def test_relative_path_joins_absolute_git_dir(self):
        assert _targets("git -C /repo/.worktrees/lane rm src/a.py") == [
            "/repo/.worktrees/lane/src/a.py"
        ]

    def test_repeated_git_dirs_apply_in_order(self):
        assert _targets("git -C /repo -C .worktrees/lane rm src/a.py") == [
            "/repo/.worktrees/lane/src/a.py"
        ]

    def test_relative_git_dir_joins_execution_cwd(self):
        assert [
            m.target_path
            for m in extract_mutations("git -C lane restore -- src/a.py", "/repo")
        ] == ["/repo/lane/src/a.py"]

    def test_without_git_dir_path_stays_relative(self):
        assert [
            m.target_path for m in extract_mutations("git rm src/a.py", "/repo")
        ] == ["src/a.py"]

    def test_absolute_path_ignores_git_dir(self):
        assert _targets("git -C /repo rm /elsewhere/a.py") == ["/elsewhere/a.py"]

    def test_config_option_is_not_a_directory(self):
        assert _targets("git -c core.x=y rm src/a.py") == ["src/a.py"]


class TestGuardExecutionDirectory:
    def _lanes(self, tmp_path):
        main = tmp_path / "main"
        worktree = main / ".worktrees" / "YOK-1577"
        worktree.mkdir(parents=True)
        return main, worktree, _claim_dict(worktree_path=str(worktree))

    def test_git_dir_into_lane_from_main_is_covered(self, tmp_path):
        main, worktree, claim = self._lanes(tmp_path)
        verdict = evaluate_payload(
            _payload(
                command=f"git -C {worktree} rm runtime/api/domain/a.py",
                cwd=str(main),
            ),
            claim=claim,
        )
        assert verdict.outcome == "allow"

    def test_git_dir_into_lane_outside_claim_is_refused(self, tmp_path):
        main, worktree, claim = self._lanes(tmp_path)
        verdict = evaluate_payload(
            _payload(command=f"git -C {worktree} rm docs/oof.md", cwd=str(main)),
            claim=claim,
        )
        assert verdict.outcome == "deny"
        assert verdict.failure_mode == "out-of-claim"
        assert "--add-paths docs/oof.md" in verdict.narrative

    def test_relative_git_dir_joins_session_cwd(self, tmp_path):
        main, _worktree, claim = self._lanes(tmp_path)
        verdict = evaluate_payload(
            _payload(
                command="git -C .worktrees/YOK-1577 rm runtime/api/domain/a.py",
                cwd=str(main),
            ),
            claim=claim,
        )
        assert verdict.outcome == "allow"

    def test_declared_workdir_wins_over_session_cwd(self, tmp_path):
        main, worktree, claim = self._lanes(tmp_path)
        payload = _payload(command="rm runtime/api/domain/a.py", cwd=str(main))
        payload["tool_input"]["workdir"] = str(worktree)
        assert evaluate_payload(payload, claim=claim).outcome == "allow"

    def test_declared_workdir_outside_claim_is_refused(self, tmp_path):
        main, worktree, claim = self._lanes(tmp_path)
        payload = _payload(command="rm docs/oof.md", cwd=str(main))
        payload["tool_input"]["workdir"] = str(worktree)
        verdict = evaluate_payload(payload, claim=claim)
        assert verdict.outcome == "deny"
        assert verdict.failure_mode == "out-of-claim"

    def test_leading_cd_moves_execution_directory(self, tmp_path):
        main, worktree, claim = self._lanes(tmp_path)
        verdict = evaluate_payload(
            _payload(
                command=f"cd {worktree} && rm runtime/api/domain/a.py",
                cwd=str(main),
            ),
            claim=claim,
        )
        assert verdict.outcome == "allow"

    def test_leading_cd_home_uses_client_home_fact(self, tmp_path):
        main, worktree, claim = self._lanes(tmp_path)
        payload = _payload(
            command="cd ~/.worktrees/YOK-1577 && git rm runtime/api/domain/a.py",
            cwd=str(main),
        )
        payload.update(client_machine_home_fact(str(main)))
        assert evaluate_payload(payload, claim=claim).outcome == "allow"


class TestPerTaskLaneFromMain:
    def _seed(self, tmp_path, live_db):
        repo = tmp_path / "repo"
        for lane in ("lane-a", "lane-b"):
            (repo / ".worktrees" / lane / "runtime/api/domain").mkdir(parents=True)
        live_db(
            repo_path=repo,
            item_id=900,
            workflow_id="epic",
            chains=("lane-a", "lane-b"),
            covered_paths=("runtime/api/domain",),
            session_id="engineer-1",
        )
        return repo

    def test_git_dir_into_task_lane_is_covered(self, tmp_path, live_db):
        repo = self._seed(tmp_path, live_db)
        verdict = evaluate_payload(
            _payload(
                command=f"git -C {repo}/.worktrees/lane-a rm runtime/api/domain/a.py",
                cwd=str(repo),
                session_id="engineer-1",
            )
        )
        assert verdict.outcome == "allow"

    def test_declared_task_lane_workdir_is_covered(self, tmp_path, live_db):
        repo = self._seed(tmp_path, live_db)
        payload = _payload(
            command="git rm runtime/api/domain/b.py",
            cwd=str(repo),
            session_id="engineer-1",
        )
        payload["tool_input"]["workdir"] = f"{repo}/.worktrees/lane-b"
        assert evaluate_payload(payload).outcome == "allow"

    def test_git_dir_into_task_lane_outside_claim_is_refused(self, tmp_path, live_db):
        repo = self._seed(tmp_path, live_db)
        verdict = evaluate_payload(
            _payload(
                command=f"git -C {repo}/.worktrees/lane-a rm docs/never-covered.md",
                cwd=str(repo),
                session_id="engineer-1",
            )
        )
        assert verdict.outcome == "deny"
        assert "lane-a" in verdict.extra["expected_worktree_path"]


class TestWidenRecipePath:
    def test_absolute_edit_target_renders_repo_relative_widen(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        verdict = path_claim_pre_edit_guard.evaluate_payload(
            _record(changed_paths=(str(worktree / "docs/oof.md"),), cwd=str(worktree)),
            claim=_claim_dict(worktree_path=str(worktree)),
        )
        assert verdict.outcome == "deny"
        assert "--add-paths docs/oof.md --reason" in verdict.narrative

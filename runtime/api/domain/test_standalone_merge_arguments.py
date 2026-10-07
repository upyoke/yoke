"""Standalone merge permission and checkout binding arguments."""

from pathlib import Path
import pytest
from yoke_core.domain import standalone_item_merge as sim


class TestEngineArguments:
    def test_standalone_permission_and_item_identity_are_engine_arguments(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_run(args):
            captured["args"] = args
            return 0

        monkeypatch.setattr(
            "yoke_core.engines.merge_worktree.run",
            fake_run,
        )
        sim._run_merge_engine(
            item_id=7,
            repo_root="/project/repo",
            branch="descriptive-lane",
            source_sha="a" * 40,
            target="main",
            local_merge=True,
        )
        assert captured["args"].standalone is True
        assert captured["args"].item_id == 7
        assert captured["args"].expected_repo_root == "/project/repo"
        assert captured["args"].epic_ref is None

    def test_expected_checkout_mismatch_refuses(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from yoke_contracts.api.function_call import FunctionCallResponse
        from yoke_core.engines import merge_worktree_prepare as prep

        monkeypatch.setattr(
            "yoke_core.domain.worktree.resolve_main_root",
            lambda: str(tmp_path),
        )
        monkeypatch.setattr(prep, "_find_worktree", lambda *_a: str(tmp_path))
        monkeypatch.setattr(
            prep,
            "call_dispatcher",
            lambda **kwargs: FunctionCallResponse(
                success=True,
                function=kwargs["function_id"],
                version="v1",
                result={"item": {"id": 7, "project": {"slug": "yoke"}}},
            ),
        )

        with pytest.raises(RuntimeError, match="does not match"):
            prep.resolve_context(
                prep.MergeArgs(
                    branch="descriptive-lane",
                    item_id="YOK-7",
                    expected_repo_root=str(tmp_path / "other"),
                    standalone=True,
                )
            )

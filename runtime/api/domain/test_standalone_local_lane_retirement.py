"""Local-only merge retirement proves ancestry without fetching a remote."""

from types import SimpleNamespace

from yoke_core.engines import merge_landed_lane_cleanup as lane_cleanup


def test_lane_retirement_uses_the_local_target_without_a_remote(
    monkeypatch,
) -> None:
    commands = []

    def git(command, **_kwargs):
        commands.append(command)
        stdout = "" if command == ["remote"] else ""
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    released = []
    monkeypatch.setattr(lane_cleanup, "_lane_worktree", lambda *_a: None)
    monkeypatch.setattr(
        lane_cleanup,
        "release_lane_row",
        lambda item, branch, **_k: released.append((item, branch)),
    )
    monkeypatch.setattr(
        lane_cleanup,
        "delete_remote_branch_if_merged",
        lambda **_k: (_ for _ in ()).throw(AssertionError("no remote cleanup")),
    )

    warnings = lane_cleanup.prune_landed_lane(
        repo_root="/repo",
        branch="ITEM-7",
        target="main",
        item_id=7,
        run_git=git,
        emit=lambda *_a, **_k: None,
    )

    assert warnings == ()
    assert ["fetch", "origin", "main"] not in commands
    assert ["merge-base", "--is-ancestor", "ITEM-7", "main"] in commands
    assert released == [(7, "ITEM-7")]

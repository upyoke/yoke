"""Regression checks for item merge landing identity."""

from __future__ import annotations

from runtime.api.domain.test_item_merge_receipt_transport import (
    BRANCH as BRANCH,
    ITEM_REF as ITEM_REF,
    TARGET as TARGET,
    pytest as pytest,
    receipts as receipts,
)


class TestLandedMergeIdentity:
    """The recorded merge identity is the branch's own, or nothing."""

    def test_a_fresh_merge_takes_the_tip_it_just_created(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            receipts.git,
            "git_out",
            lambda *_a, **_k: "c" * 40,
        )

        assert (
            receipts.landed_merge_identity(
                item_id=ITEM_REF,
                branch=BRANCH,
                target=TARGET,
                repo_root="/repo",
                already=False,
                commit_sha="a" * 40,
            )
            == "c" * 40
        )

    def test_an_already_contained_branch_never_reads_the_moved_tip(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The tip belongs to whoever moved the target since."""
        monkeypatch.setattr(
            receipts.git,
            "git_out",
            lambda *_a, **_k: pytest.fail("read the target tip"),
        )
        monkeypatch.setattr(
            receipts,
            "landing_merge_commit",
            lambda *_a, **_k: "d" * 40,
        )

        assert (
            receipts.landed_merge_identity(
                item_id=ITEM_REF,
                branch=BRANCH,
                target=TARGET,
                repo_root="/repo",
                already=True,
                commit_sha="a" * 40,
            )
            == "d" * 40
        )

    def test_a_retry_falls_back_to_the_receipt_it_already_recorded(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(receipts, "landing_merge_commit", lambda *_a, **_k: "")
        monkeypatch.setattr(
            receipts,
            "load",
            lambda *_a, **_k: receipts.MergeReceipt(
                branch=BRANCH,
                target=TARGET,
                commit_sha="a" * 40,
                merge_sha="e" * 40,
            ),
        )

        assert (
            receipts.landed_merge_identity(
                item_id=ITEM_REF,
                branch=BRANCH,
                target=TARGET,
                repo_root="/repo",
                already=True,
                commit_sha="a" * 40,
            )
            == "e" * 40
        )

    def test_a_branch_that_carried_nothing_in_has_no_merge_identity(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(receipts, "landing_merge_commit", lambda *_a, **_k: "")
        monkeypatch.setattr(receipts, "load", lambda *_a, **_k: None)

        assert (
            receipts.landed_merge_identity(
                item_id=ITEM_REF,
                branch=BRANCH,
                target=TARGET,
                repo_root="/repo",
                already=True,
                commit_sha="a" * 40,
            )
            == ""
        )


class TestAnAbsorbedMergeIsNeverTheLanding:
    """A branch's own merge can be an ancestor without ever landing.

    When a sidecar branch merges the branch in and that sidecar is what
    reaches the base, the branch's own merge is an ancestor of the base
    while sitting off its first-parent chain entirely. Walking plain
    ancestry answered with that absorbed merge, which dated an item to a
    landing the trunk never took -- the shape a branch that lands twice
    produces, where the first merge is absorbed and a later one lands the
    result.
    """

    @staticmethod
    def _repo(tmp_path):
        import subprocess

        root = tmp_path / "absorbed"
        root.mkdir()

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(root), *args],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        git("init", "-b", "main")
        git("config", "user.email", "test@test.com")
        git("config", "user.name", "Test")
        (root / "base.txt").write_text("base\n")
        git("add", "base.txt")
        git("commit", "-m", "base")

        git("checkout", "-b", "feature")
        (root / "feature.txt").write_text("feature\n")
        git("add", "feature.txt")
        git("commit", "-m", "feature work")
        feature_head = git("rev-parse", "HEAD")

        # The sidecar takes the feature branch in. This merge carries the
        # feature commit but never joins main's first-parent chain.
        git("checkout", "-b", "sidecar", "main")
        (root / "sidecar.txt").write_text("sidecar\n")
        git("add", "sidecar.txt")
        git("commit", "-m", "sidecar work")
        git("merge", "--no-ff", "--no-edit", "feature")
        absorbed = git("rev-parse", "HEAD")

        git("checkout", "main")
        git("merge", "--no-ff", "--no-edit", "sidecar")
        landing = git("rev-parse", "HEAD")
        return root, feature_head, absorbed, landing

    def test_the_trunk_merge_is_answered_not_the_absorbed_one(
        self,
        tmp_path,
    ) -> None:
        root, feature_head, absorbed, landing = self._repo(tmp_path)

        resolved = receipts.landing_merge_commit(
            str(root),
            "main",
            feature_head,
        )

        assert resolved == landing
        assert resolved != absorbed

    def test_the_absorbed_merge_is_an_ancestor_all_the_same(
        self,
        tmp_path,
    ) -> None:
        """The absorbed merge is reachable -- which is why ancestry misled."""
        root, feature_head, absorbed, _landing = self._repo(tmp_path)

        assert receipts.git.is_ancestor(str(root), absorbed, "main")
        assert receipts.git.is_ancestor(str(root), feature_head, absorbed)

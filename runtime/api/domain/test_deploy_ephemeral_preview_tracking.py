"""One preview, one name, for the whole of one deploy.

A deploy writes several tracking updates — the row it creates, the flip to
running, and the mark a failure leaves. They have to name the same preview,
because a release preview and the branch a deploy happens to mention are
different rows: splitting them leaves the preview stuck at its initial
state while an unrelated branch is marked running or failed.
"""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import deploy_ephemeral
from runtime.api.domain.deploy_ephemeral_test_support import (
    SHA as _SHA,
    SLUG as _SLUG,
    install_ephemeral_project_source,
    scripted_runner as _scripted_runner,
)


class TestPreviewTrackingKey:
    def test_a_release_preview_tracks_only_its_own_key(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        """Every update in one deploy names the preview being deployed.

        The row this deploy creates, the row it flips to running, and the row
        a failure would mark are the same row. Tracking the later updates
        under the branch instead would leave the release preview stuck at its
        initial state while marking an unrelated branch's preview running.
        """
        project_root = install_ephemeral_project_source(tmp_path)
        runner = _scripted_runner()
        monkeypatch.setattr(deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID"))
        monkeypatch.setattr(
            "yoke_core.tools.step_runners.exec_health_check",
            lambda url, request_id="": 0,
        )
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            branch="some-branch",
            preview_key=_SLUG,
            revision=_SHA,
            repo_path=str(project_root),
            runner=runner,
            emit=lambda _l: None,
        )
        assert rc == 0
        keys = {call[1] for call in deploy_seams.calls}
        assert keys == {_SLUG}, "a branch name must never appear as a tracking key"
        assert deploy_seams.calls[-1][2]["status"] == "running"

    def test_a_failed_release_preview_marks_only_its_own_key(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        """A failure marks the preview that failed, not a branch."""
        project_root = install_ephemeral_project_source(tmp_path)
        runner = _scripted_runner()
        monkeypatch.setattr(deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID"))
        monkeypatch.setattr(
            deploy_ephemeral,
            "compose_bootstrap_and_up",
            mock.Mock(side_effect=deploy_ephemeral.EphemeralDeployError("boom")),
        )
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            branch="some-branch",
            preview_key=_SLUG,
            revision=_SHA,
            repo_path=str(project_root),
            runner=runner,
            emit=lambda _l: None,
        )
        assert rc == 1
        keys = {call[1] for call in deploy_seams.calls}
        assert keys == {_SLUG}, "a failure must not mark an unrelated branch"
        assert deploy_seams.calls[-1][2]["status"] == "failed"


class TestTheReservedFrozenNamespace:
    """A branch may be named anything; the frozen namespace belongs to runs.

    A preview at ``rel-<32 hex>`` promises that what it serves does not move
    while a candidate is under review. A branch slugifying onto that name
    would take over its directory, its port and its URL and serve a moving
    branch from them, so the branch-shaped paths refuse to land there.
    """

    COLLIDING = "rel-" + "f" * 32

    def test_a_branch_preview_cannot_take_over_a_frozen_occupancy(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        project_root = install_ephemeral_project_source(tmp_path)
        monkeypatch.setattr(deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID"))
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            branch=self.COLLIDING,
            repo_path=str(project_root),
            runner=_scripted_runner(),
            emit=lambda _l: None,
        )
        assert rc == 1
        assert deploy_seams.calls == []

    def test_a_frozen_preview_of_a_pinned_candidate_is_unaffected(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        """The same slug shape is exactly what a release preview deploys
        under, so the guard keys on what makes it frozen — a pinned
        revision — rather than on the shape alone."""
        project_root = install_ephemeral_project_source(tmp_path)
        monkeypatch.setattr(deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID"))
        monkeypatch.setattr(
            "yoke_core.tools.step_runners.exec_health_check",
            lambda url, request_id="": 0,
        )
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            branch="some-branch",
            preview_key=self.COLLIDING,
            revision=_SHA,
            repo_path=str(project_root),
            runner=_scripted_runner(),
            emit=lambda _l: None,
        )
        assert rc == 0
        assert {call[1] for call in deploy_seams.calls} == {self.COLLIDING}

    def test_teardown_by_branch_cannot_remove_a_frozen_occupancy(
        self, deploy_seams
    ):
        """Read backwards, the same takeover: a caller naming an occupancy it
        never created would delete the preview a release is still under
        review against."""
        rc = deploy_ephemeral.exec_ephemeral_teardown(
            "yoke",
            branch=self.COLLIDING,
            runner=_scripted_runner(),
            emit=lambda _l: None,
        )
        assert rc == 1
        assert deploy_seams.calls == []

    def test_the_owning_release_can_still_tear_its_own_preview_down(
        self, deploy_seams
    ):
        rc = deploy_ephemeral.exec_ephemeral_teardown(
            "yoke",
            preview_key=self.COLLIDING,
            frozen=True,
            runner=_scripted_runner(),
            emit=lambda _l: None,
        )
        assert rc == 0
        assert {call[1] for call in deploy_seams.calls} == {self.COLLIDING}

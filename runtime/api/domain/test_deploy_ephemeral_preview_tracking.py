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
from yoke_core.domain.deploy_ephemeral_occupancy import preview_slug
from yoke_core.domain.deploy_preview_dispatch_boundary import (
    release_preview_identity,
)
from yoke_core.domain.ephemeral_substrate import is_release_preview_slug
from runtime.api.domain.deploy_ephemeral_test_support import (
    SHA as _SHA,
    install_ephemeral_project_source,
    scripted_runner as _scripted_runner,
)

#: The producing stage a release preview's name is read from.
_PREVIEW_STAGE = {"target": {"kind": "run_preview", "capability": "ephemeral-env"}}
#: A release preview's name is its deployment run, published verbatim.
_RELEASE_PREVIEW = "run-20260915-004"


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
            preview_key=_RELEASE_PREVIEW,
            revision=_SHA,
            repo_path=str(project_root),
            runner=runner,
            emit=lambda _l: None,
        )
        assert rc == 0
        keys = {call[1] for call in deploy_seams.calls}
        assert keys == {_RELEASE_PREVIEW}, "a branch name is never a tracking key"
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
            preview_key=_RELEASE_PREVIEW,
            revision=_SHA,
            repo_path=str(project_root),
            runner=runner,
            emit=lambda _l: None,
        )
        assert rc == 1
        keys = {call[1] for call in deploy_seams.calls}
        assert keys == {_RELEASE_PREVIEW}, "a failure never marks another branch"
        assert deploy_seams.calls[-1][2]["status"] == "failed"


class TestTheReservedFrozenNamespace:
    """A branch may be named anything; the run-named space belongs to runs.

    A preview at ``run-YYYYMMDD-NNN`` promises that what it serves does not
    move while a candidate is under review. A branch slugifying onto that
    name would take over its directory, its port and its URL and serve a
    moving branch from them, so the branch-shaped paths refuse to land there.
    """

    COLLIDING = "run-20260915-002"

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


class TestOccupancyOwnershipIsRead:
    """A caller saying it owns a frozen occupancy is not evidence.

    The URL of a frozen preview gets cited as proof that a reviewer saw a
    specific commit. Whether this deploy may claim that occupancy is decided
    by the preview already recorded there, not by the arguments passed in.
    """

    IDENTITY = "run-20260915-003"
    OTHER_SHA = "b" * 40

    def _deploy(self, monkeypatch, tmp_path, revision):
        project_root = install_ephemeral_project_source(tmp_path)
        monkeypatch.setattr(deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID"))
        monkeypatch.setattr(
            "yoke_core.tools.step_runners.exec_health_check",
            lambda url, request_id="": 0,
        )
        return deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            branch="some-branch",
            preview_key=self.IDENTITY,
            revision=revision,
            repo_path=str(project_root),
            runner=_scripted_runner(),
            emit=lambda _l: None,
        )

    def test_an_occupancy_holding_another_candidate_is_refused(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        """Replacing it would make every earlier citation of that URL wrong."""
        deploy_seams.recorded[("yoke", self.IDENTITY)] = self.OTHER_SHA
        assert self._deploy(monkeypatch, tmp_path, _SHA) == 1
        assert deploy_seams.calls == []

    def test_redeploying_the_same_candidate_is_the_ordinary_retry(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        """Which is what makes a lost dispatch safe to repeat."""
        deploy_seams.recorded[("yoke", self.IDENTITY)] = _SHA
        assert self._deploy(monkeypatch, tmp_path, _SHA) == 0

    def test_an_unclaimed_occupancy_is_deployed(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        assert self._deploy(monkeypatch, tmp_path, _SHA) == 0

    def test_a_store_that_cannot_answer_refuses_rather_than_assumes(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        """Unverified is not unclaimed: claiming it anyway could replace a
        candidate still under review."""
        deploy_seams.unreadable = "permission denied"
        assert self._deploy(monkeypatch, tmp_path, _SHA) == 1
        assert deploy_seams.calls == []

    def test_a_branch_preview_is_not_subject_to_the_check(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        """A branch preview is meant to follow its branch, so a recorded
        commit that differs is the normal case, not a conflict."""
        deploy_seams.recorded[("yoke", "some-branch")] = self.OTHER_SHA
        project_root = install_ephemeral_project_source(tmp_path)
        monkeypatch.setattr(deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID"))
        monkeypatch.setattr(
            "yoke_core.tools.step_runners.exec_health_check",
            lambda url, request_id="": 0,
        )
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            branch="some-branch",
            repo_path=str(project_root),
            runner=_scripted_runner(),
            emit=lambda _l: None,
        )
        assert rc == 0


class TestABranchNamedForARunCannotReachItsPreview:
    """The collision a run-named preview could have, driven end to end.

    A release preview is named for its run, so a branch called
    ``run-20260915-001`` would slugify onto the same occupancy and deploy a
    moving branch over a candidate under review. Both deploys run here
    against one preview store: the branch one refuses, and an ordinary
    branch keeps its own occupancy.
    """

    RUN_ID = "run-20260915-001"
    BRANCH = "feature/preview-check"

    def _run(self, deploy_seams, monkeypatch, tmp_path, **kwargs):
        project_root = install_ephemeral_project_source(tmp_path)
        monkeypatch.setattr(deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID"))
        monkeypatch.setattr(
            "yoke_core.tools.step_runners.exec_health_check",
            lambda url, request_id="": 0,
        )
        return deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            repo_path=str(project_root),
            runner=_scripted_runner(),
            emit=lambda _l: None,
            **kwargs,
        )

    def test_the_two_previews_occupy_different_slugs(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        identity = release_preview_identity(_PREVIEW_STAGE, run_id=self.RUN_ID)
        frozen = preview_slug(identity, frozen=True)
        branch = preview_slug(self.BRANCH, frozen=False)
        assert frozen != branch
        assert is_release_preview_slug(frozen)
        assert not is_release_preview_slug(branch)

    def test_a_branch_named_for_the_run_refuses_instead_of_deploying(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        """It resolves to the release preview's own occupancy, so the only
        safe answer is to refuse — deploying would replace the candidate a
        reviewer is looking at."""
        assert self._run(
            deploy_seams, monkeypatch, tmp_path, branch=self.RUN_ID,
        ) == 1
        assert deploy_seams.calls == []

    def test_deploying_both_leaves_the_candidate_serving_its_own_commit(
        self, deploy_seams, monkeypatch, tmp_path
    ):
        """The branch deploy succeeds — it is a legitimate branch — and the
        release preview's recorded commit is untouched by it."""
        identity = release_preview_identity(_PREVIEW_STAGE, run_id=self.RUN_ID)
        assert self._run(
            deploy_seams, monkeypatch, tmp_path,
            branch="main", preview_key=identity, revision=_SHA,
        ) == 0
        assert self._run(
            deploy_seams, monkeypatch, tmp_path, branch=self.BRANCH,
        ) == 0
        recorded = {key: u for _p, key, u, _i in deploy_seams.calls if "deployed_sha" in u}
        assert recorded[identity]["deployed_sha"] == _SHA
        assert set(recorded) == {identity, self.BRANCH}


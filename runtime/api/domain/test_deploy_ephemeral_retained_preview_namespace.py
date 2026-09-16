"""The reserved shape moved; the previews it protected did not.

Release previews published before they were named for their deployment run
still occupy the earlier hash shape on preview hosts. Yoke never publishes or
addresses another one, but a branch of that exact name must still be unable
to deploy over or tear down one that is serving a review — and a branch
deploy never reads the occupancy record, so the namespace reservation is the
only thing standing between that push and the candidate.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import deploy_ephemeral
from yoke_core.domain.deploy_ephemeral_occupancy import (
    is_reserved_preview_slug,
    preview_slug,
)
from yoke_core.domain.ephemeral_substrate import (
    EphemeralPolicyError,
    is_release_preview_slug,
)
from runtime.api.domain.deploy_ephemeral_test_support import (
    install_ephemeral_project_source,
    scripted_runner as _scripted_runner,
)

RETAINED = "rel-fec2595bb0bf58eca94a56710d1a087e"


def test_a_branch_deploy_cannot_take_a_retained_occupancy(
    deploy_seams, monkeypatch, tmp_path
):
    project_root = install_ephemeral_project_source(tmp_path)
    monkeypatch.setattr(deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID"))
    rc = deploy_ephemeral.exec_ephemeral_deploy(
        "yoke",
        branch=RETAINED,
        repo_path=str(project_root),
        runner=_scripted_runner(),
        emit=lambda _l: None,
    )
    assert rc == 1
    assert deploy_seams.calls == []


def test_a_branch_teardown_cannot_remove_one(deploy_seams):
    rc = deploy_ephemeral.exec_ephemeral_teardown(
        "yoke",
        branch=RETAINED,
        runner=_scripted_runner(),
        emit=lambda _l: None,
    )
    assert rc == 1
    assert deploy_seams.calls == []


def test_nothing_new_is_published_under_that_shape():
    """Closed to branches is not the same as publishable: a release preview
    may only be created under its run's name."""
    assert is_reserved_preview_slug(RETAINED)
    assert not is_release_preview_slug(RETAINED)
    with pytest.raises(EphemeralPolicyError, match="reserved release shape"):
        preview_slug(RETAINED, frozen=True)

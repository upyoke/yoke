"""Coverage for the PathClaimOverride fact layer.

Scenarios:

* ``invoke_override`` rejects when ``YOKE_HOOK_EVENT`` is set.
* The ``path_claim_overrides`` state row is persisted before
  :func:`is_active_override` sees the override as in force.
* Override auto-retires when either participant claim becomes
  terminal OR the overridden surface is narrowed out of either
  claim's declared coverage.
* ``override_point='creation'`` requires a concrete claim row.

Telemetry-emitter shape tests live in
``test_path_claims_events_override.py`` to keep both test files
under the 350-line cap.
"""

from __future__ import annotations

import os

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_item,
    seed_target,
)
from yoke_core.domain.path_claims import activate, register
from yoke_core.domain.path_claims_amend import narrow
from yoke_core.domain.path_claims_override import (
    ClaimNotFound,
    EmptyActorReason,
    HookContextRejection,
    invoke_override,
    is_active_override,
    list_overrides,
)

@pytest.fixture(autouse=True)
def _ensure_no_hook_env():
    """Tests must not inherit a YOKE_HOOK_EVENT setting."""
    prior = os.environ.pop("YOKE_HOOK_EVENT", None)
    yield
    if prior is not None:
        os.environ["YOKE_HOOK_EVENT"] = prior

class TestInvokeOverrideGuards:
    """AC-11, AC-18, AC-25 — invocation guards are distinguishable."""

    def test_rejects_hook_context(self, conn, monkeypatch):
        monkeypatch.setenv("YOKE_HOOK_EVENT", "PreToolUse")
        with pytest.raises(HookContextRejection):
            invoke_override(
                conn,
                path_claim_id=1,
                override_point="creation",
                integration_target="main",
                actor_id=1,
                actor_reason="op reason",
            )

    def test_rejects_empty_reason(self, conn):
        actor = local_human(conn)
        item_id = seed_item(conn, item_id=23010)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        with pytest.raises(EmptyActorReason):
            invoke_override(
                conn,
                path_claim_id=cid,
                override_point="creation",
                integration_target="main",
                actor_id=actor,
                actor_reason="   \n   ",
            )

    def test_creation_requires_concrete_claim_row(self, conn):
        """AC-25: override against a missing claim id is rejected."""
        with pytest.raises(ClaimNotFound):
            invoke_override(
                conn,
                path_claim_id=999_999,
                override_point="creation",
                integration_target="main",
                actor_id=1,
                actor_reason="real reason",
            )

    def test_blocking_claim_must_exist_when_provided(self, conn):
        actor = local_human(conn)
        item_id = seed_item(conn, item_id=23011)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        with pytest.raises(ClaimNotFound):
            invoke_override(
                conn,
                path_claim_id=cid,
                override_point="amend",
                integration_target="main",
                actor_id=actor,
                actor_reason="reason",
                blocking_claim_id=999_999,
            )


class TestIsActiveOverridePersistAndRetire:
    """AC-12, AC-13 — persistence-then-effect and auto-retirement."""

    def _setup_two_claims(self, conn):
        """ca holds two contended targets (active); cb is unrelated.

        Override permits cb to *eventually* claim the contended targets,
        so the invariant the fact layer checks is "anchors are in the
        blocker's coverage" not "in both claims' coverage."
        """
        actor = local_human(conn)
        item_a = seed_item(conn, item_id=24001)
        item_b = seed_item(conn, item_id=24002)
        contended = seed_target(conn, path_string="src/contended.py")
        also = seed_target(conn, path_string="src/also.py")
        ca = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[contended, also], item_id=item_a,
        )
        activate(conn, claim_id=ca, base_commit_sha=SNAP)
        other = seed_target(conn, path_string="src/other.py")
        cb = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[other], item_id=item_b,
        )
        return actor, ca, cb, contended, also

    def test_state_row_persists_before_is_active_returns_true(self, conn):
        actor, ca, cb, contended, _ = self._setup_two_claims(conn)
        assert is_active_override(
            conn, path_claim_id=cb, blocking_claim_id=ca,
        ) is False
        invoke_override(
            conn,
            path_claim_id=cb,
            override_point="amend",
            integration_target="main",
            actor_id=actor,
            actor_reason="approved collision",
            blocking_claim_id=ca,
            blocking_path_targets=[contended],
            item_id=24002,
            project="yoke",
        )
        # State row landed before fact-layer-active flips.
        rows = list_overrides(
            conn, path_claim_id=cb, blocking_claim_id=ca,
        )
        assert rows
        assert rows[0]["blocking_path_targets"] == [contended]
        assert rows[0]["actor_reason"] == "approved collision"
        assert is_active_override(
            conn, path_claim_id=cb, blocking_claim_id=ca,
        ) is True

    def test_retires_when_participant_becomes_terminal(self, conn):
        actor, ca, cb, contended, _ = self._setup_two_claims(conn)
        invoke_override(
            conn,
            path_claim_id=cb,
            override_point="amend",
            integration_target="main",
            actor_id=actor,
            actor_reason="approved",
            blocking_claim_id=ca,
            blocking_path_targets=[contended],
        )
        assert is_active_override(
            conn, path_claim_id=cb, blocking_claim_id=ca,
        ) is True
        from yoke_core.domain.path_claims import release as _release
        _release(conn, claim_id=ca, reason="merged")
        assert is_active_override(
            conn, path_claim_id=cb, blocking_claim_id=ca,
        ) is False

    def test_retires_when_overridden_surface_narrowed_out(
        self, conn, tmp_path,
    ):
        """AC-13 second clause: blocker narrows the anchored surface
        out of its declared coverage → override retires."""
        actor, ca, cb, contended, also = self._setup_two_claims(conn)
        invoke_override(
            conn,
            path_claim_id=cb,
            override_point="amend",
            integration_target="main",
            actor_id=actor,
            actor_reason="approved",
            blocking_claim_id=ca,
            blocking_path_targets=[contended],
        )
        assert is_active_override(
            conn, path_claim_id=cb, blocking_claim_id=ca,
        ) is True
        # Build a minimal repo for narrow's boundary check
        import subprocess
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(
            ["git", "init", "-q", "--initial-branch=main", str(tmp_path)],
            check=True, env=env, capture_output=True,
        )
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "also.py").write_text("y=1\n")
        subprocess.run(
            ["git", "-C", str(tmp_path), "add", "."],
            check=True, env=env, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"],
            check=True, env=env, capture_output=True,
        )
        # Narrow ca to drop the contended target so anchors no longer
        # intersect ca's declared coverage.
        narrow(
            conn,
            claim_id=ca,
            drop_target_ids=[contended],
            reason="holder narrowed",
            repo_path=str(tmp_path),
        )
        assert is_active_override(
            conn, path_claim_id=cb, blocking_claim_id=ca,
        ) is False

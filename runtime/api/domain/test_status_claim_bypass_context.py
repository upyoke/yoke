"""Unit tests for the request-scoped claim-bypass ContextVar and the
ContextVar-first-then-env precedence at the claim-verification read sites.

The done-transition status relays post the claim bypass on a ContextVar
(:mod:`yoke_core.domain.status_claim_bypass_context`) instead of process-global
env vars. These tests prove the ContextVar round-trips and resets, that each
verification-site read prefers the ContextVar and still falls back to the env
var (so every existing env-driven caller is unchanged), and that the two new
relay functions classify to the ``PROJECT`` authorization scope (not ``DENY``).
"""

from __future__ import annotations

import pytest

from yoke_core.domain import backlog_status_claim_verification as bscv
from yoke_core.domain import status_claim_bypass_context as ctx
from yoke_core.domain import verify_claim
from yoke_core.domain.backlog_update_effects import _is_delivery_release_redirect
from yoke_core.domain.function_authz_scope import classify
from yoke_core.domain.function_authz_types import DENY, PROJECT

_BYPASS_ENV_VARS = (
    "YOKE_CLAIM_BYPASS",
    "YOKE_STATUS_SOURCE",
    "YOKE_QA_GATE_BYPASS",
    "YOKE_TASK_DONE_VERIFIED",
)


@pytest.fixture(autouse=True)
def _clear_bypass_env(monkeypatch):
    """No ambient bypass env leaks into a precedence assertion."""
    for var in _BYPASS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


class TestContextVarRoundTrip:
    def test_defaults_when_unset(self):
        assert ctx.resolve_claim_bypass() == ("", "")
        assert ctx.resolve_task_done_verified() is False

    def test_override_visible_then_reset(self):
        with ctx.status_bypass_override(
            claim_bypass="done-transition:YOK-1",
            status_source="done-transition",
            task_done_verified=True,
        ):
            assert ctx.resolve_claim_bypass() == (
                "done-transition:YOK-1",
                "done-transition",
            )
            assert ctx.resolve_task_done_verified() is True
        # Reset in finally — no leak past the block.
        assert ctx.resolve_claim_bypass() == ("", "")
        assert ctx.resolve_task_done_verified() is False

    def test_nested_override_restores_outer(self):
        with ctx.status_bypass_override(
            claim_bypass="outer", status_source="s1", task_done_verified=False
        ):
            with ctx.status_bypass_override(
                claim_bypass="inner", status_source="s2", task_done_verified=True
            ):
                assert ctx.resolve_claim_bypass() == ("inner", "s2")
            assert ctx.resolve_claim_bypass() == ("outer", "s1")


class TestResolveBypassVerifyClaim:
    """verify_claim._resolve_bypass — the epic-task cascade claim gate."""

    def test_contextvar_wins_with_no_env(self):
        with ctx.status_bypass_override(
            claim_bypass="done-cascade:YOK-9",
            status_source="",
            task_done_verified=True,
        ):
            assert verify_claim._resolve_bypass() == "done-cascade:YOK-9"

    def test_env_fallback_when_contextvar_unset(self, monkeypatch):
        monkeypatch.setenv("YOKE_CLAIM_BYPASS", "auto-unblock")
        assert verify_claim._resolve_bypass() == "auto-unblock"

    def test_repair_status_promotion_via_contextvar(self):
        with ctx.status_bypass_override(
            claim_bypass="",
            status_source="repair-status:incident",
            task_done_verified=False,
        ):
            assert verify_claim._resolve_bypass() == "repair-status:incident"

    def test_repair_status_promotion_via_env(self, monkeypatch):
        monkeypatch.setenv("YOKE_STATUS_SOURCE", "repair-status:incident")
        assert verify_claim._resolve_bypass() == "repair-status:incident"

    def test_no_bypass_when_nothing_set(self):
        assert verify_claim._resolve_bypass() == ""


class TestVerifyStatusClaimReadSite:
    """backlog_status_claim_verification._verify_status_claim precedence."""

    def _run(self, *, session_id=None):
        # The bypass path emits an event and returns before any DB query; a
        # dummy conn is never touched. Silence the event emit.
        return bscv._verify_status_claim(
            object(), 7, None, session_id=session_id
        )

    def test_contextvar_bypass_skips_claim_with_no_env(self, monkeypatch):
        monkeypatch.setattr(bscv._rendering, "_emit_event", lambda *a, **k: None)
        with ctx.status_bypass_override(
            claim_bypass="done-transition:YOK-7",
            status_source="done-transition",
            task_done_verified=False,
        ):
            verified, reason = self._run(session_id=None)
        assert verified is True
        assert reason is None

    def test_env_bypass_still_skips_claim(self, monkeypatch):
        monkeypatch.setattr(bscv._rendering, "_emit_event", lambda *a, **k: None)
        monkeypatch.setenv("YOKE_CLAIM_BYPASS", "done-transition:YOK-7")
        verified, reason = self._run(session_id=None)
        assert verified is True
        assert reason is None

    def test_no_bypass_and_no_session_denies(self, monkeypatch):
        monkeypatch.setattr(bscv._rendering, "_emit_event", lambda *a, **k: None)
        verified, reason = self._run(session_id=None)
        assert verified is False
        assert reason is not None


class TestDeliveryReleaseRedirectReadSite:
    """backlog_update_effects._is_delivery_release_redirect precedence."""

    def test_non_release_target_never_redirects(self):
        assert _is_delivery_release_redirect("done") is False

    def test_contextvar_source_marks_release_redirect(self):
        with ctx.status_bypass_override(
            claim_bypass="", status_source="done-transition", task_done_verified=False
        ):
            assert _is_delivery_release_redirect("release") is True

    def test_env_source_fallback_marks_release_redirect(self, monkeypatch):
        monkeypatch.setenv("YOKE_STATUS_SOURCE", "done-transition")
        assert _is_delivery_release_redirect("release") is True

    def test_deploy_pipeline_env_bypass_still_marks_redirect(self, monkeypatch):
        monkeypatch.setenv("YOKE_CLAIM_BYPASS", "deploy-pipeline:run-1")
        assert _is_delivery_release_redirect("release") is True

    def test_plain_release_without_source_is_not_redirect(self):
        assert _is_delivery_release_redirect("release") is False


class TestAuthzClassification:
    @pytest.mark.parametrize(
        "function_id",
        [
            "done_transition.item_status_set",
            "done_transition.epic_task_status_set",
        ],
    )
    def test_relay_functions_are_project_scoped_not_denied(self, function_id):
        spec = classify(function_id, side_effects=True, project_permission=None)
        assert spec.scope == PROJECT
        assert spec.scope != DENY

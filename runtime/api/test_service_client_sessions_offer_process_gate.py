"""Service-client session-offer regressions for the disabled-process gate.

Reproduces the original ``/yoke do`` failure shape: a ``NextAction``
with ``action="charge"`` rewritten by the process-offer gate must carry
``context.scheduler.next_step`` whenever ``FrontierState.scheduler_context``
is available, so the loop's charge handler can dispatch through the
canonical scheduler routing path instead of bailing out with a contract
failure.

Covers AC-6, AC-7 (no-runnable suppressed-WAIT), and AC-12 (residue check).
The unit-level shape coverage lives in
``test_session_decision_process_gate_charge_context.py``; this file
exercises the full ``cmd_session_offer`` JSON surface so the regression
catches integration drift in addition to gate-internal drift.
"""

from __future__ import annotations

import json
import os
import sys

import pytest  # noqa: F401  (used by monkeypatch / capsys fixtures)
from runtime.api.test_constants import TEST_MODEL_ID

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.session_contract import FrontierState
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
    session_offer_db,  # noqa: F401 — re-exported fixture
)


_DISABLED_PROCESS_CONFIG = (
    "max_chain_steps=3\n"
    "do_process_offer_default=false\n"
    "do_process_offer_feed=false\n"
    "do_process_offer_strategize=false\n"
)


def _write_disabled_process_config(db_path: str) -> str:
    """Write an explicit fixture config adjacent to ``db_path``."""
    config_path = os.path.join(os.path.dirname(db_path), "config")
    with open(config_path, "w") as f:
        f.write(_DISABLED_PROCESS_CONFIG)
    return config_path


def _frontier_with_scheduler_no_sml(runnable_ids: list[str]):
    """Frontier with populated scheduler context but ``sml_coherent=False``.

    ``decide_charge_action`` requires ``sml_coherent=True`` for both of
    its return branches, so this shape forces it to return ``None`` —
    letting ``decide_next_action`` reach the not-sml-coherent branch
    (line 112 of session_decision.py) which emits ``STRATEGIZE``. The
    process-offer gate then rewrites that disabled action into
    ``CHARGE``. This is the real production path that exercises the
    ``frontier.scheduler_context``-populated route through the gate's
    CHARGE swap — distinct from the empty-scheduler-context path that
    falls through to the backward-compat charge shape covered in
    ``test_session_decision_process_gate_charge_context.py``.
    """
    primary = runnable_ids[0]
    scheduler_block = {
        "next_step": "advance",
        "item_type": "issue",
        "status": "refined-idea",
        "title": f"Runnable {primary}",
        "rank": 0,
        "explanation": f"Ranked #1: advance for issue in refined-idea ({primary})",
        "adapter": "conduct",
    }

    def _factory(*_args, **_kwargs):
        return FrontierState(
            sml_coherent=False,
            runnable_items=list(runnable_ids),
            selected_item=primary,
            scheduler_context=scheduler_block,
            drift_review=None,
        )

    return _factory


class TestSessionOfferProcessGateCharge:
    """Service-client surface for the disabled-process CHARGE swap."""

    def test_disabled_strategize_with_scheduler_yields_charge_with_scheduler(
        self, session_offer_db, monkeypatch, capsys,
    ):
        """AC-6 / AC-12: when the gate rewrites a disabled process action
        into a CHARGE and ``frontier.scheduler_context`` is populated, the
        emitted ``NextAction.context`` exposes ``scheduler.next_step`` so
        ``/yoke do``'s charge handler can dispatch through the canonical
        scheduler routing path."""
        from yoke_core.api import service_client
        from yoke_core.api import service_client_sessions_offer as offer_module

        _write_disabled_process_config(session_offer_db["db_path"])
        sid = "process-gate-strategize-runnable"
        _pre_register_session(
            session_offer_db["db_path"], sid,
            executor="claude-code",
            workspace=session_offer_db["tmp_dir"],
        )
        monkeypatch.setenv("YOKE_DB", session_offer_db["db_path"])

        runnable = ["YOK-10"]
        monkeypatch.setattr(
            offer_module,
            "_build_frontier_state_from_schedule",
            _frontier_with_scheduler_no_sml(runnable),
        )
        monkeypatch.setattr(
            service_client,
            "assess_post_delivery_drift",
            lambda *_args, **_kwargs: None,
        )

        rc = service_client.cmd_session_offer([
            "--executor", "claude-code",
            "--provider", "anthropic",
            "--model", TEST_MODEL_ID,
            "--workspace", session_offer_db["tmp_dir"],
            "--session-id", sid,
        ])
        captured = capsys.readouterr()
        assert rc == 0, f"stderr: {captured.err}"
        data = json.loads(captured.out)

        # Returned action is a chainable charge — gate's CHARGE swap fired.
        assert data["action"] == "charge"
        assert data["chainable"] is True
        ctx = data["context"]

        # Scheduler routing metadata IS present so /yoke do
        # can dispatch via context.scheduler.next_step.
        scheduler = ctx["scheduler"]
        assert scheduler["next_step"] == "advance"
        assert scheduler["status"] == "refined-idea"
        assert scheduler["adapter"] == "conduct"

        # skipped_process metadata stays additive on the charge context.
        skipped = ctx["skipped_process"]
        assert skipped["process_key"] == "STRATEGIZE"
        assert skipped["config_key"] == "do_process_offer_strategize"
        assert skipped["recommended_action"] == "strategize"
        assert skipped["skip_reason"] == "process_disabled_by_config"
        assert skipped["direct_command"] == "/yoke strategize"

        # selected_item / runnable_items are preserved and aligned with the
        # scheduler-selected item.
        assert ctx["selected_item"] == runnable[0]
        assert ctx["runnable_items"] == runnable

    def test_disabled_strategize_no_runnable_returns_suppressed_wait(
        self, session_offer_db, monkeypatch, capsys,
    ):
        """AC-7: no-runnable disabled-process path returns suppressed-WAIT
        (non-terminal) and does not invent scheduler context."""
        from yoke_core.domain.drift_review import DriftReviewResult
        from yoke_core.api import service_client
        from yoke_core.api import service_client_sessions_offer as offer_module

        _write_disabled_process_config(session_offer_db["db_path"])
        sid = "process-gate-strategize-empty"
        _pre_register_session(
            session_offer_db["db_path"], sid,
            executor="claude-code",
            workspace=session_offer_db["tmp_dir"],
        )
        monkeypatch.setenv("YOKE_DB", session_offer_db["db_path"])

        def _empty_frontier_factory(*_args, **kwargs):
            return FrontierState(
                sml_coherent=True,
                runnable_items=[],
                selected_item=None,
                scheduler_context=None,
                drift_review=kwargs.get("drift_review_dict"),
            )

        monkeypatch.setattr(
            offer_module, "_build_frontier_state_from_schedule",
            _empty_frontier_factory,
        )
        monkeypatch.setattr(
            service_client,
            "assess_post_delivery_drift",
            lambda *_args, **_kwargs: DriftReviewResult(
                classification="sml_only",
                summary="SML impacted",
                checkpoint_start="2026-05-01T00:00:00Z",
                reviewed_through="2026-05-07T00:00:00Z",
                delivered_items=[],
            ),
        )

        rc = service_client.cmd_session_offer([
            "--executor", "claude-code",
            "--provider", "anthropic",
            "--model", TEST_MODEL_ID,
            "--workspace", session_offer_db["tmp_dir"],
            "--session-id", sid,
        ])
        captured = capsys.readouterr()
        assert rc == 0, f"stderr: {captured.err}"
        data = json.loads(captured.out)

        # Suppressed-WAIT (no scheduler invented).
        assert data["action"] == "wait"
        assert data["chainable"] is False
        ctx = data["context"]
        assert "scheduler" not in ctx
        assert ctx["wait_reason"] == "process_suppressed_no_alternative"
        suppressed = ctx["suppressed_process_recommendation"]
        assert suppressed["process_key"] == "STRATEGIZE"
        assert suppressed["config_key"] == "do_process_offer_strategize"
        assert suppressed["direct_command"] == "/yoke strategize"

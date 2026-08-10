"""Relay regression tests for the done-transition status setters.

The item done-flip / delivery-stage redirect and the epic-task cascade used to
set process-global claim-bypass env vars and call the domain write directly.
They now relay ``done_transition.item_status_set`` /
``done_transition.epic_task_status_set`` with the bypass carried as a typed
payload. These tests monkeypatch ``call_dispatcher`` and assert the migrated
path relays the exact payload (preserving the ``done-transition:`` /
``done-cascade:`` source strings and the qa / nonce / done-verified flags)
WITHOUT mutating ``os.environ``.
"""

from __future__ import annotations

import os

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.engines import done_transition as dt
from yoke_core.engines import done_transition_status as status

# Synthetic fixture id kept off the literal so the doc-hygiene drift guard stays clean.
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"

_BYPASS_ENV_VARS = (
    "YOKE_CLAIM_BYPASS",
    "YOKE_STATUS_SOURCE",
    "YOKE_QA_GATE_BYPASS",
    "YOKE_TASK_DONE_VERIFIED",
)


@pytest.fixture(autouse=True)
def _clear_bypass_env(monkeypatch):
    for var in _BYPASS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _resp(function_id, result=None, *, success=True):
    return FunctionCallResponse(
        success=success, function=function_id, version="v1", result=result or {}
    )


def _patch_adapter(monkeypatch, fake):
    # Both appliers lazily import call_dispatcher from the adapter module, and
    # the cascade reads it from the engine module; patch both.
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher", fake
    )
    monkeypatch.setattr(status, "call_dispatcher", fake)


def _assert_env_untouched():
    for var in _BYPASS_ENV_VARS:
        assert var not in os.environ, var


class TestItemDirectRelay:
    def test_update_item_direct_relays_typed_payload(self, monkeypatch):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp(kwargs["function_id"], {"applied": True})

        _patch_adapter(monkeypatch, fake)
        rc = dt._update_item_direct(
            44,
            "status",
            "done",
            env_overrides={
                "YOKE_CLAIM_BYPASS": "done-transition:YOK-44",
                "YOKE_STATUS_SOURCE": "done-transition",
                "YOKE_QA_GATE_BYPASS": "0",
            },
            done_nonce_verified=True,
            qa_bypass=False,
            rebuild_board=False,
            no_github=True,
        )
        assert rc == 0
        assert len(calls) == 1
        call = calls[0]
        assert call["function_id"] == "done_transition.item_status_set"
        assert call["target"].item_id == 44
        payload = call["payload"]
        assert payload["field"] == "status"
        assert payload["value"] == "done"
        assert payload["claim_bypass"] == "done-transition:YOK-44"
        assert payload["status_source"] == "done-transition"
        assert payload["qa_bypass"] is False
        assert payload["done_nonce_verified"] is True
        assert payload["no_github"] is True
        assert payload["rebuild_board"] is False
        _assert_env_untouched()

    def test_update_item_direct_returns_one_on_relay_failure(self, monkeypatch):
        _patch_adapter(
            monkeypatch,
            lambda **k: _resp(k["function_id"], success=False),
        )
        rc = dt._update_item_direct(
            44, "status", "release",
            env_overrides={"YOKE_STATUS_SOURCE": "done-transition"},
        )
        assert rc == 1
        _assert_env_untouched()

    def test_refused_write_is_a_failure_not_a_successful_relay(
        self, monkeypatch, capsys,
    ):
        """A gate the write refused arrives as a SUCCESSFUL relay.

        Reading only the transport result is how a refused done transition
        printed its status change and exited 0 while the row never moved.
        """
        _patch_adapter(
            monkeypatch,
            lambda **k: _resp(k["function_id"], {
                "applied": True,
                "status_write_success": False,
                "status_write_error": "Error: blocking QA requirement is stale",
                "status_write_error_code": "GATE_QA_TERMINAL_VERDICT",
            }),
        )

        rc = dt._update_item_direct(44, "status", "done", item_ref=TEST_ITEM_REF)

        assert rc == 1
        # The refusal narrative goes to server stdout over an https relay, so
        # the payload text is the only thing the operator can be shown.
        assert "blocking QA requirement is stale" in capsys.readouterr().err

    def test_refusal_without_reported_text_is_still_a_failure(self, monkeypatch):
        _patch_adapter(
            monkeypatch,
            lambda **k: _resp(k["function_id"], {
                "applied": True, "status_write_success": False,
            }),
        )

        assert dt._update_item_direct(44, "status", "done") == 1


class TestTaskDirectRelay:
    def test_update_task_status_direct_relays_typed_payload(self, monkeypatch):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp(kwargs["function_id"], {"rc": 0})

        _patch_adapter(monkeypatch, fake)
        rc = dt._update_task_status_direct(
            "823",
            "1",
            "done",
            f"Auto-done: epic {TEST_ITEM_REF} marked done",
            env_overrides={
                "YOKE_TASK_DONE_VERIFIED": "1",
                "YOKE_CLAIM_BYPASS": f"done-cascade:{TEST_ITEM_REF}",
            },
        )
        assert rc == 0
        assert len(calls) == 1
        call = calls[0]
        assert call["function_id"] == "done_transition.epic_task_status_set"
        assert call["target"].item_id == 823
        payload = call["payload"]
        assert payload["epic_id"] == "823"
        assert payload["task_num"] == "1"
        assert payload["status"] == "done"
        assert payload["claim_bypass"] == f"done-cascade:{TEST_ITEM_REF}"
        assert payload["task_done_verified"] is True
        assert payload["status_source"] == ""
        assert payload["no_derive"] is True
        _assert_env_untouched()

    def test_update_task_status_direct_raises_on_relay_failure(self, monkeypatch):
        _patch_adapter(
            monkeypatch,
            lambda **k: _resp(k["function_id"], success=False),
        )
        with pytest.raises(RuntimeError):
            dt._update_task_status_direct(
                "823", "1", "done", "",
                env_overrides={"YOKE_CLAIM_BYPASS": f"done-cascade:{TEST_ITEM_REF}"},
            )
        _assert_env_untouched()


class TestSetterEndToEndRelay:
    """The migrated setters route through the relay with source strings intact."""

    def test_update_status_to_done_relays_bypass_without_env(self, monkeypatch):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp(kwargs["function_id"], {"applied": True})

        _patch_adapter(monkeypatch, fake)
        assert dt._update_status_to_done(42, skip_qa=True, item_ref=TEST_ITEM_REF) is True

        relay = [c for c in calls if c["function_id"] == "done_transition.item_status_set"]
        assert len(relay) == 1
        payload = relay[0]["payload"]
        assert payload["claim_bypass"] == f"done-transition:{TEST_ITEM_REF}"
        assert payload["status_source"] == "done-transition"
        assert payload["qa_bypass"] is True
        assert payload["done_nonce_verified"] is True
        assert payload["no_github"] is True
        _assert_env_untouched()

    def test_refused_done_write_reports_failure_after_retrying(
        self, monkeypatch, capsys,
    ):
        """The retry-and-verify path must engage, then report the truth.

        The engine's exit code is what the operator and the calling skill
        branch on; announcing ``-> done`` and exiting 0 over a row that stayed
        put strands the item with no signal that anything went wrong.
        """
        statuses = []

        def fake(**kwargs):
            fid = kwargs["function_id"]
            if fid == "done_transition.item_field":
                statuses.append(kwargs["payload"]["field"])
                return _resp(fid, {"value": "release"})
            return _resp(fid, {
                "applied": True,
                "status_write_success": False,
                "status_write_error": "Error: merging SHA is unproven",
            })

        _patch_adapter(monkeypatch, fake)
        monkeypatch.setattr("time.sleep", lambda _s: None)

        settled = dt._update_status_to_done(
            42, skip_qa=False, max_retries=2, item_ref=TEST_ITEM_REF,
        )

        assert settled is False
        assert statuses == ["status", "status"]
        assert "merging SHA is unproven" in capsys.readouterr().err

    def test_cascade_relays_done_cascade_bypass_without_env(self, monkeypatch):
        listing = "|".join(["epic", "0", "1", "t", "", "", "", "implementing"]) + "\n"
        seen = []

        def fake(**kwargs):
            seen.append(kwargs)
            fid = kwargs["function_id"]
            if fid == "done_transition.epic_task_list":
                return _resp(fid, {"task_list": listing})
            return _resp(fid, {"rc": 0})

        _patch_adapter(monkeypatch, fake)
        monkeypatch.setattr(status, "_batch_github_sync_tasks", lambda *a, **k: None)
        dt._cascade_epic_tasks_to_done(42, "42", item_ref=TEST_ITEM_REF)

        relays = [
            c for c in seen
            if c["function_id"] == "done_transition.epic_task_status_set"
        ]
        assert len(relays) == 1
        payload = relays[0]["payload"]
        assert payload["claim_bypass"] == f"done-cascade:{TEST_ITEM_REF}"
        assert payload["task_done_verified"] is True
        assert payload["status"] == "done"
        _assert_env_untouched()

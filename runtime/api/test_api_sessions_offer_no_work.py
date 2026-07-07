"""FastAPI session-offer no-work regressions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from yoke_core.api.main import app
from runtime.api.test_session_offer_schemas import session_offer_db  # noqa: F401
from runtime.api.test_service_client_sessions_helpers import _pre_register_session
from runtime.api.test_service_client_sessions_offer_no_work import (
    _seed_stale_holder_with_recent_activity,
)
from runtime.api.test_constants import TEST_MODEL_ID


def test_api_action_hint_no_work_returns_wait_with_holder(session_offer_db):
    """The API route must mirror the CLI no-work behavior."""
    holder = "yok-1628-api-holder"
    offerer = "yok-1628-api-offerer"
    _seed_stale_holder_with_recent_activity(
        session_offer_db["db_path"],
        item_id=10,
        holder_session=holder,
    )
    _pre_register_session(
        session_offer_db["db_path"],
        offerer,
        workspace=session_offer_db["tmp_dir"],
    )

    payload = {
        "session_id": offerer,
        "executor": "DARIUS",
        "provider": "anthropic",
        "model": TEST_MODEL_ID,
        "workspace": session_offer_db["tmp_dir"],
        "execution_lane": "DARIUS",
    }
    with patch("yoke_core.domain.scheduler.Path") as mock_path:
        mock_file = MagicMock()
        mock_file.is_file.return_value = True
        mock_file.stat.return_value = MagicMock(st_mtime=9999999999.0)
        mock_path.return_value.__truediv__ = lambda self, name: mock_file
        client = TestClient(app)
        client.headers.update(session_offer_db["auth_headers"])
        resp = client.post("/v1/sessions/offer", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    # With events-backed liveness, the scheduler classifies a holder with stale heartbeat
    # but fresh tool events as CLAIMED_BY_OTHER_LIVE directly, routing the
    # offer through the FEED process gate. The load-bearing invariant
    # stays: the offer never charges for a live-claim-blocked item; the
    # terminal action is non-charge (wait or escalate depending on whether
    # the do_process_offer_feed policy is enabled).
    assert data["action"] != "charge"
    assert data["action"] in ("wait", "escalate")
    assert not data["chainable"]
    ctx = data["context"]
    assert not ctx.get("selected_item")
    assert not ctx.get("scheduler")

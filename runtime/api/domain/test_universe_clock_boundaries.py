"""Imported authority and owned resume/override clocks preserve native facts."""

import json
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import (
    local_universe_import,
    path_claims_events_override,
    sessions_resume_notice,
    session_actor_binding_write,
    universe_import_credentials,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

STAMP = parse_instant("1970-01-01T05:29:59.123456+05:30")
WIRE = "1969-12-31T23:59:59.123456Z"


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_import_owner_and_rotated_credentials_bind_native_clocks(
    tmp_path, monkeypatch, zone
):
    from yoke_core.domain.api_tokens import bootstrap_admin_token

    monkeypatch.setattr(local_universe_import, "utc_now", lambda: STAMP)
    monkeypatch.setattr(universe_import_credentials, "utc_now", lambda: STAMP)
    monkeypatch.setattr(
        session_actor_binding_write, "persist_operating_actor", lambda *_: None
    )
    with init_test_db(tmp_path) as db_path:
        with connect_test_db(db_path) as conn:
            original = bootstrap_admin_token(conn)
            conn.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
            owner = local_universe_import._prepare_local_owner(conn)
            assert owner["revoked_token_count"] >= 1
            assert (
                conn.execute(
                    "SELECT revoked_at FROM api_tokens WHERE id=%s",
                    (original.token_id,),
                ).fetchone()[0]
                == STAMP
            )
            replacement = universe_import_credentials.replace_imported_credentials(conn)
            assert (
                conn.execute(
                    "SELECT created_at FROM api_tokens WHERE id=%s",
                    (replacement.token_id,),
                ).fetchone()[0]
                == STAMP
            )
            assert (
                conn.execute(
                    "SELECT created_at FROM api_token_audit WHERE api_token_id=%s AND event_type='issued'",
                    (replacement.token_id,),
                ).fetchone()[0]
                == STAMP
            )


def test_resume_notice_formats_native_claim_clocks_and_preserves_opaque_text(
    monkeypatch,
):
    recorded = []
    conn = SimpleNamespace(execute=lambda sql, params: recorded.append(params))
    monkeypatch.setattr(sessions_resume_notice, "_column_present", lambda _: True)
    monkeypatch.setattr(sessions_resume_notice, "utc_now", lambda: STAMP)
    opaque = "1970-01-01T05:29:59.123456+05:30"
    assert sessions_resume_notice.write_pending_resume_notice(
        conn,
        "session",
        released_claims=[{"released_at": STAMP, "opaque": opaque}],
        reacquired_count=1,
        conflict_count=0,
        commit=False,
    )
    payload = json.loads(recorded[0][0])
    assert payload["reactivated_at"] == WIRE
    assert payload["released_claims"] == [{"released_at": WIRE, "opaque": opaque}]


def test_override_projects_supplied_native_clock_before_emission(monkeypatch):
    monkeypatch.setattr(
        path_claims_events_override._base_events, "_emit", lambda **kw: kw
    )
    payload = path_claims_events_override.emit_override(
        conn=None,
        path_claim_id=1,
        override_point="creation",
        integration_target="main",
        actor_id=2,
        actor_reason="holder coordination",
        invoked_at=STAMP,
    )
    assert payload["context"]["invoked_at"] == WIRE


def test_override_refuses_blank_supplied_clock_before_emission(monkeypatch):
    called = []
    monkeypatch.setattr(
        path_claims_events_override._base_events,
        "_emit",
        lambda **kw: called.append(kw),
    )
    with pytest.raises(ValueError):
        path_claims_events_override.emit_override(
            conn=None,
            path_claim_id=1,
            override_point="creation",
            integration_target="main",
            actor_id=2,
            actor_reason="holder coordination",
            invoked_at="",
        )
    assert not called

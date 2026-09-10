"""Handler coverage for the profile.* surface.

Drives the handlers directly with synthetic envelopes against the
``test_db`` fixture: the one-read projection of who the caller is, the
token mint/revoke pair scoped to the caller, the time-zone preference,
and the onboarding reset that clears only dismissal preferences.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.profile import (
    handle_profile_get,
    handle_profile_onboarding_reset,
    handle_profile_preference_set,
    handle_profile_token_create,
    handle_profile_token_revoke,
)
from yoke_core.domain.profile_read import issuer_label


def _request(function_id, payload=None, actor_id=None, target=None):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=actor_id, session_id=""),
        target=target or TargetRef(kind="global"),
        payload=payload or {},
    )


def _human_actor(conn):
    return int(conn.execute(
        "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
    ).fetchone()[0])


def _get(actor_id):
    outcome = handle_profile_get(_request("profile.get", actor_id=str(actor_id)))
    assert outcome.primary_success, outcome.error
    return outcome.result_payload


def test_get_refuses_without_a_bound_actor(test_db):
    refused = handle_profile_get(_request("profile.get"))
    assert refused.primary_success is False
    assert refused.error.code == "actor_required"
    wrong_target = handle_profile_get(_request(
        "profile.get", actor_id="1", target=TargetRef(kind="item", item_id=1),
    ))
    assert wrong_target.error.code == "target_invalid"


def test_get_projects_identity_roles_tokens_preferences_and_hidden_count(
    test_db,
):
    actor = _human_actor(test_db)
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO actor_external_identities "
        "(actor_id, issuer, subject, email, linked_at) "
        "VALUES (%s, 'https://accounts.google.com', 'sub-1', 'ben@example.test', %s)",
        (actor, now),
    )
    test_db.execute(
        "INSERT INTO actor_ui_preferences (actor_id, pref_key, value, updated_at) "
        "VALUES (%s, 'overview.module.dismissed.first_deploy', '1', %s), "
        "(%s, 'profile.time_zone', 'Europe/Berlin', %s)",
        (actor, now, actor, now),
    )
    test_db.commit()
    minted = mint_token(test_db, actor_id=actor, name="operator-cli")

    profile = _get(actor)
    assert profile["actor"]["id"] == actor
    assert profile["actor"]["kind"] == "human"
    assert profile["identity"] == {
        "email": "ben@example.test", "signed_in_with": "Google",
    }
    assert isinstance(profile["roles"]["org"], list)
    assert isinstance(profile["roles"]["projects"], list)
    token_ids = [row["token_id"] for row in profile["tokens"]]
    assert minted.token_id in token_ids
    mine = next(row for row in profile["tokens"] if row["token_id"] == minted.token_id)
    assert mine["name"] == "operator-cli"
    assert mine["machine_id"] is None
    assert profile["preferences"] == {"time_zone": "Europe/Berlin"}
    assert profile["onboarding"] == {"hidden_count": 1}


def test_tokens_are_scoped_to_the_caller(test_db):
    actor = _human_actor(test_db)
    test_db.execute(
        "INSERT INTO actors (kind, name, created_at) VALUES ('human', 'other', %s) "
        "RETURNING id",
        (iso8601_now(),),
    )
    other = int(test_db.execute(
        "SELECT id FROM actors WHERE name = 'other'"
    ).fetchone()[0])
    test_db.commit()
    theirs = mint_token(test_db, actor_id=other, name="theirs")

    assert theirs.token_id not in [
        row["token_id"] for row in _get(actor)["tokens"]
    ]
    refused = handle_profile_token_revoke(_request(
        "profile.token.revoke", {"token_id": theirs.token_id},
        actor_id=str(actor),
    ))
    assert refused.primary_success is False
    assert refused.error.code == "token_not_found"


def test_token_create_then_revoke_round_trip(test_db):
    actor = _human_actor(test_db)
    created = handle_profile_token_create(_request(
        "profile.token.create", {"name": "ci-release"}, actor_id=str(actor),
    ))
    assert created.primary_success, created.error
    raw = created.result_payload["raw_token"]
    token_id = created.result_payload["token_id"]
    assert raw and len(raw) > 20
    assert token_id in [row["token_id"] for row in _get(actor)["tokens"]]

    revoked = handle_profile_token_revoke(_request(
        "profile.token.revoke", {"token_id": token_id}, actor_id=str(actor),
    ))
    assert revoked.primary_success, revoked.error
    assert revoked.result_payload == {"token_id": token_id, "status": "revoked"}
    assert token_id not in [row["token_id"] for row in _get(actor)["tokens"]]

    again = handle_profile_token_revoke(_request(
        "profile.token.revoke", {"token_id": token_id}, actor_id=str(actor),
    ))
    assert again.error.code == "token_not_active"


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
def test_token_create_refuses_bad_names(test_db, name):
    outcome = handle_profile_token_create(_request(
        "profile.token.create", {"name": name}, actor_id="1",
    ))
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"


def test_machine_bound_token_is_ended_by_retiring_the_machine(test_db):
    actor = _human_actor(test_db)
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO machines (machine_id, name, owner_actor_id, access, "
        "registered_at, last_seen_at) VALUES "
        "('11111111-1111-4111-8111-111111111111', 'laptop', %s, '{}', %s, %s)",
        (actor, now, now),
    )
    test_db.commit()
    minted = mint_token(test_db, actor_id=actor, name="laptop")
    test_db.execute(
        "UPDATE api_tokens SET machine_id = "
        "'11111111-1111-4111-8111-111111111111' WHERE id = %s",
        (minted.token_id,),
    )
    test_db.commit()

    row = next(
        t for t in _get(actor)["tokens"] if t["token_id"] == minted.token_id
    )
    assert row["machine_name"] == "laptop"
    refused = handle_profile_token_revoke(_request(
        "profile.token.revoke", {"token_id": minted.token_id},
        actor_id=str(actor),
    ))
    assert refused.error.code == "token_machine_bound"


def test_time_zone_preference_validates_and_clears(test_db):
    actor = _human_actor(test_db)
    bad = handle_profile_preference_set(_request(
        "profile.preference.set",
        {"key": "profile.time_zone", "value": "Mars/Olympus"},
        actor_id=str(actor),
    ))
    assert bad.error.code == "payload_invalid"
    unknown_key = handle_profile_preference_set(_request(
        "profile.preference.set", {"key": "theme", "value": "dark"},
        actor_id=str(actor),
    ))
    assert unknown_key.error.code == "payload_invalid"

    saved = handle_profile_preference_set(_request(
        "profile.preference.set",
        {"key": "profile.time_zone", "value": "America/New_York"},
        actor_id=str(actor),
    ))
    assert saved.primary_success, saved.error
    assert _get(actor)["preferences"]["time_zone"] == "America/New_York"

    cleared = handle_profile_preference_set(_request(
        "profile.preference.set", {"key": "profile.time_zone", "value": ""},
        actor_id=str(actor),
    ))
    assert cleared.primary_success
    assert _get(actor)["preferences"]["time_zone"] == ""


def test_onboarding_reset_clears_only_dismissals(test_db):
    actor = _human_actor(test_db)
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO actor_ui_preferences (actor_id, pref_key, value, updated_at) "
        "VALUES (%s, 'overview.module.dismissed.first_deploy', '1', %s), "
        "(%s, 'overview.module.dismissed.run_onboard', '1', %s), "
        "(%s, 'profile.time_zone', 'UTC', %s)",
        (actor, now, actor, now, actor, now),
    )
    test_db.commit()
    assert _get(actor)["onboarding"]["hidden_count"] == 2

    outcome = handle_profile_onboarding_reset(_request(
        "profile.onboarding.reset", actor_id=str(actor),
    ))
    assert outcome.primary_success, outcome.error
    assert outcome.result_payload == {"cleared": 2}
    after = _get(actor)
    assert after["onboarding"]["hidden_count"] == 0
    assert after["preferences"]["time_zone"] == "UTC"


@pytest.mark.parametrize("issuer,label", [
    ("https://accounts.google.com", "Google"),
    ("https://github.com/login/oauth", "GitHub"),
    ("https://login.example.test/oidc", "login.example.test"),
    ("", "unknown"),
])
def test_issuer_label_names_the_provider(issuer, label):
    assert issuer_label(issuer) == label

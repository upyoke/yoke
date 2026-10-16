"""Match codes keep their alphabet, expiry and bounded collision admission."""

from datetime import timedelta
from unittest.mock import Mock

import pytest

from runtime.api.domain.test_machine_authorization_codes import (
    conn as _conn_fixture,
    pending,
)
from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain import machine_authorization_codes as codes
from yoke_core.domain import machine_match_codes as matches

conn = _conn_fixture


def test_ten_thousand_draws_are_short_and_unambiguous():
    alphabet = set(matches.MATCH_CODE_ALPHABET)
    assert len(alphabet) == 32
    assert alphabet.isdisjoint("0O1I")
    for _ in range(10_000):
        code = matches.generate_match_code()
        assert len(code) == matches.MATCH_CODE_LENGTH == 4
        assert set(code) <= alphabet


@pytest.mark.parametrize("value", ["K7F2", " k7f2 ", "\tk7f2\n"])
def test_normalization_accepts_case_and_surrounding_space(value):
    assert matches.normalize_match_code(value) == "K7F2"


def test_allocation_retries_collisions_then_inserts_a_free_code(conn, monkeypatch):
    generate = Mock(side_effect=["K7F2", "K7F2", "ABCD"])
    monkeypatch.setattr(matches, "generate_match_code", generate)
    assert pending(conn)["user_code"] == "K7F2"
    assert pending(conn)["user_code"] == "ABCD"
    assert generate.call_count == 3


def test_collision_exhaustion_is_bounded_and_names_recovery(conn, monkeypatch):
    generate = Mock(return_value="K7F2")
    monkeypatch.setattr(matches, "generate_match_code", generate)
    pending(conn)
    generate.reset_mock()
    with pytest.raises(
        codes.MachineAuthorizationError, match="retry in a minute"
    ) as error:
        pending(conn)
    assert error.value.code == "match_code_exhausted"
    assert error.value.status == 503
    assert generate.call_count == matches.MATCH_CODE_ATTEMPTS == 8
    assert (
        conn.execute("SELECT count(*) FROM machine_authorization_codes").fetchone()[0]
        == 1
    )


def test_expired_collision_is_reusable_and_expiry_stays_ten_minutes(conn, monkeypatch):
    monkeypatch.setattr(matches, "generate_match_code", lambda: "K7F2")
    pending(conn)
    conn.execute(
        "UPDATE machine_authorization_codes SET expires_at='2000-01-01T00:00:00Z'"
    )
    now = utc_now()
    monkeypatch.setattr(codes, "_now", lambda: now)
    result = pending(conn)
    expiry = conn.execute(
        "SELECT expires_at FROM machine_authorization_codes"
    ).fetchone()[0]
    assert result["user_code"] == "K7F2"
    assert result["expires_in"] == 600
    assert parse_instant(expiry) == now + timedelta(minutes=10)

"""Attesting no tests and registering a command are mutually exclusive."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.verification_posture import (
    POSTURE_ATTESTED_NO_TESTS,
    POSTURE_UNDECIDED,
    VERIFICATION_POSTURE_FAMILY,
)
from yoke_core.domain.project_structure import ValidationError
from yoke_core.domain.project_structure_validation import _validate_payload
from yoke_core.domain.project_verification_posture import (
    VerificationPostureError,
    attest_no_tests,
    attestation_reason,
    attests_no_tests,
    clear_no_tests,
    declared_posture,
)
from yoke_core.domain.qa_command_plan_registration import (
    ensure_registered_command_plan,
)

_REASON = "idea-only repository; the client has not funded tests yet"


def _live_plan_slugs(conn) -> list[str]:
    return [
        str(row["slug"])
        for row in conn.execute(
            "SELECT slug FROM qa_plans WHERE project_id=1 AND retired_at IS NULL "
            "ORDER BY slug"
        ).fetchall()
    ]


def test_a_project_that_said_nothing_is_undecided() -> None:
    with test_database() as conn:
        assert declared_posture(conn, 1) == POSTURE_UNDECIDED
        assert not attests_no_tests(conn, 1)
        assert attestation_reason(conn, 1) == ""


def test_attesting_records_the_posture_and_its_reason() -> None:
    with test_database() as conn:
        result = attest_no_tests(
            conn, project_id=1, project="yoke", reason=_REASON
        )

        assert result["posture"] == POSTURE_ATTESTED_NO_TESTS
        assert attests_no_tests(conn, 1)
        assert attestation_reason(conn, 1) == _REASON


def test_attesting_retires_the_registered_command_it_contradicts() -> None:
    # Both declarations at once would materialize a command case and a review
    # requirement for the same item, and the boot-time convergence would then
    # re-enter a registration the attestation refuses. Retiring here is what
    # makes that state unreachable rather than merely discouraged.
    with test_database() as conn:
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest",
        )
        assert "registered-command-quick" in _live_plan_slugs(conn)

        result = attest_no_tests(
            conn, project_id=1, project="yoke", reason=_REASON
        )

        assert result["retired_plans"] == ["registered-command-quick"]
        assert "registered-command-quick" not in _live_plan_slugs(conn)
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM qa_plan_project_defaults "
            "WHERE project_id=1"
        ).fetchone()["n"] == 0


def test_registering_under_the_attestation_is_refused_by_name() -> None:
    with test_database() as conn:
        attest_no_tests(conn, project_id=1, project="yoke", reason=_REASON)

        with pytest.raises(VerificationPostureError) as excinfo:
            ensure_registered_command_plan(
                conn, project_id=1, project="yoke", scope="quick",
                command="python3 -m pytest",
            )

    message = str(excinfo.value)
    assert "command-ci" in message
    assert _REASON in message
    assert "yoke qa no-tests clear" in message


def test_the_refusal_covers_every_scope_not_only_the_ci_runner() -> None:
    with test_database() as conn:
        attest_no_tests(conn, project_id=1, project="yoke", reason=_REASON)

        for scope in ("quick", "full", "e2e", "smoke"):
            with pytest.raises(VerificationPostureError):
                ensure_registered_command_plan(
                    conn, project_id=1, project="yoke", scope=scope,
                    command="python3 -m pytest",
                )


def test_clearing_lets_a_project_that_gained_a_suite_bind_it() -> None:
    with test_database() as conn:
        attest_no_tests(conn, project_id=1, project="yoke", reason=_REASON)

        cleared = clear_no_tests(
            conn, project_id=1, project="yoke", reason="the suite now exists",
        )
        assert cleared["posture"] == POSTURE_UNDECIDED
        assert "yoke qa registered-command set" in cleared["next_step"]
        assert declared_posture(conn, 1) == POSTURE_UNDECIDED

        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick",
            command="python3 -m pytest",
        )
        assert "registered-command-quick" in _live_plan_slugs(conn)


def test_clearing_a_posture_that_was_never_attested_is_refused() -> None:
    with test_database() as conn:
        with pytest.raises(VerificationPostureError, match="no stored"):
            clear_no_tests(
                conn, project_id=1, project="yoke", reason="nothing to clear",
            )


def test_a_reasonless_attestation_is_refused_as_an_omission() -> None:
    with test_database() as conn:
        with pytest.raises(VerificationPostureError, match="requires a reason"):
            attest_no_tests(conn, project_id=1, project="yoke", reason="   ")


def test_the_payload_validator_stores_only_the_attestation() -> None:
    with pytest.raises(ValidationError, match="not stored"):
        _validate_payload(
            VERIFICATION_POSTURE_FAMILY,
            {"posture": POSTURE_UNDECIDED, "reason": _REASON},
        )
    with pytest.raises(ValidationError, match="non-empty 'reason'"):
        _validate_payload(
            VERIFICATION_POSTURE_FAMILY,
            {"posture": POSTURE_ATTESTED_NO_TESTS},
        )
    assert _validate_payload(
        VERIFICATION_POSTURE_FAMILY,
        {"posture": POSTURE_ATTESTED_NO_TESTS, "reason": _REASON},
    )["reason"] == _REASON

"""Regression tests for AC-1..AC-4 of the claim-safe artifact mutation
guardrail set: the ``claim-work`` conflict text and the ``who-claims``
non-holder warning. Both surfaces must carry stop/coordinate/wait
guidance and must explicitly tell the caller not to paste the holder
session id into any function-call envelope.

``claim-work`` conflict text says to stop, coordinate, or wait.
The conflict text explicitly says not to use the holder session id
      in any function-call envelope.
``who-claims`` warns non-holders that the item is actively owned
      by another session.
These tests pin both messages.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.test_sessions import EMIT_PATH_TABLES, _register, conn  # noqa: F401
from runtime.harness.harness_sessions_claims import (
    WHO_CLAIMS_NON_HOLDER_WARNING_TEMPLATE,
    cmd_who_claims,
)
from runtime.harness.harness_sessions_claims_acquire import (
    CLAIM_CONFLICT_HOLDER_AUTHORITY_WARNING,
    CLAIM_CONFLICT_NEXT_STEPS,
    cmd_claim,
)


HOLDER_SESSION_ID = "holder-session-A"
OTHER_SESSION_ID = "other-session-B"
ITEM_ID = 9001


@pytest.fixture
def conflicting_claim(conn):  # noqa: F811  (reuse imported pytest fixture)
    """Seed a held exclusive item-claim by ``HOLDER_SESSION_ID``.

    cmd_claim emits WorkClaimed via the native emitter, so the per-test DB
    needs the full events + event_registry schema (EMIT_PATH_TABLES); a
    minimal events table would fail the emit INSERT and poison the txn on PG.
    """
    apply_fixture_ddl(conn, EMIT_PATH_TABLES)
    _register(conn, session_id=HOLDER_SESSION_ID)
    _register(conn, session_id=OTHER_SESSION_ID)
    cmd_claim(conn, HOLDER_SESSION_ID, "item", item_id=ITEM_ID)
    return conn


class TestClaimConflictGuidance:
    """AC-1 / AC-2 — ``claim-work`` conflict text."""

    def test_conflict_message_names_holder_and_target(self, conflicting_claim):
        with pytest.raises(PermissionError) as excinfo:
            cmd_claim(
                conflicting_claim,
                OTHER_SESSION_ID,
                "item",
                item_id=ITEM_ID,
            )
        msg = str(excinfo.value)
        # The holder id and target label remain in the message so
        # downstream coordination/identification still works.
        assert HOLDER_SESSION_ID in msg
        assert f"YOK-{ITEM_ID}" in msg
        # Stop / coordinate / wait language.
        assert CLAIM_CONFLICT_NEXT_STEPS in msg
        assert "Stop" in msg
        assert "coordinate" in msg
        assert "wait" in msg
        # Explicit warning against pasting the holder id into any
        # claim/function-call override surface.
        assert CLAIM_CONFLICT_HOLDER_AUTHORITY_WARNING in msg
        assert "actor.session_id" in msg
        assert "--session-id" in msg
        assert "function-call envelope" in msg

    def test_conflict_constants_decline_authority_language(self):
        # Module-level constants are the single source of truth and must
        # carry the exact authority-warning language so callers cannot
        # paper over the rule by reading the holder id off a script.
        assert "Do NOT paste" in CLAIM_CONFLICT_HOLDER_AUTHORITY_WARNING
        assert "actor.session_id" in CLAIM_CONFLICT_HOLDER_AUTHORITY_WARNING
        assert "--session-id" in CLAIM_CONFLICT_HOLDER_AUTHORITY_WARNING
        assert "function-call envelope" in CLAIM_CONFLICT_HOLDER_AUTHORITY_WARNING
        assert "coordination identifier" in CLAIM_CONFLICT_HOLDER_AUTHORITY_WARNING
        assert "authority" in CLAIM_CONFLICT_HOLDER_AUTHORITY_WARNING


class TestWhoClaimsHolderConcise:
    """AC-3 — holder gets the canonical row only; no advisory noise."""

    def test_holder_caller_sees_only_canonical_row(self, conflicting_claim):
        out = cmd_who_claims(
            conflicting_claim,
            str(ITEM_ID),
            caller_session_id=HOLDER_SESSION_ID,
        )
        lines = out.splitlines()
        assert len(lines) == 1
        # Canonical _format_row shape: pipe-separated claim columns.
        assert "|" in lines[0]
        assert HOLDER_SESSION_ID in lines[0]
        assert "WARNING" not in out


class TestWhoClaimsNonHolderWarning:
    """AC-3 — non-holder and unknown-session calls carry the warning."""

    def test_non_holder_caller_sees_warning(self, conflicting_claim):
        out = cmd_who_claims(
            conflicting_claim,
            str(ITEM_ID),
            caller_session_id=OTHER_SESSION_ID,
        )
        lines = out.splitlines()
        assert len(lines) == 2
        # First line is still the canonical claim row.
        assert "|" in lines[0]
        assert HOLDER_SESSION_ID in lines[0]
        # Second line is the warning, naming the holder explicitly.
        warning = lines[1]
        assert warning.startswith("WARNING:")
        assert HOLDER_SESSION_ID in warning
        assert "actively claimed by another session" in warning
        # AC-2 alignment: same authority/envelope warning shape as
        # the claim-work conflict message.
        assert "coordination identifier" in warning
        assert "actor.session_id" in warning
        assert "--session-id" in warning
        assert "function-call envelope" in warning

    def test_unknown_caller_session_sees_warning(self, conflicting_claim):
        out = cmd_who_claims(
            conflicting_claim,
            str(ITEM_ID),
            caller_session_id="",
        )
        lines = out.splitlines()
        assert len(lines) == 2
        assert lines[1].startswith("WARNING:")
        assert HOLDER_SESSION_ID in lines[1]

    def test_no_claim_returns_empty_without_warning(self, conn):  # noqa: F811
        _register(conn, session_id=OTHER_SESSION_ID)
        out = cmd_who_claims(
            conn,
            "424242",
            caller_session_id=OTHER_SESSION_ID,
        )
        # AC-3 boundary: probing an unclaimed item must stay quiet so
        # scripts that scan availability do not get advisory noise.
        assert out == ""

    def test_warning_template_keeps_authority_language(self):
        # The warning template is module-level so the wording is pinned
        # in one place; tests fail loudly if any author softens it.
        assert "actively claimed by another session" in WHO_CLAIMS_NON_HOLDER_WARNING_TEMPLATE
        assert "coordination identifier" in WHO_CLAIMS_NON_HOLDER_WARNING_TEMPLATE
        assert "Do NOT paste" in WHO_CLAIMS_NON_HOLDER_WARNING_TEMPLATE
        assert "actor.session_id" in WHO_CLAIMS_NON_HOLDER_WARNING_TEMPLATE
        assert "--session-id" in WHO_CLAIMS_NON_HOLDER_WARNING_TEMPLATE
        assert "function-call envelope" in WHO_CLAIMS_NON_HOLDER_WARNING_TEMPLATE

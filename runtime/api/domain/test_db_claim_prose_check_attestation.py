"""db_claim_prose_check — reviewed-negative attestation reader/writer units.

Split out of ``test_db_claim_prose_check.py`` to keep authored files under
the 350-line limit. Unit coverage for the profile-JSON attestation reader
(:func:`_claim_reviewed_negative`) plus the ``db_claim.amend`` stamping
contract that writes it.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.db_claim_prose_check_state import (
    _claim_reviewed_negative,
)
from yoke_core.domain.db_claim_prose_check_test_helpers import (
    _reviewed_none_profile_json,
)
from yoke_core.domain.db_mutation_profile import (
    REVIEWED_NEGATIVE_FIELD,
    REVIEWED_VALIDATED_AT_FIELD,
    is_reviewed_negative,
    stamp_reviewed_negative,
)


class TestClaimReviewedNegative:
    """Unit coverage for :func:`_claim_reviewed_negative`."""

    def test_stamped_profile_json_string_returns_true(self):
        assert _claim_reviewed_negative(_reviewed_none_profile_json()) is True

    def test_stamped_profile_dict_returns_true(self):
        profile = {
            "state": "none",
            REVIEWED_NEGATIVE_FIELD: True,
            REVIEWED_VALIDATED_AT_FIELD: "2026-04-24T16:35:36Z",
        }
        assert _claim_reviewed_negative(profile) is True

    def test_bare_negative_default_returns_false(self):
        assert _claim_reviewed_negative('{"state":"none"}') is False

    def test_declared_profile_returns_false(self):
        profile = json.dumps({
            "state": "declared",
            REVIEWED_NEGATIVE_FIELD: True,
        })
        assert _claim_reviewed_negative(profile) is False

    def test_reviewed_negative_false_returns_false(self):
        assert _claim_reviewed_negative(
            '{"state":"none","reviewed_negative":false}'
        ) is False

    def test_reviewed_negative_truthy_non_bool_returns_false(self):
        assert _claim_reviewed_negative(
            '{"state":"none","reviewed_negative":"yes"}'
        ) is False

    def test_empty_and_malformed_inputs_return_false(self):
        assert _claim_reviewed_negative(None) is False
        assert _claim_reviewed_negative("") is False
        assert _claim_reviewed_negative("{not json") is False
        assert _claim_reviewed_negative('["state","none"]') is False
        assert _claim_reviewed_negative(42) is False


class TestStampReviewedNegative:
    """Unit coverage for the profile-side stamp helpers."""

    def test_stamp_on_none_profile_adds_attestation(self):
        stamped = stamp_reviewed_negative(
            {"state": "none"}, validated_at="2026-05-01T00:00:00Z",
        )
        assert stamped[REVIEWED_NEGATIVE_FIELD] is True
        assert stamped[REVIEWED_VALIDATED_AT_FIELD] == "2026-05-01T00:00:00Z"
        assert is_reviewed_negative(stamped) is True

    def test_stamp_does_not_mutate_input(self):
        profile = {"state": "none"}
        stamp_reviewed_negative(profile, validated_at="2026-05-01T00:00:00Z")
        assert profile == {"state": "none"}

    def test_stamp_on_declared_profile_is_identity(self):
        declared = {"state": "declared", "model_name": "primary"}
        assert stamp_reviewed_negative(
            declared, validated_at="2026-05-01T00:00:00Z",
        ) == declared

    def test_amend_rejects_caller_supplied_attestation_keys(self):
        from yoke_core.domain.db_claim import DbClaimAmendmentError, amend

        with pytest.raises(DbClaimAmendmentError, match="reserved"):
            amend(
                1,
                {"state": "none", REVIEWED_NEGATIVE_FIELD: True},
                reason="callers must not self-attest",
            )

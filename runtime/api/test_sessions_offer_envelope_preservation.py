"""Helper-level unit tests for ``merge_offer_envelope``.

Covers the named-set boundary cases (``OFFER_WRITE_OWNED_KEYS``,
``PRESERVED_KEYS``, unknown-key passthrough, malformed-input
robustness). End-to-end persistence coverage lives in
``test_service_client_sessions_offer_persist.py``.

The merge is value-level (``dict.update``): every top-level envelope
key is independent. The merge contract is "every existing key survives
unless the per-offer dict explicitly overwrites it". PRESERVED_KEYS are
never named by the per-offer dict; OFFER_WRITE_OWNED_KEYS are sometimes
named (``runtime_session_id`` only on Codex offers with a thread UUID).
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.sessions_offer_envelope_merge import (
    OFFER_WRITE_OWNED_KEYS,
    PRESERVED_KEYS,
    merge_offer_envelope,
)


class TestNamedSetClassification:
    """AC-2 / AC-3: the constants pin the cross-offer state set."""

    def test_offer_write_owned_keys_exact_membership(self):
        """The per-offer write fully owns these eleven keys."""
        assert OFFER_WRITE_OWNED_KEYS == frozenset({
            "session_id",
            "executor",
            "provider",
            "model",
            "workspace",
            "execution_lane",
            "capabilities",
            "step",
            "supported_paths",
            "max_chain_steps",
            "runtime_session_id",
        })

    def test_preserved_keys_exact_membership(self):
        """Cross-offer state keys written by other code paths."""
        assert PRESERVED_KEYS == frozenset({
            "chain_checkpoint",
            "chain_skip_memory",
            "execution_scope",
        })

    def test_named_sets_are_disjoint(self):
        """A key is either offer-owned or preserved-by-default, never both."""
        assert OFFER_WRITE_OWNED_KEYS & PRESERVED_KEYS == frozenset()

    def test_named_sets_are_frozen(self):
        """The constants are immutable to prevent runtime mutation drift."""
        assert isinstance(OFFER_WRITE_OWNED_KEYS, frozenset)
        assert isinstance(PRESERVED_KEYS, frozenset)


class TestMalformedExistingHandling:
    """AC-5: missing / empty / malformed / non-dict existing -> per-offer unchanged."""

    @pytest.mark.parametrize(
        "existing_blob",
        [
            None,
            "",
            "not json at all",
            "{unterminated",
            json.dumps([1, 2, 3]),  # JSON list, not dict
            json.dumps("scalar"),    # JSON string scalar
            json.dumps(42),          # JSON number scalar
            json.dumps(None),        # JSON null
        ],
        ids=[
            "none", "empty_string", "non_json_text", "truncated_json",
            "json_list", "json_string_scalar", "json_number_scalar",
            "json_null",
        ],
    )
    def test_unparseable_or_non_dict_returns_per_offer(self, existing_blob):
        per = {"session_id": "x", "step": 1}
        assert merge_offer_envelope(existing_blob, per) == per

    def test_per_offer_is_copied_not_aliased(self):
        """Caller's dict must not become the return value (defensive copy)."""
        per = {"session_id": "x", "step": 1}
        result = merge_offer_envelope(None, per)
        assert result is not per
        result["step"] = 99
        assert per["step"] == 1


class TestPreservedKeyContract:
    """AC-4: PRESERVED_KEYS survive every offer write (per-offer never names them)."""

    def test_chain_skip_memory_survives(self):
        existing = json.dumps({
            "chain_skip_memory": [
                {"item_id": "YOK-10", "skip_reason": "recoverable_substrate"},
                {"item_id": "YOK-11", "skip_reason": "live_claim_conflict"},
            ],
        })
        per = {"session_id": "x", "step": 2}
        merged = merge_offer_envelope(existing, per)
        assert merged["chain_skip_memory"] == [
            {"item_id": "YOK-10", "skip_reason": "recoverable_substrate"},
            {"item_id": "YOK-11", "skip_reason": "live_claim_conflict"},
        ]

    def test_chain_checkpoint_survives(self):
        existing = json.dumps({
            "chain_checkpoint": {
                "step": 1,
                "action": "charge",
                "chainable": True,
                "handler_outcome": "completed",
                "item_id": "YOK-10",
            },
        })
        per = {"session_id": "x", "step": 2}
        merged = merge_offer_envelope(existing, per)
        assert merged["chain_checkpoint"] == {
            "step": 1,
            "action": "charge",
            "chainable": True,
            "handler_outcome": "completed",
            "item_id": "YOK-10",
        }

    def test_execution_scope_survives(self):
        """Same-session execution-scope state (worktree/main) survives offers."""
        existing = json.dumps({
            "execution_scope": {
                "scope": "worktree",
                "item_id": 42,
                "worktree_path": "/abs/.worktrees/YOK-42",
            },
        })
        per = {"session_id": "x", "step": 2}
        merged = merge_offer_envelope(existing, per)
        assert merged["execution_scope"] == {
            "scope": "worktree",
            "item_id": 42,
            "worktree_path": "/abs/.worktrees/YOK-42",
        }

    def test_all_preserved_keys_survive_together(self):
        """All three preserved keys carry forward in one merge."""
        existing = json.dumps({
            "chain_skip_memory": [{"item_id": "YOK-1"}],
            "chain_checkpoint": {"step": 1, "action": "charge"},
            "execution_scope": {"scope": "main", "item_id": None,
                                "worktree_path": None},
        })
        per = {"session_id": "x", "step": 2, "executor": "DARIUS"}
        merged = merge_offer_envelope(existing, per)
        for key in PRESERVED_KEYS:
            assert key in merged, f"PRESERVED_KEYS member {key!r} was lost"


class TestOfferOwnedKeyContract:
    """AC-2 owned keys overwrite when present; preserved when omitted."""

    def test_per_offer_overwrites_owned_keys(self):
        """Identity/step fields land on top of prior values."""
        existing = json.dumps({
            "session_id": "old-sess",
            "executor": "OLD",
            "step": 1,
            "model": "old-model",
        })
        per = {
            "session_id": "new-sess",
            "executor": "NEW",
            "step": 5,
            "model": "new-model",
        }
        merged = merge_offer_envelope(existing, per)
        assert merged["session_id"] == "new-sess"
        assert merged["executor"] == "NEW"
        assert merged["step"] == 5
        assert merged["model"] == "new-model"

    def test_runtime_session_id_preserved_when_per_offer_omits(self):
        """Non-Codex offer omits the key; prior Codex thread UUID survives."""
        existing = json.dumps({"runtime_session_id": "codex-uuid-abc"})
        per = {"session_id": "x", "step": 2}  # non-Codex: omits the key
        merged = merge_offer_envelope(existing, per)
        assert merged["runtime_session_id"] == "codex-uuid-abc"

    def test_runtime_session_id_overwritten_when_per_offer_includes(self):
        """Codex re-offer with a new thread UUID overwrites the prior value."""
        existing = json.dumps({"runtime_session_id": "codex-uuid-old"})
        per = {
            "session_id": "x",
            "step": 2,
            "runtime_session_id": "codex-uuid-new",
        }
        merged = merge_offer_envelope(existing, per)
        assert merged["runtime_session_id"] == "codex-uuid-new"


class TestUnknownKeyPassthrough:
    """AC-4: keys not in either named set are preserved by default."""

    def test_unknown_top_level_key_preserved(self):
        """Future cross-offer state lands without code changes here."""
        existing = json.dumps({
            "future_route_defense_scratch": {"v": 1, "decisions": ["X", "Y"]},
        })
        per = {"session_id": "x", "step": 2}
        merged = merge_offer_envelope(existing, per)
        assert merged["future_route_defense_scratch"] == {
            "v": 1, "decisions": ["X", "Y"],
        }

    def test_unknown_key_can_still_be_overwritten_by_per_offer(self):
        """If a future writer names the same key in per-offer, dict.update wins."""
        existing = json.dumps({"hypothetical_key": "old"})
        per = {"session_id": "x", "step": 2, "hypothetical_key": "new"}
        merged = merge_offer_envelope(existing, per)
        assert merged["hypothetical_key"] == "new"


class TestMixedMerge:
    """End-to-end shape: PRESERVED + OWNED + unknown all in one merge."""

    def test_full_cross_offer_state_round_trip(self):
        existing = json.dumps({
            # PRESERVED_KEYS
            "chain_skip_memory": [{"item_id": "YOK-1"}],
            "chain_checkpoint": {"step": 1, "action": "charge"},
            "execution_scope": {"scope": "worktree", "item_id": 7,
                                "worktree_path": "/abs"},
            # OFFER_WRITE_OWNED_KEYS (overwritten by per-offer)
            "session_id": "old",
            "step": 1,
            "model": "opus-old",
            # OFFER_WRITE_OWNED_KEYS but per-offer omits — preserved
            "runtime_session_id": "codex-uuid-keep",
            # Unknown key — preserved
            "extension_scratch": {"k": "v"},
        })
        per = {
            "session_id": "new",
            "step": 2,
            "model": "opus-new",
            "executor": "DARIUS",
            "workspace": "/abs/ws",
            "capabilities": [],
            "supported_paths": ["advance"],
            "max_chain_steps": 3,
            "provider": "anthropic",
            "execution_lane": "primary",
        }
        merged = merge_offer_envelope(existing, per)
        # PRESERVED_KEYS survive
        assert merged["chain_skip_memory"] == [{"item_id": "YOK-1"}]
        assert merged["chain_checkpoint"] == {"step": 1, "action": "charge"}
        assert merged["execution_scope"] == {
            "scope": "worktree", "item_id": 7, "worktree_path": "/abs",
        }
        # Owned-and-named-by-per-offer are overwritten
        assert merged["session_id"] == "new"
        assert merged["step"] == 2
        assert merged["model"] == "opus-new"
        # Owned-but-omitted-by-per-offer is preserved
        assert merged["runtime_session_id"] == "codex-uuid-keep"
        # Unknown key survives
        assert merged["extension_scratch"] == {"k": "v"}

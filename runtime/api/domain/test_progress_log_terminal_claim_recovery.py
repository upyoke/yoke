"""A finished item teaches callers to skip their final checkpoint."""

from unittest.mock import patch

from runtime.api.domain.test_yoke_function_dispatch_claims import (
    _ClaimMatrixSuite,
    _Req,
    _Resp,
    _make_request,
    _ok_handler,
    _stable_kwargs,
)
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import register


class TestTerminalProgressLogRecovery(_ClaimMatrixSuite):
    def test_done_item_without_claim_teaches_skip_checkpoint(self):
        function = "items.progress_log.append"
        public_ref = "BUZZ-7"
        register(
            function,
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(),
            claim_required_kind="item",
        )
        with (
            patch.object(claims_module, "who_claims_for_item", return_value=None),
            patch.object(
                claims_module, "_claim_recovery_item_ref", return_value=public_ref
            ),
            patch("yoke_core.domain.db_helpers.connect") as connect,
            patch(
                "yoke_core.domain.item_terminal_resources.item_is_terminal",
                return_value=True,
            ) as item_is_terminal,
        ):
            response = dispatch(_make_request(function))
        item_is_terminal.assert_called_once_with(
            connect.return_value.__enter__.return_value,
            42,
        )
        assert not response.success
        assert response.error is not None
        assert response.error.code == "claim_required"
        expected = (
            f"item {public_ref} is terminal; its result is already recorded — "
            "skip the final checkpoint (.yoke/docs/agents/rules/item-writes.md)"
        )
        assert response.error.message == expected
        assert response.error.recovery_hint == expected
        assert "claims work acquire" not in response.error.message
        assert "claims work acquire" not in response.error.recovery_hint

"""Freezing a project's resolved delivery default onto an empty item.

Resolution itself (``resolve_default_delivery_flow``) now lives in, and is
tested with, :mod:`yoke_core.domain.deployment_flow_clearance` -- this file
covers only the freeze half this engine still owns.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.engines import done_transition_delivery_default as delivery_default


class TestFreezeResolvedDeliveryFlow:
    def test_writes_the_resolved_flow_onto_the_item(self):
        response = SimpleNamespace(
            success=True,
            result={"item_id": 550, "deployment_flow": "ext-default", "claimed": True},
            error=None,
        )
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ) as dispatch:
            result = delivery_default.freeze_resolved_delivery_flow(
                550, "ext-default", public_ref="EXT-550"
            )
        assert result == "ext-default"
        assert (
            dispatch.call_args.kwargs["function_id"]
            == "items.deployment_flow.claim_default"
        )
        assert dispatch.call_args.kwargs["payload"] == {"flow_id": "ext-default"}

    def test_a_success_response_naming_no_stored_value_refuses_rather_than_guessing(
        self,
    ):
        """A malformed response cannot be papered over by assuming it
        matches the candidate this call offered."""
        response = SimpleNamespace(
            success=True,
            result={"item_id": 553, "deployment_flow": "", "claimed": True},
            error=None,
        )
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ):
            with pytest.raises(RuntimeError, match="named no stored deployment_flow"):
                delivery_default.freeze_resolved_delivery_flow(
                    553, "ext-default", public_ref="EXT-553"
                )

    def test_a_refused_write_raises(self):
        response = SimpleNamespace(
            success=False, result={}, error=SimpleNamespace(message="frozen item"),
        )
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ):
            with pytest.raises(RuntimeError, match="frozen item"):
                delivery_default.freeze_resolved_delivery_flow(
                    551, "ext-default", public_ref="EXT-551"
                )

    def test_a_value_raced_in_since_the_callers_earlier_read_wins(self):
        """The conditional UPDATE inside claim_default did not apply
        (claimed=False), so the response's own reread value -- not the
        resolved candidate this call offered -- is the winning one."""
        response = SimpleNamespace(
            success=True,
            result={
                "item_id": 552,
                "deployment_flow": "raced-in-value",
                "claimed": False,
            },
            error=None,
        )
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ) as dispatch:
            result = delivery_default.freeze_resolved_delivery_flow(
                552, "ext-default", public_ref="EXT-552"
            )
        assert result == "raced-in-value"
        dispatch.assert_called_once()

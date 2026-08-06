"""Targeted handler tests for ``claims.path.widen`` planned-path resolution.

Lives in a sibling file because ``test_api_claims_functions.py`` already
sits at the 350-line hard limit. Coverage:

- ``add_paths`` resolves through the strict resolver by default.
- ``allow_planned=True`` routes through ``resolve_or_plan_paths_to_target_ids``
  with the owning ``item_id``, ``claim_id``, and ``directory_paths``.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, patch

from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.migration_path_claim_widen import (
    MigrationPathClaimContext,
    WidenedPathClaim,
)
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


def _envelope(
    payload: Dict[str, Any], function: str = "claims.path.widen"
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item", item_id=1665),
        payload=payload,
    )


class TestWidenPlannedPaths(unittest.TestCase):
    def setUp(self) -> None:
        reset_registry_for_tests()
        register_all_handlers()
        from yoke_core.domain import yoke_function_actor_identity as actor_id
        self._patchers = [
            patch.object(events_module, "emit_event"),
            patch.object(
                dispatch_module, "_idempotency_lookup", lambda *_a, **_k: None,
            ),
            patch.dict("os.environ", {"YOKE_SESSION_ID": "s-1"}, clear=False),
            patch.object(
                claims_module, "who_claims_for_item",
                return_value={"id": 1, "session_id": "s-1"},
            ),
            # The mocked db connection in _run() would otherwise feed the
            # actor-id resolver a fake row; pin to an empty lookup so the
            # binder leaves the envelope's actor_id alone.
            patch.object(
                actor_id, "_default_actor_id_resolver",
                return_value=actor_id.ActorLookup(),
            ),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patchers):
            p.stop()
        reset_registry_for_tests()

    def _run(
        self,
        payload: Dict[str, Any],
        *,
        strict_ret,
        planned_ret,
        function="claims.path.widen",
        amendment_id=404,
    ):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = (1665,)
        with patch(
            "yoke_core.domain.db_helpers.connect", return_value=mock_conn,
        ), patch(
            "yoke_core.domain.migration_path_claim_widen.lock_claim_for_widen",
            return_value=MigrationPathClaimContext(
                item_id=1665,
                project_id=1,
                project="yoke",
                profile_raw='{"state":"none"}',
                attestation_raw="{}",
            ),
        ), patch(
            "yoke_core.domain.path_claims_resolve.resolve_paths_to_target_ids",
            return_value=strict_ret,
        ) as strict, patch(
            "yoke_core.domain.path_claims_resolve."
            "resolve_or_plan_paths_to_target_ids", return_value=planned_ret,
        ) as planned, patch(
            "yoke_core.domain.migration_path_claim_widen.widen_locked_claim",
            return_value=WidenedPathClaim(amendment_id=amendment_id),
        ) as widen:
            resp = dispatch(_envelope(payload, function))
        return resp, strict, planned, widen

    def test_strict_resolver_when_allow_planned_omitted(self):
        """Strict half: the default keeps the existing resolver."""
        resp, strict, planned, widen = self._run(
            {
                "claim_id": 116,
                "reason": "strict default",
                "add_paths": ["runtime/api/x.py"],
            },
            strict_ret=[2960], planned_ret=[],
        )
        self.assertTrue(resp.success, msg=resp.error)
        strict.assert_called_once()
        planned.assert_not_called()
        self.assertEqual(widen.call_args.kwargs["add_target_ids"], [2960])

    def test_allow_planned_routes_through_planned_resolver(self):
        """Planned half: ``allow_planned=True`` uses the planning resolver."""
        resp, strict, planned, widen = self._run(
            {
                "claim_id": 116,
                "reason": "planned widen",
                "add_paths": [
                    "runtime/api/domain/new.py",
                    "runtime/api/domain/dir/",
                ],
                "directory_paths": ["runtime/api/domain/dir/"],
                "allow_planned": True,
            },
            strict_ret=[], planned_ret=[3001, 3002],
        )
        self.assertTrue(resp.success, msg=resp.error)
        planned.assert_called_once()
        strict.assert_not_called()
        kw = planned.call_args.kwargs
        self.assertEqual(kw["item_id"], 1665)
        self.assertEqual(kw["claim_id"], 116)
        self.assertEqual(kw["directory_paths"], ["runtime/api/domain/dir/"])
        self.assertEqual(widen.call_args.kwargs["add_target_ids"], [3001, 3002])

    def test_target_ids_route_to_atomic_widen(self):
        resp, strict, planned, widen = self._run(
            {
                "claim_id": 116,
                "add_target_ids": [2956, 2957],
                "reason": "split file budget",
            },
            strict_ret=[], planned_ret=[], amendment_id=400,
        )
        self.assertTrue(resp.success, msg=resp.error)
        strict.assert_not_called()
        planned.assert_not_called()
        self.assertEqual(resp.result["amendment_id"], 400)
        self.assertEqual(widen.call_args.kwargs["add_target_ids"], [2956, 2957])

    def test_amend_aliases_atomic_widen(self):
        resp, _, _, _ = self._run(
            {
                "claim_id": 116,
                "add_target_ids": [2958],
                "reason": "external amend verb",
            },
            strict_ret=[], planned_ret=[],
            function="claims.path.amend", amendment_id=401,
        )
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["amendment_id"], 401)


if __name__ == "__main__":
    unittest.main()

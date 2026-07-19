"""Unit tests for ephemeral environment function handlers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, Mock, patch

from yoke_core.domain.handlers import ephemeral_env
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(payload: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="ephemeral_env.update",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


class TestEphemeralEnvHandlers(unittest.TestCase):
    def test_get_returns_structured_environment(self):
        conn = Mock()
        context = MagicMock()
        context.__enter__.return_value = conn
        raw = (
            "12|demo|feature-one|EXT-9|101|refs/heads/feature-one|9001|4001|"
            "https://feature-one.preview.example.com|healthy|start|||deadbeef|created"
        )
        with patch("yoke_core.domain.db_helpers.connect", return_value=context):
            with patch(
                "yoke_core.domain.ephemeral_env.cmd_get", return_value=raw
            ) as cmd_get:
                outcome = ephemeral_env.handle_ephemeral_env_get(
                    _request({"project": "demo", "branch": "feature-one"})
                )

        self.assertTrue(outcome.primary_success)
        cmd_get.assert_called_once_with(conn, "demo", "feature-one")
        environment = outcome.result_payload["environment"]
        self.assertEqual(environment["id"], "12")
        self.assertEqual(environment["status"], "healthy")
        self.assertEqual(environment["url"], "https://feature-one.preview.example.com")

    def test_update_delegates_to_domain_update(self):
        conn = Mock()
        with patch("yoke_core.domain.db_helpers.connect", return_value=conn):
            with patch(
                "yoke_core.domain.ephemeral_env.cmd_update",
                return_value="Updated env 12: status=healthy",
            ) as cmd_update:
                outcome = ephemeral_env.handle_ephemeral_env_update(
                    _request(
                        {
                            "env_id": "12",
                            "field": "status",
                            "value": "healthy",
                        },
                    ),
                )

        self.assertTrue(outcome.primary_success)
        cmd_update.assert_called_once_with(conn, 12, "status", "healthy")
        self.assertTrue(outcome.result_payload["updated"])
        self.assertEqual(
            outcome.result_payload["message"], "Updated env 12: status=healthy"
        )
        conn.close.assert_called_once()

    def test_update_maps_unknown_env_to_not_found(self):
        conn = Mock()
        with patch("yoke_core.domain.db_helpers.connect", return_value=conn):
            with patch(
                "yoke_core.domain.ephemeral_env.cmd_update",
                side_effect=LookupError("ephemeral environment '99' not found"),
            ):
                outcome = ephemeral_env.handle_ephemeral_env_update(
                    _request(
                        {"env_id": 99, "field": "status", "value": "healthy"},
                    ),
                )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")
        self.assertEqual(outcome.error.jsonpath, "$.payload.env_id")
        conn.close.assert_called_once()

    def test_update_maps_invalid_field(self):
        conn = Mock()
        with patch("yoke_core.domain.db_helpers.connect", return_value=conn):
            with patch(
                "yoke_core.domain.ephemeral_env.cmd_update",
                side_effect=ValueError("unknown field 'bogus'"),
            ):
                outcome = ephemeral_env.handle_ephemeral_env_update(
                    _request(
                        {"env_id": 12, "field": "bogus", "value": "x"},
                    ),
                )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_field")
        self.assertEqual(outcome.error.jsonpath, "$.payload.field")
        conn.close.assert_called_once()

    def test_update_requires_env_id(self):
        outcome = ephemeral_env.handle_ephemeral_env_update(
            _request({"field": "status", "value": "healthy"}),
        )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_ephemeral_env_function_id_is_registered(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain import yoke_function_registry as registry

        registry.reset_registry_for_tests()
        try:
            register_all_handlers()
            entry = registry.lookup("ephemeral_env.update")
            self.assertIsNotNone(entry)
            self.assertEqual(
                list(entry.side_effects),
                ["ephemeral_environments_update"],
            )
            read_entry = registry.lookup("ephemeral_env.get")
            self.assertIsNotNone(read_entry)
            self.assertEqual(list(read_entry.side_effects), [])
        finally:
            registry.reset_registry_for_tests()


if __name__ == "__main__":
    unittest.main()

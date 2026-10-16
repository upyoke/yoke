"""Authenticated public adapters reach real handlers through the HTTP boundary."""

import io
import json
from unittest.mock import patch

from runtime.api.test_api_yoke_functions import _ApiSuite
from yoke_cli.commands.adapters.reflection_capture import reflection_capture
from yoke_cli.commands.adapters.hard_blocks import hard_blocks
from yoke_cli.transport.https import HttpsConnection
from yoke_core.domain import yoke_function_registry as registry
from yoke_core.domain.handlers import reflection_capture as capture_handler
from yoke_core.domain.handlers._register_advance_preflight import (
    register as register_gates,
)


class TestAgentControlPlaneHttp(_ApiSuite):
    def _through_http(self, operation):
        received = []

        def post(request, timeout=None):
            envelope = json.loads(request.data)
            received.append(envelope)
            response = self._client.post(
                "/v1/functions/call",
                json=envelope,
                headers=self._headers,
            )
            assert response.status_code == 200, response.text
            return io.BytesIO(response.content)

        with (
            patch(
                "yoke_cli.transport.https.resolve_https_connection",
                return_value=HttpsConnection(
                    api_url="https://control.example", token="fixture"
                ),
            ),
            patch("yoke_cli.transport.https.open_no_redirect", side_effect=post),
            patch(
                "yoke_cli.transport.dispatcher._call_local",
                side_effect=AssertionError("client used direct dispatch"),
            ),
            patch.dict("os.environ", {"YOKE_SESSION_ID": "s-1"}),
        ):
            code = operation()
        return code, received

    def test_complete_capture_persists_on_authenticated_server(self):
        capture_handler.register(registry)
        text = (
            "---REFLECTION-START---\n---BEGIN ENTRY---\n"
            "timestamp: 2026-10-15T12:00:00Z\nagent: engineer\n"
            "context: isolated HTTP fixture\ncategory: problem\n"
            "The public route preserves the whole response.\n"
            "---END ENTRY---\n---REFLECTION-END---"
        )
        with patch("sys.stdin", io.StringIO(text)):
            code, received = self._through_http(
                lambda: reflection_capture(
                    [
                        "--stdin",
                        "--project",
                        "yoke",
                        "--json",
                    ]
                )
            )
        assert code == 0
        assert received[0]["payload"]["text"] == text
        from runtime.api.fixtures.file_test_db import connect_test_db

        with connect_test_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT agent, body FROM ouroboros_entries WHERE context=%s",
                ("isolated HTTP fixture",),
            ).fetchone()
        assert row["agent"] == "engineer"
        assert row["body"] == "The public route preserves the whole response."

    def test_dependency_adapter_uses_same_server_evaluator(self):
        register_gates(registry)
        from runtime.api.fixtures.file_test_db import connect_test_db
        from yoke_core.domain import shepherd_init

        with connect_test_db(self._db_path) as conn:
            shepherd_init.cmd_init(conn)
        code, received = self._through_http(
            lambda: hard_blocks(
                [
                    f"YOK-{42}",
                    "--gate-point",
                    "activation",
                    "--json",
                ]
            )
        )
        assert code == 0
        assert received[0]["target"]["public_ref"] == f"YOK-{42}"

    def test_merge_audit_uses_authenticated_snapshot_and_local_report(self):
        from yoke_core.domain.handlers import merge_audit_snapshot

        merge_audit_snapshot.register(registry)
        from yoke_cli.commands.merge_audit import merge_audit
        from runtime.api.fixtures.file_test_db import connect_test_db
        from yoke_core.domain import shepherd_init

        with connect_test_db(self._db_path) as conn:
            shepherd_init.cmd_init(conn)
        code, received = self._through_http(
            lambda: merge_audit(
                [
                    f"YOK-{42}",
                    "--project",
                    "yoke",
                ]
            )
        )
        assert code == 0
        assert received[0]["function"] == "merge.audit.snapshot"
        assert received[0]["target"]["public_ref"] == f"YOK-{42}"

    def test_failed_capture_returns_partial_counts_over_http(self):
        capture_handler.register(registry)
        from runtime.api.test_api_yoke_functions import _envelope

        text = (
            "---REFLECTION-START---\n---BEGIN ENTRY---\n"
            "timestamp: 2026-10-15T12:00:00Z\nagent: engineer\n"
            "context: isolated refusal fixture\ncategory: problem\n"
            "Persistence is unavailable.\n---END ENTRY---\n---REFLECTION-END---"
        )
        with patch(
            "yoke_core.domain.ouroboros.cmd_insert_entry",
            side_effect=RuntimeError("fixture outage"),
        ):
            response = self._client.post(
                "/v1/functions/call",
                headers=self._headers,
                json=_envelope(
                    "ouroboros.reflection.capture",
                    target={"kind": "global", "project_id": "yoke"},
                    payload={"text": text},
                ),
            )
        body = response.json()
        assert not body["success"]
        assert body["error"]["code"] == "reflection_capture_incomplete"
        assert body["result"]["entries_persist_failed"] == 1
        assert body["result"]["entries_persisted"] == 0

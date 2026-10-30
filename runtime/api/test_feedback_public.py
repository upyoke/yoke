"""Public feedback reaches the receiving universe without sender credentials."""

import io
import json
from urllib.error import HTTPError
from pathlib import Path
from unittest.mock import patch

from runtime.api.test_api_yoke_functions import _ApiSuite
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_cli.feedback_delivery import send_feedback
from yoke_core.api.routes import feedback

VALID = {"category": "failed", "evidence": "The documented recipe failed.",
         "agent": "engineer", "reporter_email": "person@example.test",
         "yoke_version": "0.2.0.202610290013",
         "universe_fingerprint": "customer@2026-01-01T00:00:00Z"}


class TestFeedbackPublic(_ApiSuite):
    def post(self, payload, headers=None):
        with patch.object(feedback, "get_db_readwrite", getattr(self, "_receiver_factory", lambda: connect_test_db(self._db_path))):
            return self._client.post("/v1/feedback", json=payload,
                headers=headers or {"User-Agent": "yoke-cli/0.2.0.202610290013"})

    def rows(self):
        with connect_test_db(self._db_path) as conn:
            return conn.execute("SELECT o.category,o.body,p.slug,o.reporter_email,o.yoke_version,o.universe_fingerprint,o.agent,o.session_id,a.kind,a.system_component FROM ouroboros_entries o LEFT JOIN projects p ON p.id=o.project_id LEFT JOIN actors a ON a.id=o.actor_id ORDER BY o.id").fetchall()

    def test_tokenless_post_stores_metadata_and_service_actor(self):
        response = self.post(VALID)
        assert response.status_code == 201, response.text
        assert tuple(self.rows()[0]) == (VALID["category"], VALID["evidence"], "yoke",
            VALID["reporter_email"], VALID["yoke_version"], VALID["universe_fingerprint"],
            "engineer", "", "system", "feedback")

    def test_malformed_fields_return_400_without_writes(self):
        for field, value in [("category", "problem"), ("evidence", ""),
                             ("evidence", " " * 8), ("evidence", "x" * 4001),
                             ("yoke_version", "tomorrow"),
                             ("universe_fingerprint", "not-a-universe"),
                             ("universe_fingerprint", "customer@yesterday")]:
            with self.subTest(field=field, value=str(value)[:30]):
                assert self.post({**VALID, field: value}).status_code == 400
                assert self.rows() == []
        assert self.post(VALID, {"User-Agent": "browser"}).status_code == 400
        assert self.rows() == []

    def test_missing_or_replaced_cli_user_agent_has_its_own_refusal(self):
        for headers in [{"User-Agent": ""}, {"User-Agent": "node"}]:
            response = self.post(VALID, headers)
            assert response.status_code == 400
            assert response.json()["error"] == "feedback_user_agent_invalid"
            assert "Upgrade Yoke" in response.json()["recovery"]
        assert self.rows() == []

    def test_cli_posts_directly_without_storing_a_sender_copy(self):
        def post(request, timeout):
            assert request.get_header("Authorization") is None
            assert request.get_header("User-agent").startswith("yoke-cli/")
            result = self.post(json.loads(request.data))
            stream = io.BytesIO(result.content)
            stream.status = result.status_code
            return stream
        receiver = connect_test_db(self._db_path)
        self._receiver_factory = lambda: receiver
        with init_test_db(Path(self._tmp_dir) / "sender") as sender:
            with connect_test_db(sender) as conn:
                before = conn.execute("SELECT COUNT(*) FROM ouroboros_entries").fetchone()[0]
            with patch("yoke_cli.feedback_delivery.open_no_redirect", side_effect=post):
                assert send_feedback(category="failed", evidence=VALID["evidence"],
                    metadata=VALID, agent="engineer") == 0
            with connect_test_db(sender) as conn:
                assert conn.execute("SELECT COUNT(*) FROM ouroboros_entries").fetchone()[0] == before
        assert len(self.rows()) == 1

    def test_required_identity_fields_have_typed_refusals(self):
        for field, name in (("yoke_version", "version"),
                            ("universe_fingerprint", "fingerprint"), ("agent", "agent")):
            for value, suffix in ((None, "missing"), ("", "missing"), ("invalid value", "invalid")):
                payload = {**VALID, field: value}
                response = self.post(payload)
                assert response.status_code == 400
                assert response.json()["error"] == f"feedback_{name}_{suffix}"
                assert "Upgrade Yoke" in response.json()["recovery"]
                assert self.rows() == []
            payload = {k: v for k, v in VALID.items() if k != field}
            assert self.post(payload).json()["error"] == f"feedback_{name}_missing"
        assert self.post({"category": "failed", "evidence": "old CLI"}).json()["error"] == "feedback_version_missing"

    def test_source_reporting_version_and_matching_user_agent_are_accepted(self):
        version = VALID["yoke_version"] + "+abcdef012345.dirty"
        assert self.post({**VALID, "yoke_version": version},
                         {"User-Agent": "yoke-cli/" + version}).status_code == 201
        assert self.rows()[0][4] == version

    def test_bad_cli_version_and_mismatched_identity_are_refused(self):
        for value in ("unknown", "fixture", VALID["yoke_version"] + "+bad", "0.2.0.202610280001"):
            assert self.post(VALID, {"User-Agent": "yoke-cli/" + value}).json()["error"] == "feedback_user_agent_invalid"
        assert self.rows() == []


def test_delivery_failure_preserves_full_evidence(capsys):
    evidence = "Full evidence " + "x" * 3900
    with patch("yoke_cli.feedback_delivery.open_no_redirect", side_effect=OSError("offline")):
        assert send_feedback(category="failed", evidence=evidence, metadata=VALID, agent="tester") == 1
    assert evidence in capsys.readouterr().err


def test_delivery_failure_reports_receiver_error_code(capsys):
    error = HTTPError("https://feedback.example", 400, "Bad Request", {},
                      io.BytesIO(b'{"error":"feedback_user_agent_invalid"}'))
    with patch("yoke_cli.feedback_delivery.open_no_redirect", side_effect=error):
        assert send_feedback(category="failed", evidence="Relay changed the header", metadata=VALID, agent="tester") == 1
    diagnostic = capsys.readouterr().err
    assert "HTTP 400: feedback_user_agent_invalid" in diagnostic
    assert "Relay changed the header" in diagnostic

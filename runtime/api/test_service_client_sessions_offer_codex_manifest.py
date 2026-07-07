"""Codex manifest-derived path tests for service_client session-offer.

Covers AC-4/AC-5: Codex offers must derive supported paths from the shared
registry plus the Codex manifest's downstream-path limitations, and those
limits must override caller-provided ``--supported-paths``.
"""

from __future__ import annotations

import json
import os

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
    session_offer_db,  # noqa: F401 — re-exported fixture
)


class TestSessionOfferCodexManifest:
    def test_session_offer_selects_compatible_item_for_codex_altman_lane(self, session_offer_db):
        """Codex ALTMAN offers should skip incompatible top-ranked DARIUS work."""
        conn = connect_test_db(session_offer_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence, created_at, updated_at, source, frozen, spec)
               VALUES (13, 'Compatible refine task', 'issue', 'idea', 'high', 1, 13,
                       '2026-03-01', '2026-03-01', 'user', 0,
                       '# Compatible refine task\n\nFixture spec body for codex-manifest tests.')"""
        )
        conn.commit()
        conn.close()

        config_path = os.path.join(os.path.dirname(session_offer_db["db_path"]), "config")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("executor_default_lane_codex=ALTMAN\n")
            handle.write("lane_paths_darius=advance,conduct,shepherd,usher\n")
            handle.write("lane_paths_altman=refine,polish\n")

        sid = "codex-altman-compatible"
        _pre_register_session(session_offer_db["db_path"], sid, executor="codex", provider="openai", model="gpt-5.4", workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--executor", "codex",
                "--provider", "openai",
                "--model", "gpt-5.4",
                "--workspace", session_offer_db["tmp_dir"],
                "--supported-paths", "refine,polish",
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["action"] == "charge"
        assert data["context"]["selected_item"] == "YOK-13"
        assert data["context"]["scheduler"]["next_step"] == "refine"

    def test_session_offer_codex_applies_manifest_limits_when_input_omitted(self, session_offer_db):
        """AC-4/AC-5: Codex offers derive paths from registry plus limitations."""
        conn = connect_test_db(session_offer_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence, created_at, updated_at, source, frozen, spec)
               VALUES (13, 'Compatible refine task', 'issue', 'idea', 'high', 1, 13,
                       '2026-03-01', '2026-03-01', 'user', 0,
                       '# Compatible refine task\n\nFixture spec body for codex-manifest tests.')"""
        )
        conn.commit()
        conn.close()

        manifest_dir = os.path.join(session_offer_db["tmp_dir"], "runtime", "harness", "codex")
        os.makedirs(manifest_dir, exist_ok=True)
        with open(os.path.join(manifest_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "supports": {
                        "command_source": "shared_yoke_registry",
                        "disabled_downstream_paths": [
                            "shepherd",
                            "advance",
                            "polish",
                            "usher",
                        ],
                    }
                },
                handle,
            )

        sid = "codex-registry-derived"
        _pre_register_session(session_offer_db["db_path"], sid, executor="codex", provider="openai", model="gpt-5.4", workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--executor", "codex",
                "--provider", "openai",
                "--model", "gpt-5.4",
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["action"] == "charge"
        assert data["context"]["selected_item"] == "YOK-13"
        assert data["context"]["scheduler"]["next_step"] == "refine"

    def test_session_offer_codex_limits_override_spoofed_supported_paths(self, session_offer_db):
        """AC-5: registry+manifest truth wins over caller-provided paths."""
        conn = connect_test_db(session_offer_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence, created_at, updated_at, source, frozen, spec)
               VALUES (13, 'Compatible refine task', 'issue', 'idea', 'high', 1, 13,
                       '2026-03-01', '2026-03-01', 'user', 0,
                       '# Compatible refine task\n\nFixture spec body for codex-manifest tests.')"""
        )
        conn.commit()
        conn.close()

        manifest_dir = os.path.join(session_offer_db["tmp_dir"], "runtime", "harness", "codex")
        os.makedirs(manifest_dir, exist_ok=True)
        with open(os.path.join(manifest_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "supports": {
                        "command_source": "shared_yoke_registry",
                        "disabled_downstream_paths": [
                            "shepherd",
                            "advance",
                            "polish",
                            "usher",
                        ],
                    }
                },
                handle,
            )

        sid = "codex-manifest-override"
        _pre_register_session(session_offer_db["db_path"], sid, executor="codex", provider="openai", model="gpt-5.4", workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--executor", "codex",
                "--provider", "openai",
                "--model", "gpt-5.4",
                "--workspace", session_offer_db["tmp_dir"],
                "--supported-paths", "advance",
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["action"] == "charge"
        assert data["context"]["selected_item"] == "YOK-13"
        assert data["context"]["scheduler"]["next_step"] == "refine"

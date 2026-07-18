"""Tests for machine-local project capability secrets."""

from __future__ import annotations

from yoke_core.domain import json_helper
from yoke_core.domain import capability_machine_secrets
from yoke_core.domain import projects_capabilities as pc
from runtime.api.domain.projects_capabilities_test_helpers import cap_db
from runtime.api.fixtures.file_test_db import connect_test_db


class TestMachineLocalCapabilitySecrets:
    def test_set_aws_secret_writes_local_file(
        self, cap_db: str
    ) -> None:
        msg = pc.cmd_capability_set_secret(
            "1", "aws-admin", "access_key_id", "AKIALOCAL", db_path=cap_db
        )

        assert "machine-local" in msg
        assert pc.cmd_capability_get_secret(
            "yoke", "aws-admin", "access_key_id", db_path=cap_db
        ) == "AKIALOCAL"
        path = capability_machine_secrets.machine_capability_secret_path(
            "yoke", "aws-admin", "access_key_id"
        )
        assert path.read_text(encoding="utf-8").strip() == "AKIALOCAL"
        assert path.stat().st_mode & 0o077 == 0

    def test_list_secrets_sorted(self, cap_db: str) -> None:
        pc.cmd_capability_set_secret(
            "yoke", "aws-admin", "secret_access_key", "x", db_path=cap_db
        )
        pc.cmd_capability_set_secret(
            "yoke", "aws-admin", "access_key_id", "y", db_path=cap_db
        )
        assert pc.cmd_capability_list_secrets(
            "yoke", "aws-admin", db_path=cap_db
        ) == "access_key_id\nsecret_access_key"

    def test_set_ssh_private_key_writes_local_file_and_updates_key_path(
        self, cap_db: str
    ) -> None:
        msg = pc.cmd_capability_set_secret(
            "externalwebapp", "ssh", "private_key", "new-pem", db_path=cap_db
        )

        assert "machine-local" in msg
        assert pc.cmd_capability_get_secret(
            "externalwebapp", "ssh", "private_key", db_path=cap_db
        ) == "new-pem"
        assert pc.cmd_capability_list_secrets(
            "externalwebapp", "ssh", db_path=cap_db
        ) == "private_key"
        path = capability_machine_secrets.machine_capability_secret_path(
            "externalwebapp", "ssh", "private_key"
        )
        assert path.read_text(encoding="utf-8").strip() == "new-pem"
        assert path.stat().st_mode & 0o077 == 0
        conn = connect_test_db(cap_db)
        try:
            settings_text = conn.execute(
                "SELECT settings FROM project_capabilities "
                "WHERE project_id = 2 AND type = 'ssh'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert json_helper.loads_text(settings_text)["key_path"] == str(path)

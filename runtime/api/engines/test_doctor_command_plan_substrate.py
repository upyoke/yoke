"""Doctor validation of registered Command plans and checkout substrates."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import (
    clear_machine_checkout,
    register_machine_checkout,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_test_command_validity,
)


def _apply_command_substrate_schema() -> None:
    """Create the minimal projects + QA Command-plan validation substrate."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(
            conn,
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                name TEXT,
                github_repo TEXT,
                public_item_prefix TEXT DEFAULT 'YOK'
            );
            CREATE TABLE qa_plans (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                slug TEXT NOT NULL,
                retired_at TIMESTAMPTZ
            );
            CREATE TABLE qa_plan_cases (
                id INTEGER PRIMARY KEY,
                plan_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                method_id TEXT NOT NULL,
                method_config TEXT NOT NULL
            );
            """,
        )
        conn.commit()
    finally:
        conn.close()


class TestTestCommandValidity:
    """Command-plan checks use one isolated disposable database."""

    def _run(self, tmp_path, checkout_path, *, remove_checkout=False, **scopes):
        """Build a disposable DB with Command plans and run the HC."""
        with init_test_db(
            tmp_path, apply_schema=_apply_command_substrate_schema
        ) as db_path:
            seed = connect_test_db(db_path)
            try:
                seed.execute(
                    "INSERT INTO projects "
                    "(id, slug, name, public_item_prefix) "
                    "VALUES (2, 'externalwebapp', 'ExternalWebapp', 'EXT')",
                )
                for offset, (scope, command) in enumerate(
                    ((scope, command) for scope, command in scopes.items() if command),
                    start=1,
                ):
                    seed.execute(
                        "INSERT INTO qa_plans("
                        "id, project_id, slug, retired_at"
                        ") VALUES (%s, 2, %s, NULL)",
                        (offset, f"registered-command-{scope}"),
                    )
                    seed.execute(
                        "INSERT INTO qa_plan_cases("
                        "id, plan_id, position, method_id, method_config"
                        ") VALUES (%s, %s, 1, 'command', %s)",
                        (offset, offset, json.dumps({"command": command})),
                    )
                seed.commit()
            finally:
                seed.close()
            if checkout_path:
                checkout = Path(checkout_path)
                if checkout.is_dir():
                    register_machine_checkout(checkout.parent, checkout, 2)
                    if remove_checkout:
                        checkout.rmdir()
                else:
                    clear_machine_checkout(2)
            else:
                clear_machine_checkout(2)
            conn = connect_test_db(db_path)
            try:
                rec = RecordCollector()
                hc_test_command_validity(
                    conn, DoctorArgs(project="yoke", db_path=db_path), rec
                )
                return rec.results[0]
            finally:
                conn.close()

    def test_passes_when_project_commands_all_resolve(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        (repo_path / "package.json").write_text('{"name":"externalwebapp"}\n')
        e2e_script = repo_path / "e2e.sh"
        e2e_script.write_text("#!/usr/bin/env sh\necho test\n")
        e2e_script.chmod(0o755)
        result = self._run(
            tmp_path,
            str(repo_path),
            quick="python3 -m pytest -q",
            full="npm test",
            e2e="sh e2e.sh",
        )
        assert result.result == "PASS"

    def test_passes_when_no_commands_configured(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        result = self._run(tmp_path, str(repo_path))
        assert result.result == "PASS"

    def test_warns_when_script_missing(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        result = self._run(
            tmp_path, str(repo_path), quick="sh scripts/does-not-exist.sh"
        )
        assert result.result == "WARN"
        assert "externalwebapp.quick" in result.detail
        assert "does-not-exist.sh" in result.detail

    def test_warns_when_npm_has_no_package_json(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        result = self._run(tmp_path, str(repo_path), e2e="npm run test:browser")
        assert result.result == "WARN"
        assert "package.json" in result.detail

    def test_warns_when_checkout_mapping_is_missing(self, tmp_path):
        result = self._run(tmp_path, "", quick="sh scripts/run.sh")
        assert result.result == "WARN"
        assert "no machine-local checkout mapping" in result.detail

    def test_warns_when_mapped_checkout_is_not_a_directory(self, tmp_path):
        bogus_path = tmp_path / "does-not-exist"
        bogus_path.mkdir()
        result = self._run(
            tmp_path,
            str(bogus_path),
            remove_checkout=True,
            quick="sh scripts/run.sh",
        )
        assert result.result == "WARN"

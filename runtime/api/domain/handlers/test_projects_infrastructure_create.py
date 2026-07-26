"""Tests for the ``projects.site.create`` / ``projects.environment.create`` handlers."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import projects_restart
from yoke_core.domain.handlers import projects_infrastructure_create as handlers
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

YOKE_PROJECT = "yoke"
WEBAPP_PROJECT = "externalwebapp"
SITE = "externalwebapp-web"
ENVIRONMENT = "externalwebapp-web-stage"


@pytest.fixture
def infrastructure_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        projects_restart.cmd_init()
        yield db_path


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id=""),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _create_site(project: str = WEBAPP_PROJECT, **extra):
    return handlers.handle_projects_site_create(
        _request(
            "projects.site.create",
            {"project": project, "site_slug": SITE, **extra},
        )
    )


def _create_environment(project: str = WEBAPP_PROJECT, **extra):
    payload = {
        "project": project,
        "site_slug": SITE,
        "environment_id": ENVIRONMENT,
        **extra,
    }
    return handlers.handle_projects_environment_create(
        _request("projects.environment.create", payload)
    )


class TestSiteCreate:
    def test_creates_site_row_with_settings(self, infrastructure_db) -> None:
        outcome = _create_site(settings={"region": "us-east-1"})
        assert outcome.primary_success is True
        assert outcome.result_payload == {
            "project": WEBAPP_PROJECT,
            "site_id": SITE,
            "outcome": handlers.OUTCOME_CREATED,
        }
        conn = connect_test_db(infrastructure_db)
        try:
            row = conn.execute(
                "SELECT project_id, name, settings FROM sites WHERE id = %s",
                (SITE,),
            ).fetchone()
        finally:
            conn.close()
        assert int(row[0]) == 2
        assert str(row[1]) == SITE
        assert '"region"' in str(row[2])

    def test_recreate_reports_already_present_untouched(
        self, infrastructure_db,
    ) -> None:
        _create_site(settings={"region": "us-east-1"})
        second = _create_site(settings={"region": "eu-west-1"})
        assert second.primary_success is True
        assert second.result_payload["outcome"] == handlers.OUTCOME_ALREADY_PRESENT
        conn = connect_test_db(infrastructure_db)
        try:
            row = conn.execute(
                "SELECT settings FROM sites WHERE id = %s", (SITE,),
            ).fetchone()
        finally:
            conn.close()
        assert "us-east-1" in str(row[0])
        assert "eu-west-1" not in str(row[0])

    def test_slug_owned_by_another_project_refuses(self, infrastructure_db) -> None:
        _create_site()
        outcome = _create_site(project=YOKE_PROJECT)
        assert outcome.primary_success is False
        assert outcome.error.code == "site_project_mismatch"

    def test_unknown_project_refuses(self, infrastructure_db) -> None:
        outcome = _create_site(project="no-such-project")
        assert outcome.primary_success is False
        assert outcome.error.code == "project_not_found"


class TestEnvironmentCreate:
    def test_creates_environment_under_project_site(
        self, infrastructure_db,
    ) -> None:
        _create_site()
        outcome = _create_environment(settings={"branch": "main"})
        assert outcome.primary_success is True
        assert outcome.result_payload == {
            "project": WEBAPP_PROJECT,
            "site_id": SITE,
            "environment_id": ENVIRONMENT,
            "name": "stage",
            "outcome": handlers.OUTCOME_CREATED,
        }
        conn = connect_test_db(infrastructure_db)
        try:
            row = conn.execute(
                "SELECT site, name, settings FROM environments WHERE id = %s",
                (ENVIRONMENT,),
            ).fetchone()
        finally:
            conn.close()
        assert (str(row[0]), str(row[1])) == (SITE, "stage")
        assert '"branch"' in str(row[2])

    def test_recreate_reports_already_present_untouched(
        self, infrastructure_db,
    ) -> None:
        _create_site()
        _create_environment(settings={"branch": "main"})
        second = _create_environment(settings={"branch": "other"})
        assert second.primary_success is True
        assert second.result_payload["outcome"] == handlers.OUTCOME_ALREADY_PRESENT
        assert second.result_payload["name"] == "stage"
        conn = connect_test_db(infrastructure_db)
        try:
            row = conn.execute(
                "SELECT settings FROM environments WHERE id = %s", (ENVIRONMENT,),
            ).fetchone()
        finally:
            conn.close()
        assert '"main"' in str(row[0])

    def test_site_owned_by_another_project_refuses(
        self, infrastructure_db,
    ) -> None:
        _create_site()
        outcome = _create_environment(project=YOKE_PROJECT)
        assert outcome.primary_success is False
        assert outcome.error.code == "site_project_mismatch"

    def test_missing_site_refuses_with_create_teaching(
        self, infrastructure_db,
    ) -> None:
        outcome = _create_environment()
        assert outcome.primary_success is False
        assert outcome.error.code == "site_not_found"
        assert "projects.site.create" in outcome.error.message

    def test_environment_owned_by_another_site_refuses(
        self, infrastructure_db,
    ) -> None:
        _create_site()
        _create_environment()
        other = handlers.handle_projects_site_create(
            _request(
                "projects.site.create",
                {"project": WEBAPP_PROJECT, "site_slug": "externalwebapp-admin"},
            )
        )
        assert other.primary_success is True
        outcome = handlers.handle_projects_environment_create(
            _request(
                "projects.environment.create",
                {
                    "project": WEBAPP_PROJECT,
                    "site_slug": "externalwebapp-admin",
                    "environment_id": ENVIRONMENT,
                },
            )
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "environment_site_mismatch"

    def test_name_falls_back_to_id_without_site_prefix(
        self, infrastructure_db,
    ) -> None:
        _create_site()
        outcome = handlers.handle_projects_environment_create(
            _request(
                "projects.environment.create",
                {
                    "project": WEBAPP_PROJECT,
                    "site_slug": SITE,
                    "environment_id": "prod",
                },
            )
        )
        assert outcome.primary_success is True
        assert outcome.result_payload["name"] == "prod"


def test_registration_specs_cover_both_function_ids() -> None:
    ids = [spec["function_id"] for spec in handlers.REGISTRATION_SPECS]
    assert ids == ["projects.site.create", "projects.environment.create"]
    for spec in handlers.REGISTRATION_SPECS:
        assert callable(spec["handler"])

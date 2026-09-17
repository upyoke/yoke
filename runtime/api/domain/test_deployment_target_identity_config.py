"""Reading a project's served-revision configuration, absence included.

Three answers have to stay three answers here: a configured path, no
configuration at all, and a configuration that could not be read. Collapsing
the third into the second is what would let an unprovable release definition
activate on the strength of a failed read, so each case is asserted
separately rather than through one truthiness check.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.deployment_target_identity_config import (
    IDENTITY_CAPABILITY,
    environment_urls,
    identity_origin_for,
    identity_path_from_settings,
    persistent_identity_path,
    qa_target_environment_names,
    run_target_identity,
)

PATH = "/candidate-revision"


def _declare_identity_capability(conn: Any, settings: Any) -> None:
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (1, %s, %s)",
        (IDENTITY_CAPABILITY, settings),
    )
    conn.commit()


class TestSettingsDocument:
    def test_a_configured_path_is_read(self) -> None:
        read = identity_path_from_settings(json.dumps({"identity_path": PATH}))
        assert read.path == PATH
        assert read.configured is True
        assert read.error == ""

    def test_the_liveness_path_alone_configures_no_identity(self) -> None:
        """health_path has always been there; it proves nothing about revision."""
        read = identity_path_from_settings(
            json.dumps({"health_path": "/", "smoke_paths": ["/login"]})
        )
        assert read.configured is False
        assert read.error == ""

    def test_an_empty_document_configures_nothing(self) -> None:
        for empty in ("", "   ", "{}", None):
            read = identity_path_from_settings(empty)
            assert read.configured is False
            assert read.error == "", empty

    def test_an_unreadable_document_is_an_error_not_an_absence(self) -> None:
        read = identity_path_from_settings("{not json")
        assert read.configured is False
        assert "readable JSON" in read.error
        assert "unknown rather than absent" in read.error

    def test_a_document_that_is_not_an_object_is_an_error(self) -> None:
        read = identity_path_from_settings(json.dumps(["/rev"]))
        assert read.configured is False
        assert "not an object" in read.error

    def test_a_path_leaving_the_origin_is_refused_where_it_is_set(self) -> None:
        """The origin is the environment's own url; a setting only picks a path."""
        read = identity_path_from_settings(
            json.dumps({"identity_path": "https://attacker.test/rev"})
        )
        assert read.configured is False
        assert "scheme or host" in read.error

    def test_a_protocol_relative_url_is_refused_as_a_host(self) -> None:
        """//host/rev names a host, which is the same escape as a full URL."""
        read = identity_path_from_settings(json.dumps({"identity_path": "//host/rev"}))
        assert read.configured is False
        assert "scheme or host" in read.error

    def test_an_ambiguous_leading_slash_run_is_refused(self) -> None:
        """///rev names no host but is read as one by some clients."""
        read = identity_path_from_settings(json.dumps({"identity_path": "///rev"}))
        assert read.configured is False
        assert "names a host" in read.error

    def test_a_bare_path_without_a_leading_slash_is_refused(self) -> None:
        read = identity_path_from_settings(json.dumps({"identity_path": "rev"}))
        assert read.configured is False
        assert "beneath an origin" in read.error


class TestStoredCapability:
    def test_a_project_with_no_capability_row_configures_nothing(
        self, test_db: Any
    ) -> None:
        read = persistent_identity_path(test_db, 1)
        assert read.configured is False
        assert read.error == ""

    def test_a_stored_path_is_read(self, test_db: Any) -> None:
        _declare_identity_capability(test_db, json.dumps({"identity_path": PATH}))

        assert persistent_identity_path(test_db, 1).path == PATH

    def test_a_stored_document_that_cannot_be_read_is_an_error(
        self, test_db: Any
    ) -> None:
        _declare_identity_capability(test_db, "{not json")

        read = persistent_identity_path(test_db, 1)
        assert read.configured is False
        assert read.error


class TestEnvironmentOrigins:
    def test_only_registered_environments_answer(self, test_db: Any) -> None:
        """An unregistered name is absent, not an empty-string origin."""
        test_db.execute(
            "INSERT INTO environments (site, project_id, name, url, created_at) "
            "VALUES (1, 1, %s, %s, '2026-01-01T00:00:00Z')",
            ("stage", "https://stage.example.test"),
        )
        test_db.commit()

        assert environment_urls(test_db, 1, ["stage", "nowhere"]) == {
            "stage": "https://stage.example.test"
        }

    def test_no_names_reads_nothing(self, test_db: Any) -> None:
        assert environment_urls(test_db, 1, []) == {}


class TestQaTargetNames:
    def test_every_named_environment_is_collected_once(self) -> None:
        stages = [
            {"name": "deploy", "step_runner": "health-check"},
            {
                "name": "qa",
                "step_runner": "qa",
                "target": {"kind": "persistent_environment", "environment": "stage"},
            },
            {
                "name": "qa-again",
                "step_runner": "qa",
                "target": {"kind": "persistent_environment", "environment": "stage"},
            },
        ]

        assert qa_target_environment_names(stages) == ["stage"]

    def test_a_target_with_no_environment_names_none(self) -> None:
        assert qa_target_environment_names([{"target": {"kind": "run_preview"}}]) == []


class TestOriginSelection:
    """One environment's proof can never be read off another's host."""

    def test_only_the_named_environment_answers(self) -> None:
        projection = {
            "identity_path": PATH,
            "error": "",
            "environment_urls": {
                "stage": "https://stage.example.test",
                "prod": "https://prod.example.test",
            },
        }

        assert identity_origin_for(projection, "stage") == "https://stage.example.test"
        assert identity_origin_for(projection, "prod") == "https://prod.example.test"

    def test_an_environment_the_projection_does_not_name_gets_no_origin(self) -> None:
        """A sibling's url must not stand in — that would prove another target."""
        projection = {
            "identity_path": PATH,
            "error": "",
            "environment_urls": {"prod": "https://prod.example.test"},
        }

        assert identity_origin_for(projection, "stage") == ""

    def test_an_absent_projection_yields_no_origin(self) -> None:
        for empty in ({}, None, {"environment_urls": None}):
            assert identity_origin_for(empty, "stage") == ""


class TestDriverProjection:
    def test_the_driver_gets_the_path_and_the_origin_together(
        self, test_db: Any
    ) -> None:
        """One server-side read, because both facts are control-plane authority."""
        _declare_identity_capability(test_db, json.dumps({"identity_path": PATH}))
        test_db.execute(
            "INSERT INTO environments (site, project_id, name, url, created_at) "
            "VALUES (1, 1, %s, %s, '2026-01-01T00:00:00Z')",
            ("stage", "https://stage.example.test"),
        )
        test_db.commit()

        projection = run_target_identity(
            test_db,
            project_id=1,
            stages=[
                {
                    "name": "qa",
                    "step_runner": "qa",
                    "target": {
                        "kind": "persistent_environment",
                        "environment": "stage",
                    },
                }
            ],
        )

        assert projection == {
            "identity_path": PATH,
            "error": "",
            # The stage the definition names resolves its own answer, which
            # here is the project-wide one because stage states nothing.
            "environment_identity": {"stage": {"path": PATH, "error": ""}},
            "environment_urls": {"stage": "https://stage.example.test"},
        }

    def test_a_read_failure_travels_to_the_driver(self, test_db: Any) -> None:
        """A driver that could not tell would deploy on a failed read."""
        _declare_identity_capability(test_db, "{not json")

        projection = run_target_identity(test_db, project_id=1, stages=[])
        assert projection["identity_path"] == ""
        assert projection["error"]

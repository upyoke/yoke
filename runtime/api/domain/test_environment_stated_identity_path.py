"""An environment states the path it proves its own revision at.

One project reaches its environments under different prefixes — the tenant
segment differs per environment — so a single project-wide path can only
ever be right for one of them. These cover the three answers an environment
can give: its own path, nothing (so the project's applies), and something
unusable (which refuses rather than letting the project's stand in).
"""

from __future__ import annotations

import json
import unittest

from yoke_core.domain.deployment_target_identity_config import (
    identity_path_for,
    persistent_identity_path,
    run_target_identity,
)

from runtime.api.fixtures.pg_testdb import test_database

NOW = "2026-01-01T00:00:00Z"
PROJECT_PATH = "/candidate-revision"
PROD_PATH = "/api/orgs/example/v1/health"
STAGE_PATH = "/api/orgs/example-stage/v1/health"


def _declare_capability(conn, *, path: str = PROJECT_PATH) -> None:
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
        "VALUES (1, 'health-endpoint', %s, %s)",
        (json.dumps({"identity_path": path}), NOW),
    )
    conn.commit()


def _environment(conn, name: str, settings: object = None) -> None:
    conn.execute(
        "INSERT INTO environments (site, project_id, name, url, settings, created_at) "
        "VALUES (1, 1, %s, %s, %s, %s)",
        (
            name,
            f"https://{name}.example.test",
            None if settings is None else json.dumps(settings),
            NOW,
        ),
    )
    conn.commit()


def _stages(*names: str) -> list:
    return [
        {
            "name": f"qa-{name}",
            "step_runner": "qa",
            "target": {"kind": "persistent_environment", "environment": name},
        }
        for name in names
    ]


class TestEachEnvironmentAnswersForItself(unittest.TestCase):
    def test_two_environments_keep_their_own_tenant_prefixes(self):
        with test_database() as conn:
            _declare_capability(conn)
            _environment(conn, "prod", {"qa": {"identity_path": PROD_PATH}})
            _environment(conn, "stage", {"qa": {"identity_path": STAGE_PATH}})

            prod = persistent_identity_path(conn, 1, "prod")
            stage = persistent_identity_path(conn, 1, "stage")

            self.assertEqual(prod.path, PROD_PATH)
            self.assertEqual(stage.path, STAGE_PATH)
            self.assertEqual(prod.error, "")
            self.assertEqual(stage.error, "")

    def test_an_environment_stating_nothing_takes_the_project_path(self):
        with test_database() as conn:
            _declare_capability(conn)
            _environment(conn, "prod", {"qa": {"identity_path": PROD_PATH}})
            _environment(conn, "stage", {"hosts": {"app": "stage.example.test"}})

            stage = persistent_identity_path(conn, 1, "stage")

            self.assertEqual(stage.path, PROJECT_PATH)
            self.assertEqual(stage.error, "")

    def test_an_environment_with_no_settings_at_all_takes_the_project_path(self):
        with test_database() as conn:
            _declare_capability(conn)
            _environment(conn, "prod")

            self.assertEqual(
                persistent_identity_path(conn, 1, "prod").path, PROJECT_PATH
            )

    def test_asking_about_the_project_alone_is_unchanged(self):
        with test_database() as conn:
            _declare_capability(conn)
            _environment(conn, "prod", {"qa": {"identity_path": PROD_PATH}})

            self.assertEqual(persistent_identity_path(conn, 1).path, PROJECT_PATH)


class TestAnUnusableStatementRefuses(unittest.TestCase):
    def _refusal(self, stated: object) -> str:
        with test_database() as conn:
            _declare_capability(conn)
            _environment(conn, "prod", {"qa": {"identity_path": stated}})

            answer = persistent_identity_path(conn, 1, "prod")

            # Never the project's path: this environment tried to answer.
            self.assertEqual(answer.path, "")
            self.assertFalse(answer.configured)
            return answer.error

    def test_a_path_leaving_the_origin_refuses(self):
        self.assertIn("leaves the origin", self._refusal("https://elsewhere.test/rev"))

    def test_a_relative_path_refuses(self):
        self.assertIn("beneath an origin", self._refusal("v1/health"))

    def test_a_protocol_relative_path_refuses(self):
        """'//host/path' names an authority, so it leaves the origin too."""
        self.assertIn("leaves the origin", self._refusal("//elsewhere.test/rev"))

    def test_a_non_string_statement_refuses(self):
        self.assertIn("not a path", self._refusal(42))

    def test_an_empty_statement_refuses(self):
        self.assertIn("is empty", self._refusal("   "))

    def test_unreadable_settings_refuse_rather_than_fall_through(self):
        with test_database() as conn:
            _declare_capability(conn)
            conn.execute(
                "INSERT INTO environments "
                "(site, project_id, name, url, settings, created_at) "
                "VALUES (1, 1, 'prod', 'https://prod.example.test', %s, %s)",
                ("{not json", NOW),
            )
            conn.commit()

            answer = persistent_identity_path(conn, 1, "prod")

            self.assertEqual(answer.path, "")
            self.assertIn("unknown rather than absent", answer.error)


class TestTheReadersAgree(unittest.TestCase):
    def test_the_driver_projection_keys_each_environment_it_targets(self):
        with test_database() as conn:
            _declare_capability(conn)
            _environment(conn, "prod", {"qa": {"identity_path": PROD_PATH}})
            _environment(conn, "stage", {"qa": {"identity_path": STAGE_PATH}})

            projection = run_target_identity(
                conn, project_id=1, stages=_stages("prod", "stage")
            )

            self.assertEqual(identity_path_for(projection, "prod"), (PROD_PATH, ""))
            self.assertEqual(identity_path_for(projection, "stage"), (STAGE_PATH, ""))

    def test_an_environment_the_run_never_named_falls_back(self):
        with test_database() as conn:
            _declare_capability(conn)
            _environment(conn, "prod", {"qa": {"identity_path": PROD_PATH}})

            projection = run_target_identity(conn, project_id=1, stages=_stages("prod"))

            self.assertEqual(identity_path_for(projection, "other"), (PROJECT_PATH, ""))

    def test_an_unusable_statement_reaches_the_driver_as_a_refusal(self):
        with test_database() as conn:
            _declare_capability(conn)
            _environment(conn, "prod", {"qa": {"identity_path": "v1/health"}})

            projection = run_target_identity(conn, project_id=1, stages=_stages("prod"))
            path, error = identity_path_for(projection, "prod")

            self.assertEqual(path, "")
            self.assertIn("beneath an origin", error)

    def test_the_browser_reader_resolves_the_same_path(self):
        """The Browser case names its environment and gets that answer."""
        from yoke_core.domain.browser_qa_case_target import (
            resolve_case_deployment_under_test,
        )
        from runtime.api.fixtures.backlog_inserts import insert_item
        from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement

        with test_database() as conn:
            _declare_capability(conn)
            _environment(conn, "prod", {"qa": {"identity_path": PROD_PATH}})
            insert_item(conn, id=9701, title="Bound to production")
            insert_qa_requirement(
                conn,
                id=9702,
                item_id=9701,
                qa_kind="method_case",
                method_id="browser-inspection",
                execution_target_json=json.dumps(
                    {
                        "schema": 2,
                        "environment": {"name": "prod"},
                        "project": {"id": 1, "slug": "example", "name": "Example"},
                        "endpoints": {"app_url": "https://prod.example.test"},
                    }
                ),
            )
            conn.commit()

            bound = resolve_case_deployment_under_test(
                conn, requirement_id=9702, project_id=1
            )

            assert bound is not None
            self.assertEqual(bound.identity_path, PROD_PATH)
            self.assertEqual(bound.identity_error, "")


if __name__ == "__main__":
    unittest.main()

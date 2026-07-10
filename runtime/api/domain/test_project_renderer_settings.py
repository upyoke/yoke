"""Tests for DB-backed project renderer settings loading."""

from __future__ import annotations

import json

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
    _load_project_renderer_settings,
    select_primary_environment,
)
from yoke_core.domain.project_renderer_values import _values_from_settings


class TestProjectRendererSettingsLoader:
    def test_loads_db_settings_homes_and_maps_renderer_values(self):
        db_name = pg_testdb.create_test_database()
        conn = pg_testdb.drop_database_on_close(
            pg_testdb.connect_test_database(db_name), db_name,
        )
        try:
            conn.execute(
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, "
                "name TEXT, public_item_prefix TEXT DEFAULT 'YOK')"
            )
            conn.execute(
                "CREATE TABLE sites (id TEXT PRIMARY KEY, project_id INTEGER, "
                "name TEXT, settings TEXT)"
            )
            conn.execute(
                "CREATE TABLE environments (id TEXT PRIMARY KEY, site TEXT, "
                "name TEXT, settings TEXT)"
            )
            conn.execute(
                "CREATE TABLE project_capabilities (project_id INTEGER, type TEXT, "
                "settings TEXT)"
            )
            conn.execute(
                "INSERT INTO projects (id, slug, name) VALUES (%s, %s, %s)",
                (2, "buzz", "Buzz"),
            )
            conn.execute(
                "INSERT INTO sites (id, project_id, name, settings) "
                "VALUES (%s, %s, %s, %s)",
                (
                    "buzz-web",
                    2,
                    "Buzz Web",
                    json.dumps({
                        "domains": [{
                            "domain_name": "buzzabuzz.com",
                            "hosted_zone_id": "ZBUZZ",
                            "certificate_arn": "arn:aws:acm:cert/buzz",
                            "dns_provider": "route53",
                        }],
                        "cdn": {
                            "origin_id": "buzzOrigin",
                            "distribution_id": "EDIST",
                            "distribution_domain": "d123.cloudfront.net",
                        },
                    }),
                ),
            )
            conn.execute(
                "INSERT INTO environments (id, site, name, settings) "
                "VALUES (%s, %s, %s, %s)",
                (
                    "buzz-web-production",
                    "buzz-web",
                    "production",
                    json.dumps({
                        "hosts": {"origin": "origin.buzz.example.com"},
                        "servers": [{
                            "host": "203.0.113.50",
                            "description": "Buzz VPS",
                        }],
                    }),
                ),
            )
            for cap_type, settings in (
                ("aws-admin", {"region": "us-east-1", "account_id": "123"}),
                ("ssh", {"default_user": "ubuntu"}),
                ("webapp-runtime", {"web_port": 3000, "api_port": 8000}),
                ("health-endpoint", {"health_path": "/", "smoke_paths": ["/login"]}),
                ("ephemeral-env", {"web_base_port": 4000, "api_base_port": 9000}),
            ):
                conn.execute(
                    "INSERT INTO project_capabilities (project_id, type, settings) "
                    "VALUES (%s, %s, %s)",
                    (2, cap_type, json.dumps(settings)),
                )

            settings = _load_project_renderer_settings(conn, "buzz")
            values = _values_from_settings("buzz", settings)

            assert settings.display_name == "Buzz"
            assert settings.site_id == "buzz-web"
            assert settings.primary_environment is not None
            assert settings.primary_environment.name == "production"
            assert settings.capabilities["ssh"]["default_user"] == "ubuntu"
            assert values["domain_name"] == "buzzabuzz.com"
            assert values["origin_host"] == "origin.buzz.example.com"
            assert values["origin_ip"] == "203.0.113.50"
            assert values["cloudfront_id"] == "EDIST"
            assert values["web_smoke_paths"] == "/login"
            assert values["port_base"] == "4000"
            assert values["api_port_base"] == "9000"
        finally:
            conn.close()

    def test_renderer_primary_flag_pins_primary_over_id_order(self):
        """A flagged row stays primary when a settings-home row sorts first.

        Without the flag, the settings-home row (id sorts earlier, no
        hosts/servers) would become primary and origin values would
        render empty.
        """
        db_name = pg_testdb.create_test_database()
        conn = pg_testdb.drop_database_on_close(
            pg_testdb.connect_test_database(db_name), db_name,
        )
        try:
            conn.execute(
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, "
                "name TEXT, public_item_prefix TEXT DEFAULT 'YOK')"
            )
            conn.execute(
                "CREATE TABLE sites (id TEXT PRIMARY KEY, project_id INTEGER, "
                "name TEXT, settings TEXT)"
            )
            conn.execute(
                "CREATE TABLE environments (id TEXT PRIMARY KEY, site TEXT, "
                "name TEXT, settings TEXT)"
            )
            conn.execute(
                "INSERT INTO projects (id, slug, name) VALUES (%s, %s, %s)",
                (2, "buzz", "Buzz"),
            )
            conn.execute(
                "INSERT INTO sites (id, project_id, name, settings) "
                "VALUES (%s, %s, %s, %s)",
                ("buzz-web", 2, "Buzz Web", json.dumps({"domains": [
                    {"domain_name": "buzzabuzz.com"},
                ]})),
            )
            conn.execute(
                "INSERT INTO environments (id, site, name, settings) "
                "VALUES (%s, %s, %s, %s)",
                (
                    "buzz-web-a-home",
                    "buzz-web",
                    "settings-home",
                    json.dumps({"integrations": {"mail": "smtp.example.com"}}),
                ),
            )
            conn.execute(
                "INSERT INTO environments (id, site, name, settings) "
                "VALUES (%s, %s, %s, %s)",
                (
                    "buzz-web-live",
                    "buzz-web",
                    "live",
                    json.dumps({
                        "renderer_primary": True,
                        "hosts": {"origin": "origin.buzz.example.com"},
                        "servers": [{"host": "203.0.113.50"}],
                    }),
                ),
            )

            settings = _load_project_renderer_settings(conn, "buzz")
            values = _values_from_settings("buzz", settings)

            assert settings.primary_environment is not None
            assert settings.primary_environment.id == "buzz-web-live"
            assert values["origin_host"] == "origin.buzz.example.com"
            assert values["origin_ip"] == "203.0.113.50"
        finally:
            conn.close()


def _env(env_id: str, name: str = "", **settings) -> RendererEnvironmentSettings:
    return RendererEnvironmentSettings(id=env_id, name=name, settings=settings)


class TestSelectPrimaryEnvironment:
    def test_no_flag_selects_first_row(self):
        first = _env("api-alpha")
        second = _env("api-beta")
        assert select_primary_environment((first, second)) is first

    def test_falsy_flag_is_not_a_pin(self):
        first = _env("api-alpha", renderer_primary=False)
        assert select_primary_environment((first, _env("api-beta"))) is first

    def test_flag_on_later_sorting_row_wins(self):
        settings_home = _env("api-a-home")
        live = _env("api-live", renderer_primary=True)
        assert select_primary_environment((settings_home, live)) is live

    def test_first_flagged_row_wins_when_multiple_flagged(self):
        unflagged = _env("api-a")
        flagged_first = _env("api-b", renderer_primary=True)
        flagged_second = _env("api-c", renderer_primary=True)
        selected = select_primary_environment(
            (unflagged, flagged_first, flagged_second),
        )
        assert selected is flagged_first

    def test_empty_environments_yield_none(self):
        assert select_primary_environment(()) is None


def _settings_with_ephemeral(ephemeral: dict) -> ProjectRendererSettings:
    return ProjectRendererSettings(
        project="buzz",
        deploy_namespace="buzz",
        display_name="Buzz",
        site_id="buzz-web",
        site_settings={},
        primary_environment=None,
        environments=(),
        capabilities={"ephemeral-env": ephemeral},
    )


class TestEphemeralPortBaseKeys:
    """``web_base_port`` is the only WEB base-port key.

    The retired ``base_port`` alias carried the API base (9000) on live
    rows; reading it as the web fallback would silently render web
    previews onto the API port range.
    """

    def test_web_base_port_feeds_port_base(self):
        values = _values_from_settings(
            "buzz", _settings_with_ephemeral({"web_base_port": 4100}),
        )
        assert values["port_base"] == "4100"

    def test_retired_base_port_alias_is_ignored(self):
        values = _values_from_settings(
            "buzz", _settings_with_ephemeral({"base_port": 9000}),
        )
        assert values["port_base"] == "4000"  # default, not the alias value

    def test_api_base_port_feeds_api_port_base(self):
        values = _values_from_settings(
            "buzz", _settings_with_ephemeral({"api_base_port": 9100}),
        )
        assert values["api_port_base"] == "9100"

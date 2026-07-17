"""CLI round-trip tests for ``yoke templates list`` / ``yoke templates fetch``."""

from __future__ import annotations

import json

import pytest

from runtime.api.cli.project_onboarding_test_helpers import write_https_config
from yoke_contracts.template_bundle import (
    TEMPLATE_PRODUCT_BOUNDARY_FIELD,
    TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN,
    TEMPLATES_API_PATH,
)
from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import template_fetch
from yoke_cli.config.template_fetch import TemplateFetchError
from yoke_cli.transport.https import HttpsConnection
from yoke_core.domain import template_bundle as template_bundle_domain


@pytest.fixture(autouse=True)
def machine_home(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


def _fake_bundle() -> dict:
    return {
        "bundle_schema": 1,
        "yoke_version": "0.1.0",
        "template": "alpha",
        "description": "Alpha raw material",
        "files": [
            {"path": "README.md", "content": "# Alpha\n"},
            {"path": "ops/deploy.yml", "content": "name: {{project_name}}\n"},
            {"path": "ops/sub/run.yml", "content": "run: true\n"},
        ],
        "binary_files_skipped": 1,
    }


def _fake_source_dev_admin_bundle() -> dict:
    bundle = _fake_bundle()
    bundle["template"] = "admin"
    bundle[TEMPLATE_PRODUCT_BOUNDARY_FIELD] = (
        TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN
    )
    return bundle


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        body = json.dumps(self._payload).encode("utf-8")
        return body if size < 0 else body[:size]

    def geturl(self) -> str:
        return "https://api.example/v1/templates"


@pytest.fixture()
def fake_bundle(monkeypatch):
    monkeypatch.setattr(
        template_fetch, "resolve_bundle",
        lambda name, config_path=None, include_source_dev_admin=False: (
            _fake_bundle(), "test"
        ),
    )


@pytest.fixture()
def fake_listing(monkeypatch):
    monkeypatch.setattr(
        template_fetch, "resolve_listing",
        lambda config_path=None: (
            [
                {"name": "alpha", "description": "Alpha raw material",
                 "file_count": 3},
                {"name": "beta", "description": "", "file_count": 1},
            ],
            "test",
        ),
    )


class TestTemplatesList:
    def test_human_output_names_each_template(self, fake_listing, capsys) -> None:
        rc = yoke_operations_cli.main(["templates", "list"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "alpha (3 files) — Alpha raw material" in out
        assert "beta (1 files)" in out

    def test_json_output_carries_listing_and_source(
        self, fake_listing, capsys
    ) -> None:
        rc = yoke_operations_cli.main(["templates", "list", "--json"])

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["source"] == "test"
        assert [t["name"] for t in report["templates"]] == ["alpha", "beta"]

    def test_listing_failure_exits_nonzero(self, monkeypatch, capsys) -> None:
        def _boom(config_path=None):
            raise TemplateFetchError("no templates surface")

        monkeypatch.setattr(template_fetch, "resolve_listing", _boom)

        rc = yoke_operations_cli.main(["templates", "list"])

        assert rc == 1
        assert "no templates surface" in capsys.readouterr().err

    def test_https_listing_accepts_versioned_api_url(self, monkeypatch) -> None:
        captured = {}

        def _urlopen(request, timeout=None):
            captured["url"] = request.full_url
            return _JsonResponse({"templates": []})

        monkeypatch.setattr(template_fetch.urllib.request, "urlopen", _urlopen)

        payload = template_fetch._fetch_json_https(
            HttpsConnection(api_url="https://api.example/v1", token="tok"),
            TEMPLATES_API_PATH,
        )

        assert payload == {"templates": []}
        assert captured["url"] == "https://api.example/v1/templates"


class TestTemplatesFetch:
    def test_fetch_writes_files_under_dest(
        self, fake_bundle, tmp_path, capsys
    ) -> None:
        dest = tmp_path / "material"

        rc = yoke_operations_cli.main(
            ["templates", "fetch", "alpha", "--dest", str(dest)]
        )

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["operation"] == "fetch"
        assert report["template"] == "alpha"
        assert report["product_boundary"] == "product"
        assert report["files_written"] == [
            "README.md", "ops/deploy.yml", "ops/sub/run.yml",
        ]
        assert report["binary_files_skipped"] == 1
        assert (dest / "README.md").read_text() == "# Alpha\n"
        # Raw delivery: placeholders ship verbatim.
        assert (dest / "ops/deploy.yml").read_text() == "name: {{project_name}}\n"

    def test_only_prefix_filters_bundle_paths(
        self, fake_bundle, tmp_path, capsys
    ) -> None:
        dest = tmp_path / "material"

        rc = yoke_operations_cli.main(
            ["templates", "fetch", "alpha", "--dest", str(dest), "--only", "ops/"]
        )

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["only"] == "ops/"
        assert report["files_written"] == ["ops/deploy.yml", "ops/sub/run.yml"]
        assert not (dest / "README.md").exists()

    def test_existing_files_are_skipped_and_reported(
        self, fake_bundle, tmp_path, capsys
    ) -> None:
        dest = tmp_path / "material"
        dest.mkdir()
        (dest / "README.md").write_text("operator-authored\n")

        rc = yoke_operations_cli.main(
            ["templates", "fetch", "alpha", "--dest", str(dest)]
        )

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["files_skipped_existing"] == ["README.md"]
        assert "README.md" not in report["files_written"]
        assert (dest / "README.md").read_text() == "operator-authored\n"

    def test_force_overwrites_existing_files(
        self, fake_bundle, tmp_path, capsys
    ) -> None:
        dest = tmp_path / "material"
        dest.mkdir()
        (dest / "README.md").write_text("operator-authored\n")

        rc = yoke_operations_cli.main(
            ["templates", "fetch", "alpha", "--dest", str(dest), "--force"]
        )

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert "README.md" in report["files_written"]
        assert report["files_skipped_existing"] == []
        assert (dest / "README.md").read_text() == "# Alpha\n"

    def test_source_dev_admin_template_requires_opt_in(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        monkeypatch.setattr(
            template_fetch, "resolve_bundle",
            lambda name, config_path=None, include_source_dev_admin=False: (
                _fake_source_dev_admin_bundle(), "test"
            ),
        )

        rc = yoke_operations_cli.main(
            ["templates", "fetch", "admin", "--dest", str(tmp_path / "material")]
        )

        assert rc == 1
        assert "source-dev/admin" in capsys.readouterr().err

    def test_source_dev_admin_opt_in_fetches_template(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        seen = {}

        def _resolve(name, config_path=None, include_source_dev_admin=False):
            seen["include_source_dev_admin"] = include_source_dev_admin
            return _fake_source_dev_admin_bundle(), "test"

        monkeypatch.setattr(template_fetch, "resolve_bundle", _resolve)
        dest = tmp_path / "material"

        rc = yoke_operations_cli.main(
            [
                "templates", "fetch", "admin",
                "--source-dev-admin",
                "--dest", str(dest),
            ]
        )

        assert rc == 0
        assert seen["include_source_dev_admin"] is True
        report = json.loads(capsys.readouterr().out)
        assert report["product_boundary"] == "source-dev/admin"
        assert (dest / "README.md").read_text() == "# Alpha\n"

    def test_unknown_template_exits_nonzero(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        def _missing(name, config_path=None, include_source_dev_admin=False):
            raise TemplateFetchError(f"template {name!r} does not exist")

        monkeypatch.setattr(template_fetch, "resolve_bundle", _missing)

        rc = yoke_operations_cli.main(
            ["templates", "fetch", "gamma", "--dest", str(tmp_path / "x")]
        )

        assert rc == 1
        assert "gamma" in capsys.readouterr().err


def _write_local_config(tmp_path, *, prod: bool = False):
    """A machine config whose active env is a local-postgres connection."""
    connection: dict = {"transport": "local-postgres"}
    if prod:
        connection["prod"] = True
    config = tmp_path / "local-config.json"
    config.write_text(
        json.dumps({
            "schema_version": 1,
            "active_env": "local",
            "connections": {"local": connection},
        }),
        encoding="utf-8",
    )
    return config


@pytest.fixture()
def local_server_tree(tmp_path, monkeypatch):
    """A fake install code tree with a product and a source-dev template."""
    root = tmp_path / "tree"
    alpha = root / "templates" / "alpha"
    (alpha / "ops").mkdir(parents=True)
    (alpha / "template.json").write_text(
        json.dumps({"description": "Alpha raw material"}), encoding="utf-8",
    )
    (alpha / "README.md").write_text("# Alpha\n", encoding="utf-8")
    (alpha / "ops" / "deploy.yml").write_text(
        "name: {{project_name}}\n", encoding="utf-8",
    )
    gamma = root / "templates" / "gamma"
    gamma.mkdir(parents=True)
    (gamma / "template.json").write_text(
        json.dumps({
            TEMPLATE_PRODUCT_BOUNDARY_FIELD: (
                TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN
            ),
        }),
        encoding="utf-8",
    )
    (gamma / "admin.md").write_text("# Gamma\n", encoding="utf-8")
    monkeypatch.setattr(template_bundle_domain, "server_tree_root", lambda: root)
    return root


class TestTemplatesLocalTransport:
    """A non-prod local env serves templates in-process from its own tree."""

    def test_local_env_serves_listing_in_process(
        self, local_server_tree, tmp_path, capsys
    ) -> None:
        config = _write_local_config(tmp_path)

        rc = yoke_operations_cli.main(
            ["templates", "list", "--config", str(config), "--json"]
        )

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["source"] == "local-postgres:local"
        by_name = {t["name"]: t for t in report["templates"]}
        assert sorted(by_name) == ["alpha", "gamma"]
        assert by_name["alpha"]["description"] == "Alpha raw material"
        assert by_name["alpha"]["file_count"] == 3

    def test_local_fetch_writes_the_built_bundle_contents(
        self, local_server_tree, tmp_path, capsys
    ) -> None:
        config = _write_local_config(tmp_path)
        dest = tmp_path / "material"

        rc = yoke_operations_cli.main(
            ["templates", "fetch", "alpha", "--dest", str(dest),
             "--config", str(config)]
        )

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["source"] == "local-postgres:local"
        expected = template_bundle_domain.build_template_bundle("alpha")
        assert report["yoke_version"] == expected["yoke_version"]
        assert report["files_written"] == [
            entry["path"] for entry in expected["files"]
        ]
        for entry in expected["files"]:
            written = (dest / entry["path"]).read_text(encoding="utf-8")
            assert written == entry["content"]
        # Raw delivery: placeholders ship verbatim.
        assert (dest / "ops/deploy.yml").read_text(
            encoding="utf-8"
        ) == "name: {{project_name}}\n"

    def test_local_unknown_template_names_known_ones(
        self, local_server_tree, tmp_path, capsys
    ) -> None:
        config = _write_local_config(tmp_path)

        rc = yoke_operations_cli.main(
            ["templates", "fetch", "missing", "--dest", str(tmp_path / "x"),
             "--config", str(config)]
        )

        assert rc == 1
        err = capsys.readouterr().err
        assert "'missing'" in err
        assert "alpha" in err

    def test_local_source_dev_admin_requires_opt_in(
        self, local_server_tree, tmp_path, capsys
    ) -> None:
        config = _write_local_config(tmp_path)
        dest = tmp_path / "material"

        rc = yoke_operations_cli.main(
            ["templates", "fetch", "gamma", "--dest", str(dest),
             "--config", str(config)]
        )

        assert rc == 1
        assert "source-dev/admin" in capsys.readouterr().err
        assert not (dest / "admin.md").exists()

    def test_local_source_dev_admin_opt_in_fetches(
        self, local_server_tree, tmp_path, capsys
    ) -> None:
        config = _write_local_config(tmp_path)
        dest = tmp_path / "material"

        rc = yoke_operations_cli.main(
            ["templates", "fetch", "gamma", "--source-dev-admin",
             "--dest", str(dest), "--config", str(config)]
        )

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["product_boundary"] == (
            TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN
        )
        assert (dest / "admin.md").read_text(encoding="utf-8") == "# Gamma\n"

    def test_prod_flagged_local_connection_is_refused(
        self, local_server_tree, tmp_path, capsys
    ) -> None:
        config = _write_local_config(tmp_path, prod=True)

        rc = yoke_operations_cli.main(
            ["templates", "list", "--config", str(config), "--json"]
        )

        assert rc == 1
        err = capsys.readouterr().err
        assert "prod-marked local-postgres" in err
        assert "operator-only" in err

    def test_missing_engine_names_repair_instead_of_traceback(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        config = _write_local_config(tmp_path)
        monkeypatch.setattr(
            template_fetch, "_TEMPLATE_BUNDLE_MODULE",
            "yoke_core.domain.template_bundle_absent_for_test",
        )

        rc = yoke_operations_cli.main(
            ["templates", "list", "--config", str(config), "--json"]
        )

        assert rc == 1
        err = capsys.readouterr().err
        assert "yoke-core engine package is not importable" in err
        assert "Traceback" not in err

    def test_https_env_still_fetches_listing_over_https(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        config = write_https_config(
            tmp_path, "product-token", "https://api.example/v1"
        )
        seen = {}

        def _fake_get(connection, route, template=None):
            seen["api_url"] = connection.api_url
            seen["route"] = route
            return {"templates": [
                {"name": "webapp", "description": "", "file_count": 2},
            ]}

        monkeypatch.setattr(template_fetch, "_fetch_json_https", _fake_get)

        rc = yoke_operations_cli.main(
            ["templates", "list", "--config", str(config), "--json"]
        )

        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["source"] == "https://api.example/v1"
        assert seen["api_url"] == "https://api.example/v1"
        assert seen["route"] == TEMPLATES_API_PATH

"""CLI round-trip tests for ``yoke templates list`` / ``yoke templates fetch``."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.template_bundle import (
    TEMPLATE_PRODUCT_BOUNDARY_FIELD,
    TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN,
    TEMPLATES_API_PATH,
)
from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import template_fetch
from yoke_cli.config.template_fetch import TemplateFetchError
from yoke_cli.transport.https import HttpsConnection


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

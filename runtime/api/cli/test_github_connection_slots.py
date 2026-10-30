"""Connection-isolated GitHub authorization, migration and helper selection."""

import copy
import json
from pathlib import Path

import pytest

from runtime.api.cli.test_github_machine_config_concurrency import _seed_connection
from yoke_cli.config import github_git_credential_helper as helper
from yoke_cli.config import github_git_credential_store as store
from yoke_cli.config import github_machine_profile, machine_config, writer
from yoke_contracts import cursor_permissions, github_app_tokens
from yoke_contracts.machine_config import schema as contract


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.delenv("YOKE_ENV", raising=False)
    config = tmp_path / "config.json"
    payload = {
        "schema_version": 1,
        "active_env": "prod",
        "connections": {
            label: {
                "transport": "https",
                "api_url": f"https://{label}.example.test",
                "protected": False,
                "credential_source": {
                    "kind": "token_file",
                    "path": str(tmp_path / label),
                },
            }
            for label in ("prod", "stage")
        },
    }
    for label in ("prod-db-admin", "local"):
        payload["connections"][label] = {
            "transport": "local-postgres",
            "protected": False,
            "credential_source": {"kind": "dsn_file", "path": str(tmp_path / label)},
        }
    config.write_text(json.dumps(payload))
    a, a_path = _seed_connection(
        config, "prod", service_api_url="https://prod.example.test"
    )
    b, b_path = _seed_connection(
        config, "stage", service_api_url="https://stage.example.test"
    )
    return config, payload, a, b, a_path, b_path


def save(config, payload):
    config.write_text(json.dumps(payload))
    config.chmod(0o600)


@pytest.mark.parametrize(
    "env,expected",
    [
        ("prod", "prod"),
        ("stage", "stage"),
        ("prod-db-admin", "prod"),
        ("local", "local"),
    ],
)
def test_slot_label(configured, env, expected):
    _, payload, *_ = configured
    assert github_app_tokens.github_connection_label(payload, env) == expected


@pytest.mark.parametrize(
    "env,slot",
    [
        ("prod", "prod"),
        ("stage", "stage"),
        ("prod-db-admin", "prod"),
        ("local", None),
    ],
)
def test_machine_reader_selects_only_its_slot(configured, monkeypatch, env, slot):
    config, payload, a, b, *_ = configured
    payload["connection_github"] = {"prod": a, "stage": b}
    save(config, payload)
    monkeypatch.setenv("YOKE_ENV", env)
    assert machine_config.github_config(config) == (
        payload["connection_github"][slot] if slot else {}
    )


@pytest.mark.parametrize("env", ["prod", "stage", "prod-db-admin", "local"])
def test_legacy_reader_preserves_record(configured, monkeypatch, env):
    config, payload, a, *_ = configured
    payload["github"] = a
    save(config, payload)
    monkeypatch.setenv("YOKE_ENV", env)
    assert machine_config.github_config(config) == a


def test_write_migrates_legacy_to_provenance_owner(configured, monkeypatch):
    config, payload, a, b, a_path, _ = configured
    payload["github"] = a
    save(config, payload)
    store.claim_config_owner(a_path, config)
    monkeypatch.setenv("YOKE_ENV", "stage")
    writer.set_github(b, expected_credential_ref="", path=config)
    saved = json.loads(config.read_text())
    assert "github" not in saved
    assert saved["connection_github"] == {"prod": a, "stage": b}
    assert a_path.is_file()
    assert (
        str(config.resolve()) in store.read_credential_document(a_path)["config_owners"]
    )


def test_unmatched_migration_preserves_bytes(configured, monkeypatch):
    config, payload, a, b, *_ = configured
    payload["github"] = {**a, "profile_service_api_url": "https://unknown.example.test"}
    save(config, payload)
    before = config.read_bytes()
    monkeypatch.setenv("YOKE_ENV", "stage")
    with pytest.raises(writer.MachineConfigWriteError, match="github disconnect"):
        writer.set_github(b, expected_credential_ref="", path=config)
    assert config.read_bytes() == before
    writer.clear_github(path=config)
    assert "github" not in json.loads(config.read_text())


def test_clear_removes_selected_slot_and_credential_only(configured, monkeypatch):
    config, payload, a, b, a_path, b_path = configured
    payload["connection_github"] = {"prod": a, "stage": b}
    save(config, payload)
    store.claim_config_owner(a_path, config)
    store.claim_config_owner(b_path, config)
    monkeypatch.setenv("YOKE_ENV", "stage")
    writer.clear_github(path=config)
    assert json.loads(config.read_text())["connection_github"] == {"prod": a}
    assert not b_path.exists()
    assert a_path.is_file()
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    writer.clear_github(path=config)
    assert "connection_github" not in json.loads(config.read_text())
    assert not a_path.exists()


def test_cas_and_credential_ownership_are_per_slot(configured, monkeypatch):
    config, payload, a, b, a_path, _ = configured
    payload["connection_github"] = {"prod": a}
    save(config, payload)
    monkeypatch.setenv("YOKE_ENV", "stage")
    with pytest.raises(
        writer.MachineConfigWriteError, match="github_credential_shared"
    ):
        writer.set_github(a, expected_credential_ref="", path=config)
    writer.set_github(b, expected_credential_ref="", path=config)
    with pytest.raises(writer.MachineConfigWriteError, match="changed"):
        writer.clear_github(expected_credential_ref=str(a_path), path=config)
    assert json.loads(config.read_text())["connection_github"] == {
        "prod": a,
        "stage": b,
    }


def test_new_connection_needs_no_profile_replacement(configured, monkeypatch):
    config, payload, a, b, *_ = configured
    payload["connection_github"] = {"prod": a}
    save(config, payload)
    monkeypatch.setenv("YOKE_ENV", "stage")

    class Response:
        def __init__(self, url):
            self.url = url
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return self.url

        def read(self, size=-1):
            values = {
                k: b[k]
                for k in ("client_id", "app_slug", "app_id", "api_url", "web_url")
            }
            return json.dumps({"github_app": {"available": True, **values}}).encode()

    existing, _ = github_machine_profile.resolve(
        config_path=config,
        client_id=None,
        app_slug=None,
        app_id=None,
        api_url=None,
        web_url=None,
        service_api_url="https://stage.example.test",
        use_local_product_profile=False,
        profile_opener=lambda request, timeout: Response(request.full_url),
        replace_profile=False,
        error_type=RuntimeError,
    )
    assert existing == {}


@pytest.mark.parametrize(
    "env,expected", [("stage", "stage"), ("prod-db-admin", "prod")]
)
def test_git_helper_reads_selected_credential(configured, monkeypatch, env, expected):
    config, payload, a, b, a_path, b_path = configured
    payload["connection_github"] = {"prod": a, "stage": b}
    save(config, payload)
    monkeypatch.setenv("YOKE_ENV", env)
    paths = []
    original = store.read_credential_document

    def read(path):
        paths.append(Path(path))
        return original(path)

    monkeypatch.setattr(store, "read_credential_document", read)
    result = helper.access_token_for_git_request(
        config,
        {"protocol": "https", "host": "github.com"},
        opener=lambda *args, **kwargs: pytest.fail("valid cache must not refresh"),
    )
    assert result["access_token"] == f"access-{expected}"
    assert paths == [b_path if expected == "stage" else a_path]


def test_helper_declines_other_connections_checkout(configured, tmp_path, monkeypatch):
    config, payload, a, b, *_ = configured
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    payload["connection_github"] = {"prod": a, "stage": b}
    payload["connection_projects"] = {
        "stage": [{"checkout": str(checkout), "project_id": 1}]
    }
    save(config, payload)
    monkeypatch.chdir(checkout)
    with pytest.raises(store.GitHubCredentialStoreError, match="connection 'stage'"):
        helper.access_token_for_git_request(
            config, {"protocol": "https", "host": "github.com"}
        )


def test_validation_and_unknown_key_paths_are_slot_scoped(configured):
    _, payload, a, b, *_ = configured
    b = copy.deepcopy(b)
    b.pop("authorization")
    b["unexpected"] = True
    payload["connection_github"] = {"prod": a, "stage": b}
    issues = contract.validate_payload(payload)
    assert any(i.path == "connection_github.stage.authorization" for i in issues)
    assert any(i.path == "connection_github.stage.unexpected" for i in issues)


def test_network_permissions_include_every_slot_and_legacy(configured):
    _, payload, a, b, *_ = configured
    payload["connection_github"] = {
        "prod": {**a, "api_url": "https://api.one.test", "web_url": "https://one.test"},
        "stage": {
            **b,
            "api_url": "https://api.two.test",
            "web_url": "https://two.test",
        },
    }
    payload["github"] = {**a, "api_url": "https://legacy.test"}
    assert set(cursor_permissions.control_plane_origins(payload)) >= {
        "api.one.test",
        "one.test",
        "api.two.test",
        "two.test",
        "legacy.test",
    }



def test_helper_checks_external_worktrees_primary_registration(configured, tmp_path, monkeypatch):
    config, payload, a, b, *_ = configured
    primary = tmp_path / "primary"
    gitdir = primary / ".git" / "worktrees" / "external"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..")
    external = tmp_path / "external"
    external.mkdir()
    (external / ".git").write_text(f"gitdir: {gitdir}")
    payload["connection_github"] = {"prod": a, "stage": b}
    payload["connection_projects"] = {"stage": [{"checkout": str(primary), "project_id": 1}]}
    save(config, payload)
    monkeypatch.chdir(external)
    with pytest.raises(store.GitHubCredentialStoreError, match="connection 'stage'"):
        helper.access_token_for_git_request(config, {"protocol": "https", "host": "github.com"})



def test_cli_user_token_uses_checkout_connection(configured, tmp_path, monkeypatch):
    from yoke_cli.config import github_user_tokens
    config, payload, a, b, *_ = configured
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    payload["connection_github"] = {"prod": a, "stage": b}
    payload["connection_projects"] = {"stage": [{"checkout": str(checkout), "project_id": 1}]}
    save(config, payload)
    monkeypatch.chdir(checkout)
    token = github_user_tokens.access_token_from_machine_config(
        config_path=config, _expected_service_api_url="https://stage.example.test"
    )
    assert token.access_token == "access-stage"

"""Git connection routing and safe checkout mismatch diagnostics."""

from io import StringIO

import pytest

from runtime.api.cli.test_github_connection_slots import configured as configured, save
from yoke_cli.config import github_git_credential_helper as helper
from yoke_cli.config import github_git_credential_store as store
from yoke_contracts.machine_config import selection


def prepare(configured, tmp_path, monkeypatch, labels=("prod",)):
    config, payload, prod, stage, *_ = configured
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    payload["active_env"] = "stage"
    payload["connection_github"] = {"prod": prod, "stage": stage}
    payload["connection_projects"] = {
        label: [{"checkout": str(checkout), "project_id": 7}] for label in labels
    }
    monkeypatch.chdir(checkout)
    save(config, payload)
    return config, payload, checkout


def run_helper(config):
    out = StringIO()
    rc = helper.main(
        ["--config", str(config), "get"],
        stdin=StringIO("protocol=https\nhost=github.com\n\n"),
        stdout=out,
    )
    return rc, out.getvalue()


def forbid_credential_read(monkeypatch):
    monkeypatch.setattr(
        store, "read_credential_document",
        lambda *args, **kwargs: pytest.fail("routing refusal must precede credential read"),
    )


def test_override_mismatch(configured, tmp_path, monkeypatch, capsys):
    config, _, checkout = prepare(configured, tmp_path, monkeypatch)
    monkeypatch.setenv("YOKE_ENV", "stage")
    forbid_credential_read(monkeypatch)
    assert run_helper(config) == (1, "")
    err = capsys.readouterr().err
    assert err == (
        "checkout connection mismatch: this checkout is registered to Yoke "
        "connection 'prod' but YOKE_ENV selects 'stage'; unset YOKE_ENV or set "
        "YOKE_ENV=prod for git here, or move the checkout with `yoke --env stage "
        f"project register {checkout.resolve()} --project-id 7 --reassign`\n"
    )
    assert "github connect" not in err


@pytest.mark.parametrize(
    "labels,override,registered,expected",
    [
        (("prod",), None, True, "prod"),
        (("prod",), "prod", True, "prod"),
        ((), None, False, "stage"),
        (("prod-db-admin",), None, True, "prod"),
        (("prod", "stage"), "stage", True, "stage"),
    ],
)
def test_selection_matches_cli(
    configured, tmp_path, monkeypatch, labels, override, registered, expected
):
    config, payload, _ = prepare(configured, tmp_path, monkeypatch, labels)
    if override:
        monkeypatch.setenv("YOKE_ENV", override)
    if not registered:
        monkeypatch.chdir(tmp_path)
    assert helper._git_connection_label(payload) == selection.connection_selection(payload)[0]
    assert run_helper(config) == (
        0, f"username=x-access-token\npassword=access-{expected}\n"
    )


def test_ambiguous_checkout(configured, tmp_path, monkeypatch, capsys):
    config, _, checkout = prepare(
        configured, tmp_path, monkeypatch, ("prod", "stage")
    )
    forbid_credential_read(monkeypatch)
    assert run_helper(config) == (1, "")
    err = capsys.readouterr().err
    assert err == (
        "checkout connection ambiguous: this checkout is registered to Yoke "
        "connections prod, stage; set YOKE_ENV for git here, or move the duplicate "
        f"with `yoke --env ENV project register {checkout.resolve()} "
        "--project-id N --reassign`\n"
    )
    assert "github connect" not in err


def test_deepest_checkout_and_retired_registration(configured, tmp_path, monkeypatch):
    config, payload, checkout = prepare(configured, tmp_path, monkeypatch)
    child = checkout / "child"
    child.mkdir()
    payload["connection_projects"].update({
        "stage": [{"checkout": str(child), "project_id": 8}],
        "retired": [{"checkout": str(child), "project_id": 9}],
    })
    save(config, payload)
    monkeypatch.chdir(child)
    assert helper._git_connection_label(payload) == selection.connection_selection(payload)[0]
    assert run_helper(config) == (0, "username=x-access-token\npassword=access-stage\n")

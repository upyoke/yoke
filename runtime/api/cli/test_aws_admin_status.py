"""`yoke aws admin-status` tells the two halves of aws-admin apart.

A project's AWS credential is a capability row in the control plane plus an
access-key pair on this machine, and either can exist without the other. The
onboarding step that could not tell them apart asked an operator to re-enter
two secrets that were already on disk, so the report names the missing half and
only the command that fills it. The paired refusal covers the flag pair two
separate runs guessed at: settings are one document, and `--key` belongs to the
secret surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import aws
from yoke_cli.commands.adapters import projects_capability_settings as settings_cli
from yoke_cli.config import aws_admin_capability as hosting


_PROJECT = "acme-app"
_ROW = {"region": "eu-west-1", "account_id": "123456789012"}


@pytest.fixture(autouse=True)
def _isolated_machine_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / ".yoke"))


def _store(*keys: str) -> None:
    for key in keys:
        hosting.store_credential(
            _PROJECT,
            access_key_id="AKIAEXAMPLE",
            secret_access_key="secret-value",
        ) if False else None
    from yoke_cli.config import capability_secrets

    for key in keys:
        capability_secrets.store_machine_capability_secret(
            _PROJECT, hosting.CAPABILITY_TYPE, key, f"value-for-{key}",
        )


# --------------------------------------------------------------------------- #
# Which half is missing
# --------------------------------------------------------------------------- #


def test_both_halves_present_is_ready_with_nothing_to_run() -> None:
    _store(*hosting.REQUIRED_CREDENTIAL_KEYS)

    report = aws.aws_admin_status_report(_PROJECT, _ROW)

    assert report["ready"] is True
    assert report["missing"] == []
    assert report["remedy"] == []
    assert report["capability_row"] == {
        "present": True, "region": "eu-west-1", "account_id": "123456789012",
    }
    assert report["machine_secrets"]["missing"] == []


def test_a_saved_pair_with_no_row_asks_only_for_the_row(monkeypatch) -> None:
    """The failure this command exists for: never re-ask for a saved secret."""
    _store(*hosting.REQUIRED_CREDENTIAL_KEYS)
    monkeypatch.setattr(hosting, "default_region", lambda: "us-east-1")

    report = aws.aws_admin_status_report(_PROJECT, None)

    assert report["ready"] is False
    assert report["missing"] == ["capability_row"]
    assert report["remedy"] == [
        "yoke projects capability-settings merge --project acme-app "
        "--cap-type aws-admin --set region=us-east-1"
    ]
    assert not any("secret set" in command for command in report["remedy"])


def test_a_row_with_no_secrets_asks_only_for_the_two_secret_keys() -> None:
    report = aws.aws_admin_status_report(_PROJECT, _ROW)

    assert report["missing"] == ["machine_secrets"]
    assert report["remedy"] == [
        "yoke projects capability secret set --project acme-app "
        "--cap-type aws-admin --key access_key_id --value-stdin",
        "yoke projects capability secret set --project acme-app "
        "--cap-type aws-admin --key secret_access_key --value-stdin",
    ]
    assert not any("capability-settings" in command for command in report["remedy"])


def test_one_stored_half_asks_only_for_the_other_one() -> None:
    _store(hosting.ACCESS_KEY_ID_KEY)

    report = aws.aws_admin_status_report(_PROJECT, _ROW)

    assert report["machine_secrets"]["present"] == [hosting.ACCESS_KEY_ID_KEY]
    assert report["machine_secrets"]["missing"] == [hosting.SECRET_ACCESS_KEY_KEY]
    assert len(report["remedy"]) == 1
    assert hosting.SECRET_ACCESS_KEY_KEY in report["remedy"][0]
    assert hosting.ACCESS_KEY_ID_KEY not in report["remedy"][0]


def test_a_row_without_a_region_is_not_a_usable_row() -> None:
    """`yoke aws exec` refuses without one, so the report must not call it ready."""
    _store(*hosting.REQUIRED_CREDENTIAL_KEYS)

    report = aws.aws_admin_status_report(_PROJECT, {})

    assert report["missing"] == ["capability_row"]
    assert report["capability_row"]["present"] is True


def test_both_halves_missing_names_both_commands() -> None:
    report = aws.aws_admin_status_report(_PROJECT, None)

    assert report["missing"] == ["capability_row", "machine_secrets"]
    assert len(report["remedy"]) == 3


def test_the_command_prints_the_report_and_exits_zero(monkeypatch, capsys) -> None:
    """Exit status reports whether the check ran, not whether AWS is ready."""
    _store(*hosting.REQUIRED_CREDENTIAL_KEYS)
    monkeypatch.setattr(aws, "_aws_admin_settings_or_none", lambda _project: None)
    monkeypatch.setattr(
        "yoke_cli.config.project_slug_lookup.resolve_project_slug",
        lambda reference, **_kwargs: _PROJECT,
    )

    code = aws.aws_admin_status(["--project", _PROJECT, "--json"])

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is False
    assert report["missing"] == ["capability_row"]


def test_the_human_form_names_the_missing_half_and_its_command(
    monkeypatch, capsys,
) -> None:
    _store(*hosting.REQUIRED_CREDENTIAL_KEYS)
    monkeypatch.setattr(aws, "_aws_admin_settings_or_none", lambda _project: None)
    monkeypatch.setattr(
        "yoke_cli.config.project_slug_lookup.resolve_project_slug",
        lambda reference, **_kwargs: _PROJECT,
    )

    assert aws.aws_admin_status(["--project", _PROJECT]) == 0

    out = capsys.readouterr().out
    assert "capability row     missing" in out
    assert "Fill only the missing half:" in out
    assert "capability-settings merge" in out
    assert "capability secret set" not in out


# --------------------------------------------------------------------------- #
# The flag pair that does not exist on this surface
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "adapter",
    [
        settings_cli.projects_capability_settings_get,
        settings_cli.projects_capability_settings_set,
    ],
)
def test_scalar_key_value_is_refused_with_the_real_shapes(adapter, capsys) -> None:
    code = adapter([
        "--project", _PROJECT, "--cap-type", "aws-admin",
        "--key", "region", "--value", "us-east-1",
    ])

    assert code == 2
    message = json.loads(capsys.readouterr().err)["message"]
    assert "capability-settings merge" in message
    assert "--set key.path=value" in message
    assert "capability secret set" in message


def test_a_settings_read_without_the_bad_flags_still_dispatches(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        settings_cli,
        "dispatch_and_emit",
        lambda **kwargs: seen.append(kwargs["function_id"]) or 0,
    )

    assert settings_cli.projects_capability_settings_get(
        ["--project", _PROJECT, "--cap-type", "aws-admin"]
    ) == 0
    assert seen == ["projects.capability_settings.get"]

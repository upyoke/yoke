"""Apply registers the ``aws-admin`` capability row, not only the secret files.

The wizard's AWS step reported the credential saved after writing the pair to
this machine, while the connected universe gained no capability row at all.
`/yoke onboard` then read `has=false` and told the operator to re-enter two
secrets that were already on disk. These cover the half that was missing: Apply
writes the row from the same inputs the verified screen showed, converges on a
second run, and stays out of the way when there is nothing to declare.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from yoke_cli.config import aws_admin_capability as hosting
from yoke_cli.config import onboard_apply_aws_admin_capability as apply_capability
from yoke_contracts import hosting_posture


_PROJECT = "acme-app"


@pytest.fixture(autouse=True)
def _isolated_machine_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / ".yoke"))


def _store_pair(project: str = _PROJECT) -> None:
    hosting.store_credential(
        project, access_key_id="AKIAEXAMPLE", secret_access_key="secret-value",
    )


def _ok_response():
    class _Response:
        success = True
        error = None
        result: dict[str, Any] = {}

    return _Response()


def _record_calls(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        apply_capability,
        "call_dispatcher",
        lambda **kwargs: calls.append(kwargs) or _ok_response(),
    )
    return calls


def test_apply_registers_the_row_with_the_verified_region_and_account(
    monkeypatch,
) -> None:
    _store_pair()
    calls = _record_calls(monkeypatch)

    result = apply_capability.record(
        project=_PROJECT,
        posture=hosting_posture.POSTURE_YOKE_MANAGED_AWS,
        verification={
            "checked": True,
            "ok": True,
            "account": "123456789012",
            "identity": "user/yoke-aws-admin",
            "region": "eu-west-1",
        },
    )

    assert len(calls) == 1
    assert calls[0]["function_id"] == "projects.capability_settings.merge"
    payload = calls[0]["payload"]
    assert payload["project"] == _PROJECT
    assert payload["cap_type"] == hosting.CAPABILITY_TYPE
    assert payload["assignments"] == {
        "region": "eu-west-1",
        "account_id": "123456789012",
    }
    assert result is not None
    assert result["settings"] == payload["assignments"]


def test_a_second_wizard_run_converges_instead_of_conflicting(monkeypatch) -> None:
    """The settings merge creates an absent row and CAS-updates a present one."""
    _store_pair()
    calls = _record_calls(monkeypatch)
    verification = {"account": "123456789012", "region": "eu-west-1"}

    for _ in range(2):
        apply_capability.record(
            project=_PROJECT,
            posture=hosting_posture.POSTURE_YOKE_MANAGED_AWS,
            verification=verification,
        )

    assert calls[0]["payload"] == calls[1]["payload"]


def test_an_unverified_pair_records_the_region_without_inventing_an_account(
    monkeypatch,
) -> None:
    _store_pair()
    calls = _record_calls(monkeypatch)
    monkeypatch.setattr(hosting, "default_region", lambda: "us-east-1")

    apply_capability.record(
        project=_PROJECT,
        posture=hosting_posture.POSTURE_YOKE_MANAGED_AWS,
        verification=None,
    )

    assert calls[0]["payload"]["assignments"] == {"region": "us-east-1"}


def test_a_non_aws_posture_declares_no_aws_capability(monkeypatch) -> None:
    _store_pair()
    calls = _record_calls(monkeypatch)

    for posture in (
        hosting_posture.POSTURE_NO_YOKE_MANAGED_HOST,
        hosting_posture.POSTURE_UNDECIDED,
    ):
        assert apply_capability.record(project=_PROJECT, posture=posture) is None
    assert calls == []


def test_no_credential_on_this_machine_declares_nothing(monkeypatch) -> None:
    """A row whose credential no deploy could read is not a fact worth writing."""
    calls = _record_calls(monkeypatch)

    assert apply_capability.record(
        project=_PROJECT,
        posture=hosting_posture.POSTURE_YOKE_MANAGED_AWS,
        verification={"region": "eu-west-1"},
    ) is None
    assert calls == []


def test_the_wizard_passes_the_verification_through_apply() -> None:
    """The region the probe used has to survive into `build_report`."""
    from yoke_cli.config import onboard_wizard

    result = onboard_wizard.WizardResult(
        config_path="", env_name="prod", api_url="",
    )
    result.hosting_choice = hosting_posture.POSTURE_YOKE_MANAGED_AWS
    result.hosting_verification = {"account": "1", "region": "eu-west-1"}

    kwargs = result.build_report_kwargs(apply=True, check_identity=False)

    assert kwargs["hosting_verification"] == {"account": "1", "region": "eu-west-1"}

"""The destination picker carries the hosted environment choice.

Picking a home used to take two screens: a destination, then a separate
"which hosted environment" question whose only row was production. The
environment now rides the picker row, so `upyoke.com` and `stage.upyoke.com`
are two rows of one question and the browser connect leg opens whichever
platform the row named.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters.onboard_destination_args import resolve_destination
from yoke_cli.config import hosted_machine_authorization
from yoke_contracts.api_urls import (
    HOSTED_PLATFORM_URL,
    HOSTED_PROD_API_URL,
    HOSTED_STAGE_API_URL,
    HOSTED_STAGE_PLATFORM_URL,
)

from yoke_cli.config.onboard_destinations import (
    DESTINATION_HOSTED,
    DESTINATION_LOCAL,
    DESTINATION_SERVER,
    ENV_PRODUCTION,
    ENV_STAGE,
)
from yoke_cli.config.onboard_destination_rows import (
    DESTINATION_ROWS,
    HOSTED_ROW_ENVS,
    HOSTED_STAGE_ROW,
)
from yoke_cli.config.onboard_wizard_flow_hosted_machine import platform_url_for_env
from yoke_cli.config.onboard_wizard_flow_hosted_machine import (
    HostedMachineConnectFlow,
    platform_url_for_connection,
)


def _destination_args(connect_url: str, env_name: str | None = None):
    return SimpleNamespace(
        destination_local=False,
        connect_url=connect_url,
        destination=None,
        api_url=None,
        env_name=env_name,
        token=None,
        token_file=None,
        token_stdin=False,
    )


def test_picker_offers_both_hosted_platforms_as_rows() -> None:
    values = [row.value for row in DESTINATION_ROWS]
    assert values == [
        DESTINATION_LOCAL,
        DESTINATION_SERVER,
        DESTINATION_HOSTED,
        HOSTED_STAGE_ROW,
    ]


def test_hosted_rows_name_the_platform_they_connect_to() -> None:
    labels = {row.value: row.label for row in DESTINATION_ROWS}
    assert labels[DESTINATION_HOSTED] == "upyoke.com"
    assert labels[HOSTED_STAGE_ROW] == "stage.upyoke.com"


def test_each_hosted_row_selects_its_environment() -> None:
    assert HOSTED_ROW_ENVS[DESTINATION_HOSTED] == ENV_PRODUCTION
    assert HOSTED_ROW_ENVS[HOSTED_STAGE_ROW] == ENV_STAGE


def test_connect_leg_opens_the_platform_the_row_named() -> None:
    assert platform_url_for_env(ENV_PRODUCTION) == HOSTED_PLATFORM_URL
    assert platform_url_for_env(ENV_STAGE) == HOSTED_STAGE_PLATFORM_URL


def test_an_unset_environment_connects_to_production() -> None:
    # A resumed run that never recorded an environment must not silently
    # send a founder at staging.
    assert platform_url_for_env(None) == HOSTED_PLATFORM_URL
    assert platform_url_for_env("") == HOSTED_PLATFORM_URL


@pytest.mark.parametrize(
    ("connect_url", "expected_env"),
    (
        (HOSTED_PLATFORM_URL, ENV_PRODUCTION),
        (HOSTED_PROD_API_URL, ENV_PRODUCTION),
        (HOSTED_STAGE_PLATFORM_URL, ENV_STAGE),
        (HOSTED_STAGE_API_URL, ENV_STAGE),
    ),
)
def test_explicit_hosted_url_selects_its_environment(
    connect_url: str,
    expected_env: str,
) -> None:
    choice = resolve_destination(_destination_args(connect_url))

    assert choice.error is None
    assert choice.destination == DESTINATION_HOSTED
    assert choice.env_name == expected_env


def test_explicit_hosted_url_rejects_a_different_environment() -> None:
    choice = resolve_destination(
        _destination_args(HOSTED_STAGE_PLATFORM_URL, ENV_PRODUCTION)
    )

    assert choice.error == (
        "hosted URL selects 'stage', but --env selects 'prod'; "
        "use matching values"
    )


def test_resumed_hosted_connection_preserves_its_org_label() -> None:
    choice = resolve_destination(
        _destination_args(HOSTED_STAGE_API_URL, "upyoke-stage-1")
    )

    assert choice.error is None
    assert choice.env_name == "upyoke-stage-1"
    assert (
        platform_url_for_connection(HOSTED_STAGE_API_URL, choice.env_name)
        == HOSTED_STAGE_PLATFORM_URL
    )


def test_browser_authorization_uses_the_explicit_hosted_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        hosted_machine_authorization,
        "start",
        lambda platform_url: opened.append(platform_url),
    )

    class Probe(HostedMachineConnectFlow):
        result = SimpleNamespace(
            api_url=HOSTED_STAGE_PLATFORM_URL,
            env_name="",
        )
        _hosted_machine_denial_retry_used = False

        def _run_checking(self, **kwargs) -> None:
            kwargs["work"]()

    Probe()._start_hosted_machine_authorization()

    assert opened == [HOSTED_STAGE_PLATFORM_URL]
    assert (
        platform_url_for_connection(HOSTED_STAGE_API_URL, "")
        == HOSTED_STAGE_PLATFORM_URL
    )


def test_the_separate_environment_screen_is_retired() -> None:
    from yoke_cli.config import onboard_wizard_flow_hosted_machine as flow

    assert not hasattr(flow, "ENV_SELECT_ROWS")
    assert not hasattr(flow.HostedMachineConnectFlow, "_goto_hosted_env_select")

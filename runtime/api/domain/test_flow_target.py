"""A flow's declared deploy target resolves in exactly one place."""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain.flow_target import resolve_flow_target


class _Conn:
    pass


def _resolve(target_tier, environment, *, env_id=7):
    with mock.patch(
        "yoke_core.domain.flow_target.resolve_project",
        return_value=mock.Mock(id=3, slug="acme"),
    ), mock.patch(
        "yoke_core.domain.environment_reference.resolve",
        return_value=mock.Mock(id=env_id),
    ):
        return resolve_flow_target(
            _Conn(),
            project="acme",
            target_tier=target_tier,
            environment=environment,
        )


def test_merge_only_flow_names_no_environment() -> None:
    assert _resolve(None, None) is None


def test_ephemeral_flow_names_no_environment() -> None:
    assert _resolve("ephemeral", None) is None


def test_persistent_flow_resolves_its_registered_environment() -> None:
    assert _resolve("persistent", "prod") == 7


@pytest.mark.parametrize(
    "target_tier, environment",
    [
        ("persistent", None),
        ("ephemeral", "prod"),
        (None, "prod"),
    ],
)
def test_tier_and_environment_must_agree(target_tier, environment) -> None:
    with pytest.raises(ValueError, match="environment is required exactly when"):
        _resolve(target_tier, environment)


def test_unknown_tier_is_refused() -> None:
    with pytest.raises(ValueError, match="target_tier must be one of"):
        _resolve("preview", None)

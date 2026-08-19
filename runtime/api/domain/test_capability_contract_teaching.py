"""Capability-contract failure hints name configure and remove."""

from __future__ import annotations

from yoke_core.domain.deploy_environment_settings import _CAPABILITY_HINT


def test_deploy_capability_hint_names_configure_and_remove() -> None:
    hint = _CAPABILITY_HINT.format(project="demo", capability="ephemeral-env")
    assert "capability-merge-settings demo ephemeral-env" in hint
    assert (
        "yoke projects capability-settings remove --project demo "
        "--cap-type ephemeral-env --base <as-read>"
    ) in hint

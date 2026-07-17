"""Scalar environment-settings projection through array entries."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.handlers.projects_environment_settings import (
    _project_scalar_paths,
)
from yoke_core.domain.settings_cas import apply_key_path_assignments


def test_projection_reads_only_named_array_scalar() -> None:
    settings = json.dumps({
        "servers": [
            {"instance_type": "t4g.micro", "ssh_user": "ubuntu"},
            {"instance_type": "t4g.small", "ssh_user": "admin"},
        ]
    })

    assert _project_scalar_paths(
        settings, ["servers.1.instance_type"]
    ) == {"servers.1.instance_type": "t4g.small"}


def test_projection_refuses_array_container_or_non_numeric_index() -> None:
    settings = '{"servers":[{"instance_type":"t4g.micro"}]}'

    with pytest.raises(ValueError, match="selects a container"):
        _project_scalar_paths(settings, ["servers.0"])
    with pytest.raises(ValueError, match="array index"):
        _project_scalar_paths(settings, ["servers.first.instance_type"])


def test_assignment_updates_one_array_entry_without_replacing_siblings() -> None:
    settings = {
        "servers": [
            {"instance_type": "t4g.micro", "ssh_user": "ubuntu"},
            {"instance_type": "t4g.small", "ssh_user": "admin"},
        ]
    }

    updated = apply_key_path_assignments(
        settings, {"servers.0.instance_type": "t4g.medium"}
    )

    assert updated["servers"][0] == {
        "instance_type": "t4g.medium", "ssh_user": "ubuntu"
    }
    assert updated["servers"][1]["instance_type"] == "t4g.small"
    assert settings["servers"][0]["instance_type"] == "t4g.micro"

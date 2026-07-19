"""Exact-stack Pulumi rendering for deployment-specific consumers."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.test_project_renderer_pulumi_instances import (
    _environment_settings,
    _make_project_tree,
    _settings_with_environments,
)
from yoke_core.domain.project_renderer_pulumi import (
    gather_pulumi_values,
    render_pulumi_artifacts,
)


def _render(root, output, settings, pulumi_stack) -> None:
    values = gather_pulumi_values(
        "platform", root, settings, pulumi_stack=pulumi_stack
    )
    render_pulumi_artifacts(
        "platform",
        values,
        root,
        output,
        True,
        settings,
        pulumi_stack=pulumi_stack,
    )


def _runner_fleet_project(tmp_path: Path):
    root, output = _make_project_tree(tmp_path, "platform")
    infra = root / "infra"
    (infra / "webapp_distribution_stack.py").write_text("# distribution\n")
    (infra / "webapp_runner_fleet_stack.py").write_text("# runners\n")
    (infra / "webapp_runner_github_api.mjs").write_text("// runners\n")
    settings = _settings_with_environments(
        "platform",
        ["runner-fleet"],
        [
            _environment_settings("yoke-prod", "prod"),
            _environment_settings("yoke-stage", "stage"),
        ],
    )
    return root, output, settings


def test_selected_environment_skips_unrelated_runner_fleet_requirements(
    tmp_path: Path,
) -> None:
    root, output, settings = _runner_fleet_project(tmp_path)

    _render(root, output, settings, "yoke-stage")

    names = {path.name for path in (output / "infra").iterdir()}
    assert "Pulumi.yaml" in names
    assert "Pulumi.yoke-stage.yaml" in names
    assert "Pulumi.yoke-prod.yaml" not in names
    assert "Pulumi.platform-runner-fleet.yaml" not in names
    assert "webapp_environment_stack.py" in names
    assert "webapp_distribution_stack.py" in names
    assert "webapp_distribution_github_variables.py" in names
    assert "webapp_runner_fleet_stack.py" not in names
    assert "webapp_runner_github_api.mjs" not in names


@pytest.mark.parametrize("pulumi_stack", [None, "platform-runner-fleet"])
def test_full_or_runner_fleet_render_keeps_binding_validation(
    tmp_path: Path, pulumi_stack: str | None,
) -> None:
    root, output, settings = _runner_fleet_project(tmp_path)

    with pytest.raises(
        ValueError, match="requires explicit github_capability",
    ):
        _render(root, output, settings, pulumi_stack)


def test_unknown_stack_selector_fails_without_partial_render(tmp_path: Path) -> None:
    root, output, settings = _runner_fleet_project(tmp_path)

    with pytest.raises(ValueError, match="is not declared"):
        _render(root, output, settings, "missing-stack")

    assert not (output / "infra" / "Pulumi.yaml").exists()


def test_ambiguous_stack_selector_fails_closed(tmp_path: Path) -> None:
    root, output = _make_project_tree(tmp_path, "platform")
    settings = _settings_with_environments(
        "platform",
        ["infra"],
        [_environment_settings("platform-infra", "prod")],
    )

    with pytest.raises(ValueError, match="matches multiple declarations"):
        _render(root, output, settings, "platform-infra")

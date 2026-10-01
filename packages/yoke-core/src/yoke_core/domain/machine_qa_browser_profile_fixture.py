"""Explicit installed-product restoration for browser-authenticated QA."""

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from yoke_contracts.machine_config.capability_secrets import (
    browser_profile_relative_path,
    safe_secret_component,
)
from yoke_contracts.machine_config.schema import SECRETS_DIR_NAME
from yoke_contracts.machine_config.test_machine import validate_golden_baseline_path
from yoke_core.domain.machine_qa_fixture_validation_common import (
    bounded_text,
    exact_keys,
    operation_error,
)


OPERATION_ID = "machine.browser-profile-restore"


def validate_browser_profile_restore(parameters: Mapping[str, Any]) -> dict[str, str]:
    exact_keys(OPERATION_ID, parameters, {"project", "baseline_path"})
    project = bounded_text(OPERATION_ID, parameters, "project", max_length=80)
    if project != safe_secret_component(project, "project"):
        raise operation_error(OPERATION_ID, "project must be a canonical safe slug")
    try:
        baseline = validate_golden_baseline_path(parameters.get("baseline_path"))
    except ValueError:
        raise operation_error(
            OPERATION_ID, "baseline_path must name a sealed absolute snapshot"
        ) from None
    return {"project": project, "baseline_path": baseline}


class MachineQaBrowserProfileFixture:
    def _browser_profile_restore(self, parameters: Mapping[str, Any]) -> None:
        project = parameters["project"]
        relative = str(
            PurePosixPath(".yoke")
            / SECRETS_DIR_NAME
            / browser_profile_relative_path(project)
        )
        self._run(
            self._installed_yoke_python(
                "-m",
                "yoke_harness.browser_profile_archive",
                "restore",
                self.home,
                parameters["baseline_path"],
                project,
                relative,
            ),
            timeout=300,
        )

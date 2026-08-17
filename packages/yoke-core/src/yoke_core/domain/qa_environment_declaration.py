"""Per-project QA-environment declaration (capability + uv flag lists).

Settings live on ``project_capabilities.type='test_environment'``. Test
trees stay on Project Structure ``test_roots`` — this module does not
invent a second roots list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from yoke_contracts.project_defaults import default_project_for_directory
from yoke_contracts.uv_project import UV_EXECUTABLE, is_uv_project, uv_run_argv

CAPABILITY_TYPE = "test_environment"
SETTING_UV_PROJECT = "uv_project"
SETTING_UV_EXTRAS = "uv_extras"
SETTING_UV_GROUPS = "uv_groups"
SANCTIONED_RUN_SURFACE = "yoke watch pytest --"


@dataclass(frozen=True)
class TestEnvironmentDeclaration:
    """Resolved sync/run selection for one project checkout."""

    __test__ = False

    project: str
    uv_project: str = ""
    extras: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()

    def selection_flags(self) -> list[str]:
        flags: list[str] = []
        for extra in self.extras:
            flags.extend(["--extra", extra])
        for group in self.groups:
            flags.extend(["--group", group])
        return flags

    def sync_argv(self) -> list[str]:
        return [UV_EXECUTABLE, "sync", "--frozen", *self.selection_flags()]

    def run_python_argv(
        self,
        trailing: Sequence[str],
        *,
        cwd: Path | None = None,
    ) -> list[str]:
        """``uv run --frozen`` plus declared extras/groups and optional ``--project``."""
        if not self.selection_flags() and not self._project_flag(cwd):
            return uv_run_argv(list(trailing))
        argv = [UV_EXECUTABLE, "run", "--frozen", *self._project_flag(cwd)]
        argv.extend(self.selection_flags())
        argv.extend(["python3", *trailing])
        return argv

    def _project_flag(self, cwd: Path | None) -> list[str]:
        if not self.uv_project:
            return []
        here = (cwd or Path.cwd()).resolve()
        if is_uv_project(here / self.uv_project):
            return ["--project", self.uv_project]
        return []

    def capability_get_recipe(self) -> str:
        return (
            f"yoke projects capability-settings get --project {self.project} "
            f"--cap-type {CAPABILITY_TYPE}"
        )


def parse_declaration(
    project: str,
    settings: Mapping[str, Any] | None,
) -> TestEnvironmentDeclaration:
    raw = settings or {}
    return TestEnvironmentDeclaration(
        project=project,
        uv_project=_scalar(raw, SETTING_UV_PROJECT),
        extras=_csv(raw, SETTING_UV_EXTRAS),
        groups=_csv(raw, SETTING_UV_GROUPS),
    )


def load_declaration(
    project: str | None = None,
    *,
    checkout: Path | None = None,
) -> TestEnvironmentDeclaration:
    """Read the capability over the connected control plane.

    A missing capability (or a relay failure) is the default: empty
    extras/groups and nested uv-project discovery.
    """
    slug = project or default_project_for_directory(checkout or Path.cwd())
    return parse_declaration(slug, _read_settings(slug))


def resolve_uv_projects(
    worktree_path: Path,
    declaration: TestEnvironmentDeclaration,
    *,
    discover,
) -> list[Path] | str:
    """Return uv project dirs, or a blocking error string."""
    if not declaration.uv_project:
        return list(discover(worktree_path))
    target = (worktree_path / declaration.uv_project).resolve()
    if not is_uv_project(target):
        return (
            f"Declared {CAPABILITY_TYPE}.{SETTING_UV_PROJECT} "
            f"{declaration.uv_project!r} is not a uv-managed project at "
            f"{target}. {declaration.capability_get_recipe()}"
        )
    return [target]


def _read_settings(project: str) -> dict[str, Any]:
    import json

    from yoke_core.domain.control_plane_transport import relay

    try:
        result = relay(
            "projects.capability_settings.get",
            {"project": project, "cap_type": CAPABILITY_TYPE},
        )
    except Exception:  # noqa: BLE001 — missing cap or relay failure is default
        return {}
    raw = result.get("settings_json")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _scalar(settings: Mapping[str, Any], key: str) -> str:
    value = settings.get(key, "")
    return str(value).strip() if value is not None else ""


def _csv(settings: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = _scalar(settings, key)
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


__all__ = [
    "CAPABILITY_TYPE",
    "SANCTIONED_RUN_SURFACE",
    "SETTING_UV_EXTRAS",
    "SETTING_UV_GROUPS",
    "SETTING_UV_PROJECT",
    "TestEnvironmentDeclaration",
    "load_declaration",
    "parse_declaration",
    "resolve_uv_projects",
]

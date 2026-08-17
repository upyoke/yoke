"""Import-graph proof for the project's installed-hook health check."""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor_project_checks import load_check_module


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_CHECK = load_check_module(
    REPO_ROOT / ".yoke" / "doctor",
    "check_packaged_hook_boundaries",
)


def test_packaged_modules_do_not_import_source_hook_namespace() -> None:
    assert HOOK_CHECK.scan_source_namespace_edges(REPO_ROOT) == []


def test_hook_registries_name_only_packaged_modules() -> None:
    findings = HOOK_CHECK.scan_source_namespace_edges(REPO_ROOT)
    assert findings == []


def test_local_engine_import_cannot_fail_open_silently() -> None:
    assert HOOK_CHECK.scan_local_engine_fail_loud(REPO_ROOT) == []

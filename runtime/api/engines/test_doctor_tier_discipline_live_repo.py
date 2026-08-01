"""Live-repository regressions for tier-discipline health checks."""

from __future__ import annotations

import os
from pathlib import Path

from yoke_project_checks import check_packet_tier_completeness as packet_mod
from yoke_project_checks import (
    check_progressive_disclosure_direction as disclosure_mod,
)
from yoke_project_checks import check_tier_cli_shape_bleed as cli_mod
from yoke_project_checks import check_tier_module_path_resolution as module_path_mod
from yoke_project_checks import check_tier_schema_bleed as schema_mod


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_live_schema_teaching_does_not_misclassify_function_surfaces() -> None:
    findings = schema_mod._scan_all(REPO_ROOT)
    detail = "\n".join(findings)
    for function_surface in (
        "items.structured_field",
        "items.section",
        "items.progress_log",
        "items.scalar",
        "project_structure.patch",
        "epic_tasks.list",
    ):
        assert function_surface not in detail


def test_live_cli_teaching_uses_supported_shapes(monkeypatch) -> None:
    source_roots = [
        str(REPO_ROOT / "packages" / package / "src")
        for package in (
            "yoke-core",
            "yoke-cli",
            "yoke-contracts",
            "yoke-harness",
        )
    ]
    inherited = os.environ.get("PYTHONPATH")
    if inherited:
        source_roots.append(inherited)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(source_roots))

    findings = cli_mod._scan_all(REPO_ROOT)
    assert not findings, "\n".join(findings)


def test_live_role_packets_cover_skill_references() -> None:
    findings: list[str] = []
    for role in sorted(packet_mod.ROLE_TOPICS):
        packet_mod._check_a_for_role(role, REPO_ROOT, findings)
    packet_mod._check_b_envelope(findings)
    assert not findings, "\n".join(findings)


def test_live_teaching_references_are_classified_without_strategy_cache(
    monkeypatch,
) -> None:
    strategy_root = REPO_ROOT / ".yoke/strategy"
    original_is_file = Path.is_file

    def is_file_without_strategy_cache(path: Path) -> bool:
        if path.is_relative_to(strategy_root):
            return False
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", is_file_without_strategy_cache)
    findings = disclosure_mod._scan_all(REPO_ROOT)
    detail = "\n".join(findings)
    assert "is not classified into a teaching tier" not in detail, detail


def test_live_python_module_references_resolve() -> None:
    findings = module_path_mod._scan_all(REPO_ROOT)
    assert not findings, "\n".join(findings)

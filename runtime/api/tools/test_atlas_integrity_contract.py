"""Always-run floor: live Atlas integrity, not doc-render currency.

Keeps Atlas integrity on the impacted-selection contract floor so a lane
that bypasses hooks still fails locally instead of only in CI. Field-note
collection is stubbed — that section is normalised out of staleness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.tools import atlas_integrity_audit as audit_mod
from yoke_core.tools import atlas_render_docs as ard_mod
from yoke_core.tools import ci_repo_contracts as crc
from yoke_core.tools._impacted_ci_only_contract_floor import (
    CI_ONLY_CONTRACT_FLOOR_TESTS,
)
from yoke_core.tools._impacted_generated_artifact_parity import (
    GENERATED_ARTIFACT_PARITY_TESTS,
)
from yoke_core.tools.impacted_tests import ALWAYS_RUN_TESTS

_EMPTY_SCOPE = crc.ChangedPathScope(base_sha="unused", paths=())


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "docs" / "atlas.md").is_file():
            return parent
    raise RuntimeError("could not locate repo root with docs/atlas.md")


def _patch_atlas_audit(
    monkeypatch: pytest.MonkeyPatch, *, report: dict, stale: bool,
) -> None:
    monkeypatch.setattr(audit_mod, "build_report", lambda _root: report)
    monkeypatch.setattr(ard_mod, "render", lambda _report: "body")
    monkeypatch.setattr(ard_mod, "is_stale", lambda _root, *, body: stale)


def test_atlas_contract_has_no_currency_alias() -> None:
    assert not hasattr(crc, "check_atlas_currency")
    assert "atlas-currency" not in [name for name, _ in crc.CONTRACTS]


def test_atlas_integrity_fails_on_taught_command_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_atlas_audit(
        monkeypatch,
        report={
            "taught_commands": {
                "surfaces": [
                    {
                        "kind": "yoke",
                        "recipe": "yoke relay diagnostic",
                        "source": ".agents/skills/yoke/relay/SKILL.md",
                        "line_number": 12,
                        "drift_type": "taught_yoke_command_unresolved",
                    }
                ],
            },
        },
        stale=False,
    )
    ok, detail = crc.check_atlas_integrity(tmp_path, _EMPTY_SCOPE)
    assert ok is False
    assert "yoke relay diagnostic" in detail
    assert "taught_yoke_command_unresolved" in detail
    assert "SKILL.md:12" in detail


def test_atlas_integrity_ignores_internal_module_inventory_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_atlas_audit(
        monkeypatch,
        report={
            "taught_commands": {
                "surfaces": [
                    {
                        "kind": "python_module",
                        "recipe": "python3 -m yoke_core.tools.install_yoke_launcher",
                        "source": "AGENTS.md",
                        "line_number": 100,
                        "drift_type": "taught_internal_module_unsanctioned",
                    }
                ],
            },
        },
        stale=False,
    )
    ok, detail = crc.check_atlas_integrity(tmp_path, _EMPTY_SCOPE)
    assert ok is True
    assert "no drift findings" in detail


def test_atlas_integrity_fails_on_stale_doc_without_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_atlas_audit(
        monkeypatch,
        report={"taught_commands": {"surfaces": []}},
        stale=True,
    )
    ok, detail = crc.check_atlas_integrity(tmp_path, _EMPTY_SCOPE)
    assert ok is False
    assert "docs/atlas.md is stale" in detail


def test_atlas_integrity_passes_when_current_and_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_atlas_audit(
        monkeypatch,
        report={
            "taught_commands": {
                "surfaces": [{"recipe": "yoke items get", "drift_type": None}],
            },
        },
        stale=False,
    )
    ok, detail = crc.check_atlas_integrity(tmp_path, _EMPTY_SCOPE)
    assert ok is True
    assert "no drift findings" in detail


def test_live_repo_atlas_integrity(monkeypatch) -> None:
    monkeypatch.setattr(
        audit_mod,
        "collect_field_notes",
        lambda: {
            "count": 0,
            "rows": [],
            "read_surface_status": "agent_facing",
        },
    )
    root = _repo_root()
    ok, detail = crc.check_atlas_integrity(root, _EMPTY_SCOPE)
    assert ok, detail


def test_generated_artifact_parity_is_on_the_always_run_floor() -> None:
    assert set(GENERATED_ARTIFACT_PARITY_TESTS) <= set(ALWAYS_RUN_TESTS)


def test_atlas_integrity_contract_is_on_the_ci_only_floor() -> None:
    assert (
        "runtime/api/tools/test_atlas_integrity_contract.py"
        in CI_ONLY_CONTRACT_FLOOR_TESTS
    )

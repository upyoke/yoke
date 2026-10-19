"""The workbench's harness-name module is generated from the registry."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS, harness_display_name
from yoke_core.ui import harness_names_module
from yoke_core.ui.harness_names_module import MODULE_REL, has_drift, render_module


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_checked_in_module_matches_the_registry():
    assert not has_drift(target_root=REPO_ROOT), (
        f"Repair: {harness_names_module.SYNC_COMMAND}"
    )


def test_module_names_every_harness_in_registry_order():
    names = [harness_display_name(harness_id) for harness_id in CANONICAL_HARNESS_IDS]
    assert f"export const HARNESS_NAMES = {json.dumps(names)};" in render_module()


def test_check_refuses_drift_and_names_the_repair(tmp_path, capsys):
    target = tmp_path / MODULE_REL
    target.parent.mkdir(parents=True)
    target.write_text("export const HARNESS_NAMES = [];\n", encoding="utf-8")
    assert harness_names_module.run_cli(["check", "--target-root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "drifted from the harness registry" in output
    assert harness_names_module.SYNC_COMMAND in output

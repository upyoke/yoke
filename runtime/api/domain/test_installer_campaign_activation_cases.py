"""Exploration exports the core mission through the QA contract."""

import json
from pathlib import Path

import pytest

from yoke_core.domain import pack_catalog
from yoke_core.domain.qa_method_config_validation import validate_method_config
from yoke_core.tools.installer_campaign_plan import compare_plan


ROOT = Path(__file__).resolve().parents[3]


def test_exploration_export_and_readback_use_core_cases(monkeypatch):
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)
    plan = {
        "id": 42,
        "slug": "installer-exploration",
        "target_environment": "test",
        "cases": [],
    }
    cases, report = compare_plan(plan)
    assert report["differences"] == [
        {"case_key": "installer-exploration", "change": "added"}
    ]
    assert cases == json.loads(
        (
            ROOT
            / "packages/yoke-core/src/yoke_core/domain/installer_exploration_cases.json"
        ).read_text()
    )
    for case in cases:
        assert validate_method_config("agent-mission", case["method_config"])
    plan["cases"] = cases
    assert compare_plan(plan)[1]["matches_source"]
    plan["cases"][0]["instructions"] = "stale"
    assert not compare_plan(plan)[1]["matches_source"]


def test_export_rejects_an_unrelated_plan():
    with pytest.raises(ValueError, match="unsupported installer plan"):
        compare_plan({"slug": "unrelated"})

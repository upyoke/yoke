"""Lineage contract for the latest Smoke Testing Pack."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import pack_catalog


ROOT = Path(__file__).resolve().parents[3]
SMOKE_WORKFLOW = (
    "packs/smoke-testing/versions/1.1.0/files"
    "/.github/workflows/{{project_name}}-smoke.yml"
)
_SHA_PATTERN = re.compile(r"\^\[0-9a-f\]\{40\}\$")
_UNSAFE_INPUT_INTERPOLATION = re.compile(
    r"""["']\$\{\{\s*inputs\.commit_sha\s*\}\}["']"""
)
_RENDER_VALUES = {
    "PROJECT_NAME_UPPER": "SAMPLE",
    "api_port": "8000",
    "project_display_name": "Sample App",
    "project_name": "sample",
    "web_port": "3000",
    "web_smoke_paths": "/login",
}


def _latest_workflow() -> str:
    return (ROOT / SMOKE_WORKFLOW).read_text(encoding="utf-8")


def _commit_sha_input(text: str) -> str:
    start = text.index("      commit_sha:")
    jobs = text.index("\njobs:", start)
    return text[start:jobs]


def test_latest_smoke_pack_publishes_required_lineage_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)
    descriptor = pack_catalog.load_pack_descriptor("smoke-testing")
    assert descriptor["latest_version"] == "1.1.0"
    assert set(descriptor["versions"]) >= {"1.0.0", "1.0.1", "1.1.0"}
    assert descriptor["versions"]["1.1.0"]["source"] == "versions/1.1.0/files"


def test_latest_smoke_workflow_rejects_optional_or_conditional_lineage() -> None:
    text = _latest_workflow()
    commit_sha = _commit_sha_input(text)
    assert "        required: true" in commit_sha
    assert "        required: false" not in commit_sha
    assert "default:" not in commit_sha
    assert "if: inputs.commit_sha" not in text
    assert "Verify deployed version" in text


def test_latest_smoke_workflow_passes_commit_sha_through_env() -> None:
    text = _latest_workflow()
    assert "EXPECTED_COMMIT_SHA: ${{ inputs.commit_sha }}" in text
    assert _UNSAFE_INPUT_INTERPOLATION.search(text) is None


def test_latest_smoke_workflow_rejects_malformed_sha_and_absent_marker() -> None:
    text = _latest_workflow()
    match = _SHA_PATTERN.search(text)
    assert match is not None
    pattern = re.compile(match.group(0))
    assert pattern.search("a" * 40)
    assert pattern.search("0123456789abcdef0123456789abcdef01234567")
    assert pattern.search("ABC") is None
    assert pattern.search("A" * 40) is None
    assert pattern.search("a" * 39) is None
    assert pattern.search("") is None
    assert "Deployed version marker is absent" in text
    assert "|| echo \"none\"" not in text


def test_latest_smoke_workflow_keeps_dispatch_correlation_and_settings() -> None:
    text = _latest_workflow()
    assert "      yoke_dispatch_id:" in text
    assert "[yoke-dispatch:${{ inputs.yoke_dispatch_id }}]" in text
    assert "{{PROJECT_NAME_UPPER}}" in text
    assert "{{project_display_name}}" in text
    assert "{{project_name}}" in text
    assert "{{api_port}}" in text
    assert "{{web_port}}" in text
    assert "{{web_smoke_paths}}" in text


def test_latest_smoke_pack_matches_install_bundle_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=9, slug="sample"),
    )
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)
    canonical = pack_catalog.build_pack_bundle(
        object(),
        project="sample",
        pack="smoke-testing",
        render_values=_RENDER_VALUES,
    )
    packaged_root = ROOT / "packages/yoke-core/src/yoke_core/install_bundle_tree"
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: packaged_root)
    packaged = pack_catalog.build_pack_bundle(
        object(),
        project="sample",
        pack="smoke-testing",
        render_values=_RENDER_VALUES,
    )

    assert canonical["version"] == "1.1.0"
    assert canonical["content_digest"] == packaged["content_digest"]
    assert canonical["files"] == packaged["files"]

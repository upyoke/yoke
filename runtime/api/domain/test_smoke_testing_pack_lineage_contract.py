"""Lineage contract for the latest Smoke Testing Pack."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import json_helper, pack_catalog


ROOT = Path(__file__).resolve().parents[3]

#: The version that introduced deployed-lineage verification. Every later
#: version inherits the contract below, so the floor is what is pinned and
#: the assertions follow whichever version is currently published as latest.
LINEAGE_FLOOR = "1.1.0"
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


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _latest_version() -> str:
    """Read the published latest version straight from the pack manifest."""
    return json_helper.loads_text(
        (ROOT / "packs/smoke-testing/pack.json").read_text(encoding="utf-8")
    )["latest_version"]


def _latest_workflow() -> str:
    workflow = (
        ROOT / "packs/smoke-testing/versions" / _latest_version()
        / "files/.github/workflows/{{project_name}}-smoke.yml"
    )
    return workflow.read_text(encoding="utf-8")


def _commit_sha_input(text: str) -> str:
    start = text.index("      commit_sha:")
    jobs = text.index("\njobs:", start)
    return text[start:jobs]


def test_latest_smoke_pack_publishes_required_lineage_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)
    descriptor = pack_catalog.load_pack_descriptor("smoke-testing")
    latest = descriptor["latest_version"]
    assert _version_key(latest) >= _version_key(LINEAGE_FLOOR)
    assert set(descriptor["versions"]) >= {"1.0.0", "1.0.1", LINEAGE_FLOOR}
    assert descriptor["versions"][latest]["source"] == f"versions/{latest}/files"


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

    assert canonical["version"] == _latest_version()
    assert canonical["content_digest"] == packaged["content_digest"]
    assert canonical["files"] == packaged["files"]

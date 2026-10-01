"""Canonical PEP 440 tag spelling shared by both public release factories."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from packaging.version import Version

from yoke_core.domain.yaml_helper import load_document
from yoke_core.tools.release_tag_validation import validate_tag_spelling


_ROOT = Path(__file__).resolve().parents[3]
_RELEASE_WORKFLOW = _ROOT / ".github" / "workflows" / "yoke-release.yml"
_IMAGE_WORKFLOW = _ROOT / ".github" / "workflows" / "yoke-server-image.yml"
_RELEASE_DOC = _ROOT / "docs" / "releases" / "README.md"
_CANONICAL_TAGS = (
    "v0.0.0+0",
    "v1.2.3+launch.1",
    "v10.20.30+g140dff0aa.2abc.0",
)
_NORMALIZING_ALIASES = (
    "v01.02.03+launch.01",
    "v1.02.3+launch.1",
    "v1.2.03+launch.1",
    "v1.2.3+launch.01",
    "v1.2.3+01",
    "v0.0.0+00.abc",
)


def test_release_and_image_factories_share_the_canonical_tag_language():
    script = "packages/yoke-core/src/yoke_core/tools/release_tag_validation.py"
    for workflow in (_RELEASE_WORKFLOW, _IMAGE_WORKFLOW):
        steps = load_document(workflow)["jobs"]["validate-tag"]["steps"]
        validation = next(step for step in steps if step.get("id") == "tag")
        command = shlex.split(validation["run"])
        expected = ["python3", script]
        if workflow == _RELEASE_WORKFLOW:
            expected.append("--require-note-heading")
        assert command == expected, f"factory bypasses the shared validator: {workflow}"

    for tag in _CANONICAL_TAGS:
        assert str(Version(tag.removeprefix("v"))) == tag.removeprefix("v")
        validate_tag_spelling(tag)

    for tag in _NORMALIZING_ALIASES:
        raw_version = tag.removeprefix("v")
        assert str(Version(raw_version)) != raw_version
        with pytest.raises(ValueError, match="without leading-zero numeric atoms"):
            validate_tag_spelling(tag)

    operator_doc = _RELEASE_DOC.read_text(encoding="utf-8")
    assert "Use canonical decimal atoms" in operator_doc
    assert "numeric-local atoms with leading zeros are refused" in operator_doc

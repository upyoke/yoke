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
_CANONICAL_TAGS = ("0.2.0.202610140941", "1.2.3.202612312359", "10.20.30.202601010000")
_NORMALIZING_ALIASES = (
    "v0.2.0.202610140941",
    "00.2.0.202610140941",
    "0.02.0.202610140941",
    "0.2.00.202610140941",
    "0.2.0+202610140941",
    "0.2.0.202613010000",
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
        with pytest.raises(ValueError, match="release_version_invalid"):
            validate_tag_spelling(tag)

    operator_doc = _RELEASE_DOC.read_text(encoding="utf-8")
    assert "BASE.YYYYMMDDHHMM" in operator_doc
    assert "without a `v` prefix" in operator_doc

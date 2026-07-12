"""Canonical PEP 440 tag spelling shared by both public release factories."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from packaging.version import Version


_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS = (
    _ROOT / ".github" / "workflows" / "yoke-release.yml",
    _ROOT / ".github" / "workflows" / "yoke-server-image.yml",
)
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


def _pattern(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^\s*canonical_tag_re='([^']+)'$", text, re.MULTILINE)
    assert match is not None, f"missing canonical tag validator: {path}"
    assert '"$TAG_NAME" =~ $canonical_tag_re' in text
    return match.group(1)


def _bash_accepts(pattern: str, tag: str) -> bool:
    result = subprocess.run(
        ["bash", "-c", '[[ "$1" =~ $2 ]]', "canonical-tag", tag, pattern],
        check=False,
    )
    return result.returncode == 0


def test_release_and_image_factories_share_the_canonical_tag_language():
    patterns = [_pattern(path) for path in _WORKFLOWS]
    assert len(set(patterns)) == 1
    pattern = patterns[0]

    for tag in _CANONICAL_TAGS:
        assert str(Version(tag.removeprefix("v"))) == tag.removeprefix("v")
        assert re.fullmatch(pattern, tag), f"canonical tag rejected: {tag}"
        assert _bash_accepts(pattern, tag), f"Bash validator rejected: {tag}"

    for tag in _NORMALIZING_ALIASES:
        raw_version = tag.removeprefix("v")
        assert str(Version(raw_version)) != raw_version
        assert not re.fullmatch(pattern, tag), f"noncanonical alias accepted: {tag}"
        assert not _bash_accepts(pattern, tag), f"Bash validator accepted: {tag}"

    operator_doc = _RELEASE_DOC.read_text(encoding="utf-8")
    assert "Use canonical decimal atoms" in operator_doc
    assert "numeric-local atoms with leading zeros are refused" in operator_doc

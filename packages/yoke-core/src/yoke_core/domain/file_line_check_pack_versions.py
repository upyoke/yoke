"""Line-limit classification for immutable Pack version trees.

Pack versions are immutable: publishing a new version copies every file of
the prior version into ``packs/<slug>/versions/<version>/files/`` and edits
only the few that change. Judged naively, every one of those copies looks
like a brand-new authored file, so any file that was already over the
line limit in the prior version blocks the release — including files the
new version never opened. That turns a protected gate into a routine
bypass, which is worse than the oversized file it was guarding.

Two shapes are therefore not newly authored source:

* a version file whose bytes match the same relative path in another
  version of the same pack — carried forward, not written here;
* ``pack.json``, whose bulk is a per-version restatement of the version's
  file tree, so it grows mechanically with every release.

Neither exempts a file the author actually changed: a carried-forward copy
stops being exempt the moment its bytes differ from every sibling version.
"""

from __future__ import annotations

import pathlib
import re

#: ``packs/<slug>/versions/<version>/files/<relative path>``
_PACK_VERSION_FILE = re.compile(
    r"^packs/(?P<slug>[^/]+)/versions/(?P<version>[^/]+)/files/(?P<rel>.+)$"
)
#: ``packs/<slug>/pack.json``
_PACK_MANIFEST = re.compile(r"^packs/[^/]+/pack\.json$")


def is_pack_manifest(posix_path: str) -> bool:
    """True for a pack's ``pack.json`` version manifest."""
    return bool(_PACK_MANIFEST.match(posix_path))


def is_pack_version_carry_forward(
    posix_path: str, repo_root: pathlib.Path
) -> bool:
    """True when this pack version file is a byte-identical carry-forward.

    Compares against the same relative path in every other version of the
    same pack. A file that differs from all of them was authored here and
    stays subject to the limit.
    """
    match = _PACK_VERSION_FILE.match(posix_path)
    if match is None:
        return False

    candidate = repo_root / posix_path
    try:
        content = candidate.read_bytes()
    except OSError:
        return False

    versions_root = repo_root / "packs" / match["slug"] / "versions"
    try:
        siblings = sorted(versions_root.iterdir())
    except OSError:
        return False

    for sibling in siblings:
        if sibling.name == match["version"] or not sibling.is_dir():
            continue
        prior = sibling / "files" / match["rel"]
        try:
            if prior.read_bytes() == content:
                return True
        except OSError:
            continue
    return False


__all__ = ["is_pack_manifest", "is_pack_version_carry_forward"]

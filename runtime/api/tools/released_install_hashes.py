"""Render immutable installed-file ownership evidence from annotated releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


def git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=True
    )
    return completed.stdout


def source_key(path: str) -> str | None:
    if "/skills/yoke/" in path:
        return "skills/" + path.split("/skills/yoke/", 1)[1]
    if path.startswith("docs/public/"):
        return "docs/" + path.removeprefix("docs/public/")
    if path.startswith("runtime/harness/") and "/agents/" in path:
        return path
    return None


def render(root: Path) -> dict[str, list[str]]:
    tags = (
        git(root, "for-each-ref", "--format=%(refname) %(objecttype)", "refs/tags/v*")
        .decode()
        .splitlines()
    )
    objects: dict[str, set[str]] = {}
    releases = 0
    for tag in tags:
        ref, kind = tag.split()
        if kind != "tag":
            continue
        releases += 1
        tree = git(
            root,
            "ls-tree",
            "-r",
            "-z",
            ref,
            "--",
            ".agents/skills/yoke",
            ".claude/skills/yoke",
            "docs/public",
            "runtime/harness/claude/agents",
            "runtime/harness/codex/agents",
            "runtime/harness/cursor/agents",
        )
        for entry in tree.split(b"\0"):
            if not entry:
                continue
            header, path = entry.decode().split("\t", 1)
            _, kind, blob = header.split()
            key = source_key(path)
            if kind == "blob" and key:
                objects.setdefault(blob, set()).add(key)
    if not releases or not objects:
        raise RuntimeError(
            "release_catalogue_empty: fetch annotated release tags before rendering ownership evidence"
        )
    # One cat-file process reads all distinct contents rather than one process per file.
    stream = git(root, "cat-file", "--batch", data=("\n".join(objects) + "\n").encode())
    offset = 0
    hashes: dict[str, set[str]] = {}
    for blob, keys in objects.items():
        end = stream.index(b"\n", offset)
        actual, kind, length = stream[offset:end].decode().split()
        if actual != blob or kind != "blob":
            raise RuntimeError(
                "release_catalogue_blob_unreadable: restore the tagged git objects before rendering"
            )
        start = end + 1
        content = stream[start : start + int(length)]
        offset = start + int(length) + 1
        digest = hashlib.sha256(content).hexdigest()
        for key in keys:
            hashes.setdefault(key, set()).add(digest)
    print(
        f"released install evidence: {releases} annotated releases, {len(objects)} blobs, {len(hashes)} paths"
    )
    return {key: sorted(values) for key, values in sorted(hashes.items())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-checkout", type=Path, required=True)
    args = parser.parse_args()
    root = args.source_checkout.resolve()
    target = (
        root
        / "packages/yoke-cli/src/yoke_cli/project_install/released_bundle_hashes.json"
    )
    assert_target_under_session_work_authority(target)
    # Compact canonical JSON is generated runtime data, not authored prose.
    try:
        value = render(root)
    except (subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        parser.exit(
            1,
            f"release_catalogue_render_failed: {exc}. Restore annotated release objects and rerun; existing evidence was preserved.\n",
        )
    target.write_text(json.dumps(value, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()

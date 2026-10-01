"""Read-only release-tag validation shared by the public wheel and image factories.

Run directly with Python's standard library on a GitHub-hosted runner. The
validation job has only contents:read; building and signing remain separate.
"""

from __future__ import annotations

import json
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence


_ATOM = r"([a-z0-9]*[a-z][a-z0-9]*|0|[1-9][0-9]*)"
_NUMBER = r"(0|[1-9][0-9]*)"
_TAG = re.compile(rf"v{_NUMBER}\.{_NUMBER}\.{_NUMBER}\+{_ATOM}(\.{_ATOM})*")


def validate_tag_spelling(tag: str) -> None:
    """Refuse tag aliases that PEP 440 would normalize to a different spelling."""
    if not _TAG.fullmatch(tag):
        raise ValueError(
            "release tags must use canonical vX.Y.Z+local.N spelling "
            f"without leading-zero numeric atoms: {tag}"
        )


def validate_release_tag(
    env: dict[str, str], *, require_note_heading: bool = False
) -> dict[str, str]:
    """Require a canonical annotated tag peeling to this exact workflow commit."""
    tag = env["TAG_NAME"]
    validate_tag_spelling(tag)
    if env["GITHUB_REF"] != f"refs/tags/{tag}":
        raise ValueError(f"workflow ref must be refs/tags/{tag}")

    def api(path: str) -> dict:
        result = subprocess.run(
            ["gh", "api", f"repos/{env['GITHUB_REPOSITORY']}/{path}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return json.loads(result.stdout)

    remote = api(f"git/ref/tags/{tag}")["object"]
    tag_sha = remote["sha"]
    if remote["type"] != "tag" or not re.fullmatch(r"[0-9a-f]{40}", tag_sha):
        raise ValueError(f"release tag must be an annotated tag object: {tag}")
    tag_object = api(f"git/tags/{tag_sha}")
    target = tag_object["object"]
    source_sha = target["sha"]
    if target["type"] != "commit" or source_sha != env["GITHUB_SHA"]:
        raise ValueError(
            f"remote tag does not peel to workflow commit {env['GITHUB_SHA']}"
        )
    if require_note_heading:
        expected = f"Yoke {tag[1:]}"
        heading = (tag_object.get("message") or "").split("\n", 1)[0]
        if heading != expected:
            raise ValueError(
                f"annotated release tag message must start with: {expected}"
            )
    repository = f"ghcr.io/{env['GITHUB_REPOSITORY_OWNER'].lower()}/yoke-server"
    return {
        "latest_ref": f"{repository}:latest",
        "repository": repository,
        "release_version": tag[1:],
        "sha_ref": f"{repository}:{source_sha[:12]}",
        "sha_tag": source_sha[:12],
        "source_sha": source_sha,
        "tag_object_sha": tag_sha,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Publish validated identities to the job's output file or refuse clearly."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-note-heading", action="store_true")
    args = parser.parse_args(argv)
    try:
        outputs = validate_release_tag(
            dict(os.environ), require_note_heading=args.require_note_heading
        )
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as out:
            for key, value in outputs.items():
                out.write(f"{key}={value}\n")
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        print(
            f"release tag validation failed: {exc}. "
            "Repair the annotated release tag or GitHub API access before retrying.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

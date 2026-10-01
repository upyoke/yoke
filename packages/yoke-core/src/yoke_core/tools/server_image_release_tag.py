"""Read-only release-tag validation for the public server-image factory.

Run directly with Python's standard library on a GitHub-hosted runner. The
validation job has only contents:read; building and signing remain separate.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


_ATOM = r"([a-z0-9]*[a-z][a-z0-9]*|0|[1-9][0-9]*)"
_NUMBER = r"(0|[1-9][0-9]*)"
_TAG = re.compile(rf"v{_NUMBER}\.{_NUMBER}\.{_NUMBER}\+{_ATOM}(\.{_ATOM})*")


def validate_release_tag(env: dict[str, str]) -> dict[str, str]:
    """Require a canonical annotated tag peeling to this exact workflow commit."""
    tag = env["TAG_NAME"]
    if env["GITHUB_REF"] != f"refs/tags/{tag}" or not _TAG.fullmatch(tag):
        raise ValueError(
            "image release tags must use canonical vX.Y.Z+local.N spelling "
            f"without leading-zero numeric atoms: {tag}"
        )

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
        raise ValueError(f"image release tag must be an annotated tag object: {tag}")
    target = api(f"git/tags/{tag_sha}")["object"]
    source_sha = target["sha"]
    if target["type"] != "commit" or source_sha != env["GITHUB_SHA"]:
        raise ValueError(
            f"remote image tag does not peel to workflow commit {env['GITHUB_SHA']}"
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


def main() -> int:
    """Publish validated identities to the job's output file or refuse clearly."""
    try:
        outputs = validate_release_tag(dict(os.environ))
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as out:
            for key, value in outputs.items():
                out.write(f"{key}={value}\n")
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        print(
            f"server image release tag validation failed: {exc}. "
            "Repair the annotated release tag or GitHub API access before retrying.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

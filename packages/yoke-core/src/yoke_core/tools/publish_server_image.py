"""Publish verified main image digests under immutable commit-clock references."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

from yoke_contracts.release_version import BASE_VERSION, release_version, version_order
from yoke_core.tools.release_tag_validation import validate_release_tag


def run(command: list[str]) -> str:
    return subprocess.run(
        command, check=True, text=True, capture_output=True, timeout=120
    ).stdout.strip()


def inspect(reference: str) -> str | None:
    result = subprocess.run(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            reference,
            "--format",
            "{{ .Manifest.Digest }}",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    if re.search(r"manifest unknown|not found", result.stderr, re.IGNORECASE):
        return None
    raise ValueError(
        "image_registry_unreadable: restore GHCR access before retrying publication"
    )


def latest_release(repo: str) -> str:
    # matching-refs returns the full matching array; it is not paginated.
    refs = json.loads(
        run(["gh", "api", f"repos/{repo}/git/matching-refs/tags/{BASE_VERSION}."])
    )
    candidates = []
    for ref in refs:
        tag = ref["ref"].removeprefix("refs/tags/")
        try:
            release_version(tag)
        except ValueError:
            continue
        if ref["object"]["type"] == "tag":
            candidates.append(tag)
    if not candidates:
        raise ValueError("release_inventory_empty: restore the annotated release tag")
    return max(candidates, key=version_order)


def publish(env: dict[str, str]) -> None:
    identity = validate_release_tag(env)
    if identity["tag_object_sha"] != env["EXPECTED_TAG_OBJECT_SHA"]:
        raise ValueError(
            "release_tag_moved: restore the immutable annotated tag before retrying"
        )
    digest = env["PUSHED_DIGEST"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("image_digest_invalid: recover the verified main image record")
    repository = identity["repository"]
    immutable = identity["version_ref"]
    existing = inspect(immutable)
    if existing is not None and existing != digest:
        raise ValueError(
            "release_image_collision: keep the existing immutable image and release a distinct commit clock"
        )
    manifest = json.loads(
        run(
            [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                f"{repository}@{digest}",
                "--format",
                "{{json .Manifest}}",
            ]
        )
    )
    platforms = {
        f"{m['platform']['os']}/{m['platform']['architecture']}"
        for m in manifest["manifests"]
        if m["platform"]["os"] != "unknown"
    }
    if platforms != {"linux/amd64", "linux/arm64"}:
        raise ValueError(
            "published_image_platforms_missing: rerun the native main image factory"
        )
    references = [immutable]
    if latest_release(env["GITHUB_REPOSITORY"]) == env["TAG_NAME"]:
        references.append(identity["latest_ref"])
    for reference in references:
        if reference != immutable or existing is None:
            run(
                [
                    "docker",
                    "buildx",
                    "imagetools",
                    "create",
                    "--prefer-index=false",
                    "--tag",
                    reference,
                    f"{repository}@{digest}",
                ]
            )
        if inspect(reference) != digest:
            raise ValueError(
                "published_image_mismatch: inspect GHCR and retry publication without rebuilding"
            )
    print(f"Promoted {repository}@{digest} as {', '.join(references)}")


def main() -> int:
    try:
        publish(dict(os.environ))
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        print(
            f"image_publication_refused: {exc}; retry the publication job after correcting the named cause",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

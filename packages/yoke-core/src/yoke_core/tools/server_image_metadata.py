"""Self-identifying release metadata for the Yoke server image."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from importlib.metadata import version
from typing import Sequence


METADATA_MARKER = "YOKE_SERVER_IMAGE_METADATA="
_METADATA_FIELDS = frozenset({"build", "version"})


class ServerImageMetadataError(ValueError):
    """Raised when image metadata output violates its wire contract."""


@dataclass(frozen=True)
class ServerImageMetadata:
    """Installed product and source identities baked into an image."""

    version: str
    build: str

    def __post_init__(self) -> None:
        values = (self.version, self.build)
        if not all(isinstance(value, str) and value for value in values):
            raise ServerImageMetadataError(
                "metadata build and version must be non-empty strings"
            )


def format_metadata_line(metadata: ServerImageMetadata) -> str:
    """Return one marked, deterministic JSON metadata line."""
    payload = {"build": metadata.build, "version": metadata.version}
    return METADATA_MARKER + json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    )


def parse_metadata_output(output: str) -> ServerImageMetadata:
    """Read exactly one marked envelope while ignoring unrelated output."""
    marked_lines = [
        line for line in output.splitlines() if line.startswith(METADATA_MARKER)
    ]
    if not marked_lines:
        detail = repr(output[:200]) if output else "<empty>"
        raise ServerImageMetadataError(
            f"metadata marker missing; captured output was {detail}"
        )
    if len(marked_lines) != 1:
        raise ServerImageMetadataError(
            f"expected one metadata marker, found {len(marked_lines)}"
        )
    raw_payload = marked_lines[0][len(METADATA_MARKER) :]
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ServerImageMetadataError(
            f"metadata envelope is not valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != _METADATA_FIELDS:
        raise ServerImageMetadataError(
            "metadata envelope must contain exactly build and version"
        )
    return ServerImageMetadata(
        version=payload["version"],
        build=payload["build"],
    )


def installed_metadata() -> ServerImageMetadata:
    """Validate the installed runtime and return its release identities."""
    from yoke_core.tools.product_wheel_validation import verify_installed_boot

    verify_installed_boot()
    return ServerImageMetadata(
        version=version("yoke-core"),
        build=os.environ.get("YOKE_BUILD_SHA", ""),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("emit", help="Emit installed image metadata.")
    verify = commands.add_parser("verify", help="Verify captured image metadata.")
    verify.add_argument("--expected-version", required=True)
    verify.add_argument("--expected-build", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Emit installed metadata or verify a captured envelope."""
    args = _parser().parse_args(argv)
    if args.command == "emit":
        try:
            print(format_metadata_line(installed_metadata()))
        except ServerImageMetadataError as exc:
            print(f"server image metadata emission failed: {exc}", file=sys.stderr)
            return 1
        return 0

    try:
        actual = parse_metadata_output(sys.stdin.read())
    except ServerImageMetadataError as exc:
        print(f"server image metadata verification failed: {exc}", file=sys.stderr)
        return 1
    if actual.version != args.expected_version or actual.build != args.expected_build:
        print(
            "pushed image metadata mismatch: "
            f"version={actual.version} build={actual.build} "
            f"expected version={args.expected_version} build={args.expected_build}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "METADATA_MARKER",
    "ServerImageMetadata",
    "ServerImageMetadataError",
    "format_metadata_line",
    "installed_metadata",
    "main",
    "parse_metadata_output",
]

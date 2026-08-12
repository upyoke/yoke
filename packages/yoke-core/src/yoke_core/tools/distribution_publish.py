"""Validate Yoke static distribution release artifacts and public URLs.

The release tree is a private PEP 503 "simple" index plus immutable versioned
wheels. ``validate-release-artifact`` checks the flat, immutable payload emitted
for one release version. ``validate-release`` additionally requires that payload
at ``<output-root>/dist/releases/<version>`` and checks the sibling ``simple/``
tree. ``write-channel`` writes the mutable channel -> version pointer. ``smoke``
GETs the index pages and wheels and asserts cache headers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.parse import urljoin

from yoke_core.domain import json_helper
from yoke_core.resilient_fetch import FetchError, fetch_bytes
from yoke_core.tools import (
    distribution_channel,
    distribution_release_validation,
    migration_history_release_artifact,
    package_index,
    release_artifacts,
)


CHANNELS = distribution_channel.CHANNELS
channel_payload = distribution_channel.channel_payload
validate_channel_pointer = distribution_channel.validate_channel_pointer
MUTABLE_COMMON_PATHS = (
    "/install",
    "/dist/install.py",
)


@dataclass(frozen=True)
class UrlCheck:
    url: str
    sha256: str | None = None
    size: int | None = None
    cache_control_contains: str | None = None


def validate_release_directory(
    release_dir: Path,
    *,
    expected_source_commit: str | None = None,
) -> list[dict[str, object]]:
    """Validate a canonical publication tree and its ``simple/`` index.

    ``release_dir`` must be ``<output-root>/dist/releases/<version>``; the
    ``simple/`` tree lives at ``<output-root>/simple``. Returns the per-wheel
    records.
    """

    output_root = _publication_output_root(release_dir)
    records = validate_release_artifact_directory(
        release_dir,
        expected_source_commit=expected_source_commit,
    )
    versions = {str(record["version"]) for record in records}
    if versions != {release_dir.name}:
        raise ValueError(
            "release directory version does not match release records: "
            f"{release_dir.name}"
        )
    by_filename = {str(record["filename"]): record for record in records}
    distribution_release_validation.validate_simple_index(
        output_root / release_artifacts.SIMPLE_DIR, by_filename
    )
    return records


def validate_release_artifact_directory(
    release_artifact_dir: Path,
    *,
    expected_source_commit: str | None = None,
) -> list[dict[str, object]]:
    """Validate one flat downloaded release-artifact payload.

    The payload contains ``release-records.json``, ``wheels/``, and the
    migration-history manifest and evidence directly beneath
    ``release_artifact_dir``. It intentionally has no publication-tree or
    ``simple/`` index requirement.
    """

    records = _load_release_records(
        release_artifact_dir / release_artifacts.RELEASE_RECORDS_FILENAME
    )
    distribution_release_validation.validate_product_release_records(records)
    wheels_dir = release_artifact_dir / release_artifacts.WHEELS_DIR
    missing: list[str] = []
    for record in records:
        filename = str(record["filename"])
        wheel = wheels_dir / filename
        if not wheel.is_file():
            missing.append(f"{release_artifacts.WHEELS_DIR}/{filename}")
        elif wheel.stat().st_size != int(record["size"]):
            raise ValueError(f"{filename} size does not match release record")
        elif _sha256(wheel) != str(record["sha256"]):
            raise ValueError(f"{filename} sha256 does not match release record")
    if missing:
        raise ValueError("release directory is missing: " + ", ".join(missing))
    distribution_release_validation.validate_wheel_records_match(records, wheels_dir)
    distribution_release_validation.validate_sibling_pins(records, wheels_dir)
    migration_manifest = migration_history_release_artifact.validate_release_manifest(
        release_artifact_dir / release_artifacts.MIGRATION_HISTORY_MANIFEST_FILENAME,
        package_index.read_wheel_records(wheels_dir),
        expected_source_commit=expected_source_commit,
    )
    migration_history_release_artifact.validate_release_evidence(
        release_artifact_dir
        / release_artifacts.MIGRATION_HISTORY_RELEASE_EVIDENCE_FILENAME,
        migration_manifest,
        expected_source_commit=expected_source_commit,
    )
    return records


def _publication_output_root(release_dir: Path) -> Path:
    releases_dir = release_dir.parent
    dist_dir = releases_dir.parent
    if (
        not release_dir.name
        or releases_dir.name != release_artifacts.RELEASES_DIR
        or dist_dir.name != release_artifacts.DIST_ROOT
    ):
        raise ValueError(
            "validate-release requires release_dir layout "
            f"<output-root>/{release_artifacts.DIST_ROOT}/"
            f"{release_artifacts.RELEASES_DIR}/<version>; got {release_dir}"
        )
    return dist_dir.parent


def verify_urls(checks: Sequence[UrlCheck], *, timeout: float = 20.0) -> None:
    failures: list[str] = []
    for check in checks:
        try:
            headers, _body = _get_url(
                check.url, timeout=timeout,
                expected_sha256=check.sha256, expected_size=check.size,
            )
        except FetchError as exc:
            failures.append(f"{check.url}: {exc}")
            continue
        cache_control = headers.get("Cache-Control", "")
        if (
            check.cache_control_contains is not None
            and check.cache_control_contains not in cache_control
        ):
            failures.append(
                f"{check.url}: Cache-Control {cache_control!r} lacks "
                f"{check.cache_control_contains!r}"
            )
    if failures:
        raise ValueError("; ".join(failures))


def build_url_checks(
    *,
    base_url: str,
    records: Sequence[Mapping[str, object]],
    index_url: str,
    include_mutable: bool,
    mutable_channel: str | None = None,
) -> list[UrlCheck]:
    """Smoke checks for immutable wheels, the ``simple/`` index, and (optionally)
    the mutable installer + channel pointers.

    ``base_url`` is the versioned release base (``.../dist/releases/<version>/``)
    resolving immutable wheel URLs. ``index_url`` is the served ``simple/`` index
    URL — short-cache mutable, since it accretes wheels across versions.
    """

    # Wheels are immutable and already published; gate the mutable /simple/ index below.
    checks: list[UrlCheck] = [
        UrlCheck(
            _join_public_url(
                base_url, release_artifacts.WHEELS_DIR, str(record["filename"])
            ),
            sha256=str(record["sha256"]),
            size=_optional_int(record, "size"),
            cache_control_contains="immutable",
        )
        for record in records
    ]
    if include_mutable:
        checks.append(UrlCheck(index_url, cache_control_contains="max-age=60"))
        for project in sorted({str(record["project"]) for record in records}):
            checks.append(
                UrlCheck(
                    _join_public_url(index_url, project) + "/",
                    cache_control_contains="max-age=60",
                )
            )
        root = distribution_channel.site_root_from_release_base(base_url)
        checks.extend(
            UrlCheck(
                urljoin(root, path.lstrip("/")),
                cache_control_contains="max-age=60",
            )
            for path in _mutable_paths(mutable_channel)
        )
    return checks


def _mutable_paths(channel: str | None) -> tuple[str, ...]:
    if channel not in CHANNELS:
        raise ValueError(
            "mutable_channel must be stable or latest when include_mutable is true"
        )
    return (*MUTABLE_COMMON_PATHS, f"/dist/channels/{channel}.json")


def _load_release_records(path: Path) -> list[dict[str, object]]:
    payload = json_helper._load_json(path)
    if not isinstance(payload, list) or not all(
        isinstance(entry, dict) for entry in payload
    ):
        raise ValueError(f"release records must be an array of objects: {path}")
    return list(payload)


def _optional_int(record: Mapping[str, object], key: str) -> int | None:
    value = record.get(key)
    return None if value is None else int(value)


def _join_public_url(base: str, *parts: str) -> str:
    return distribution_channel.join_public_url(base, *parts)


def _quote_url_path(url: str) -> str:
    return distribution_channel.quote_url_path(url)


def _get_url(
    url: str, *, timeout: float, expected_sha256: str | None = None,
    expected_size: int | None = None,
) -> tuple[Mapping[str, str], bytes]:
    result = fetch_bytes(
        url, timeout=timeout, headers={"User-Agent": "yoke-distribution-smoke"},
        expected_sha256=expected_sha256, expected_size=expected_size,
    )
    return result.headers, result.body


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_channel(channel: str, channel_input: Path, output: Path) -> None:
    source = json_helper._load_json(channel_input)
    if not isinstance(source, dict):
        raise ValueError("channel input must be an object")
    validate_channel_pointer(source, require_content_evidence=True)
    migration_history = source.get("migration_history")
    if not isinstance(migration_history, dict):
        raise ValueError("channel input lacks migration_history release evidence")
    payload = channel_payload(
        channel=channel,
        version=str(source["version"]),
        index_url=str(source["index_url"]),
        release_base_url=str(source["release_base_url"]),
        generated_at=str(source.get("generated_at") or ""),
        migration_manifest_sha256=str(migration_history.get("manifest_sha256") or ""),
        source_commit=str(migration_history.get("source_commit") or ""),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Yoke static distribution artifacts and smoke URLs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_release = subparsers.add_parser("validate-release")
    validate_release.add_argument("release_dir", type=Path)
    validate_release.add_argument("--source-commit")
    validate_release_artifact = subparsers.add_parser("validate-release-artifact")
    validate_release_artifact.add_argument("release_artifact_dir", type=Path)
    validate_release_artifact.add_argument("--source-commit")
    channel = subparsers.add_parser("write-channel")
    channel.add_argument("--channel", choices=["stable", "latest"], required=True)
    channel.add_argument("--channel-input", type=Path, required=True)
    channel.add_argument("--output", type=Path, required=True)
    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--base-url", required=True)
    smoke.add_argument("--index-url", required=True)
    smoke.add_argument("--release-records", type=Path, required=True)
    smoke.add_argument("--include-mutable", action="store_true")
    smoke.add_argument("--channel", choices=CHANNELS)
    smoke.add_argument("--timeout", type=float, default=20.0)
    subparsers.add_parser("encode-url").add_argument("url")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "validate-release":
            validate_release_directory(
                args.release_dir,
                expected_source_commit=args.source_commit,
            )
            print(args.release_dir)
        elif args.command == "validate-release-artifact":
            validate_release_artifact_directory(
                args.release_artifact_dir,
                expected_source_commit=args.source_commit,
            )
            print(args.release_artifact_dir)
        elif args.command == "write-channel":
            _write_channel(args.channel, args.channel_input, args.output)
            print(args.output)
        elif args.command == "smoke":
            verify_urls(
                build_url_checks(
                    base_url=args.base_url,
                    records=_load_release_records(args.release_records),
                    index_url=args.index_url,
                    include_mutable=args.include_mutable,
                    mutable_channel=args.channel,
                ),
                timeout=args.timeout,
            )
            print(args.base_url)
        elif args.command == "encode-url":
            print(_quote_url_path(args.url))
        else:
            raise AssertionError(args.command)
    except (OSError, ValueError, KeyError) as exc:
        print(f"distribution-publish: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

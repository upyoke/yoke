"""Validate Yoke static distribution release artifacts and public URLs.

The release tree is a private PEP 503 "simple" index plus immutable versioned
wheels. ``validate-release`` checks versioned wheels against the per-wheel
``release-records.json`` and that the ``simple/`` tree lists every product wheel
with a matching ``#sha256=`` fragment. ``write-channel`` writes the mutable
channel -> version pointer. ``smoke`` GETs the index pages and wheels and
asserts cache headers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from yoke_core.domain import json_helper
from yoke_core.tools import package_index, release_artifacts


CHANNELS = ("stable", "latest")
MUTABLE_COMMON_PATHS = (
    "/install",
    "/dist/install.py",
)

# Wheel links in a PEP 503 page: href="<url>#sha256=<hex>" (single or double
# quotes), with the trailing >filename</a> text node.
_LINK_RE = re.compile(
    r'<a\s+href=(?P<q>["\'])(?P<href>.*?)(?P=q)\s*>(?P<text>[^<]*)</a>',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UrlCheck:
    url: str
    sha256: str | None = None
    size: int | None = None
    cache_control_contains: str | None = None


def validate_release_directory(release_dir: Path) -> list[dict[str, object]]:
    """Validate versioned wheels + the ``simple/`` index for ``release_dir``.

    ``release_dir`` is ``dist/releases/<version>``; the ``simple/`` tree lives at
    the output root (``release_dir.parents[2]``). Returns the per-wheel records.
    """

    records = _load_release_records(
        release_dir / release_artifacts.RELEASE_RECORDS_FILENAME
    )
    _validate_records(records)
    wheels_dir = release_dir / release_artifacts.WHEELS_DIR
    by_filename: dict[str, dict[str, object]] = {}
    missing: list[str] = []
    for record in records:
        filename = str(record["filename"])
        by_filename[filename] = record
        wheel = wheels_dir / filename
        if not wheel.is_file():
            missing.append(f"{release_artifacts.WHEELS_DIR}/{filename}")
        elif wheel.stat().st_size != int(record["size"]):
            raise ValueError(f"{filename} size does not match release record")
        elif _sha256(wheel) != str(record["sha256"]):
            raise ValueError(f"{filename} sha256 does not match release record")
    if missing:
        raise ValueError("release directory is missing: " + ", ".join(missing))
    _validate_simple_index(
        release_dir.parents[2] / release_artifacts.SIMPLE_DIR, by_filename
    )
    return records


def _validate_simple_index(
    simple_dir: Path,
    by_filename: Mapping[str, dict[str, object]],
) -> None:
    root_index = simple_dir / package_index.ROOT_INDEX_FILENAME
    if not root_index.is_file():
        raise ValueError(f"simple index is missing: {root_index}")
    root_html = root_index.read_text(encoding="utf-8")
    projects = {str(record["project"]) for record in by_filename.values()}
    linked: dict[str, str] = {}
    for project in projects:
        if f'href="{project}/"' not in root_html:
            raise ValueError(f"simple root index missing project link: {project}")
        project_index = simple_dir / project / package_index.ROOT_INDEX_FILENAME
        if not project_index.is_file():
            raise ValueError(f"simple project index is missing: {project_index}")
        for match in _LINK_RE.finditer(project_index.read_text(encoding="utf-8")):
            url, _, fragment = match.group("href").partition("#sha256=")
            if not fragment:
                raise ValueError(f"simple index wheel link missing sha256: {url}")
            linked[unquote(url.rstrip("/").rsplit("/", 1)[-1])] = fragment
    for filename, record in by_filename.items():
        sha = linked.get(filename)
        if sha is None:
            raise ValueError(f"simple index does not list wheel: {filename}")
        if sha != str(record["sha256"]):
            raise ValueError(f"simple index sha256 mismatch for {filename}")


def channel_payload(
    *,
    channel: str,
    version: str,
    index_url: str,
    release_base_url: str,
    generated_at: str,
    site_root: str | None = None,
) -> dict[str, object]:
    if channel not in CHANNELS:
        raise ValueError("channel must be stable or latest")
    root = site_root or _site_root_from_release_base(release_base_url)
    return {
        "schema_version": 2,
        "channel": channel,
        "version": version,
        "generated_at": generated_at,
        "index_url": index_url,
        "release_base_url": release_base_url,
        "installer": {
            "python_url": urljoin(root, "dist/install.py"),
            "shell_url": urljoin(root, "install"),
        },
    }


def verify_urls(checks: Sequence[UrlCheck], *, timeout: float = 20.0) -> None:
    failures: list[str] = []
    for check in checks:
        try:
            headers, body = _get_url(check.url, timeout=timeout)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            failures.append(f"{check.url}: {exc}")
            continue
        actual = hashlib.sha256(body).hexdigest()
        if check.sha256 is not None and actual != check.sha256:
            failures.append(f"{check.url}: sha256 {actual} does not match {check.sha256}")
        if check.size is not None and len(body) != check.size:
            failures.append(f"{check.url}: size {len(body)} does not match {check.size}")
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
        root = _site_root_from_release_base(base_url)
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


def _validate_records(records: Sequence[Mapping[str, object]]) -> None:
    package_index.validate_records(
        [
            package_index.WheelRecord(
                name=str(record["name"]),
                version=str(record["version"]),
                filename=str(record["filename"]),
                sha256=str(record["sha256"]),
                size=int(record["size"]),
                source=Path(str(record["filename"])),
            )
            for record in records
        ]
    )


def _optional_int(record: Mapping[str, object], key: str) -> int | None:
    value = record.get(key)
    return None if value is None else int(value)


def _site_root_from_release_base(base_url: str) -> str:
    marker = "/dist/releases/"
    if marker not in base_url:
        return base_url.rstrip("/") + "/"
    return base_url.split(marker, 1)[0].rstrip("/") + "/"


def _join_public_url(base: str, *parts: str) -> str:
    value = _quote_url_path(base.rstrip("/"))
    for part in parts:
        value += "/" + quote(part.strip("/"), safe="%")
    return value


def _quote_url_path(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, quote(parsed.path, safe="/%"),
         parsed.query, parsed.fragment)
    )


def _get_url(url: str, *, timeout: float) -> tuple[Mapping[str, str], bytes]:
    request = Request(url, headers={"User-Agent": "yoke-distribution-smoke"})
    with urlopen(request, timeout=timeout) as response:
        return response.headers, response.read()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_channel(channel: str, channel_input: Path, output: Path) -> None:
    source = json_helper._load_json(channel_input)
    if not isinstance(source, dict):
        raise ValueError("channel input must be an object")
    payload = channel_payload(
        channel=channel,
        version=str(source["version"]),
        index_url=str(source["index_url"]),
        release_base_url=str(source["release_base_url"]),
        generated_at=str(source.get("generated_at") or ""),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Yoke static distribution artifacts and smoke URLs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-release").add_argument("release_dir", type=Path)
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
            validate_release_directory(args.release_dir)
            print(args.release_dir)
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

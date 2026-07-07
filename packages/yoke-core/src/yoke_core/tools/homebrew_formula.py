"""Render the Homebrew formula from the Yoke release manifest."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import quote, urlsplit, urlunsplit

from yoke_core.domain import json_helper


DEFAULT_TEMPLATE = Path("packaging/homebrew/Formula/yoke.rb.in")
DEFAULT_OUTPUT = Path("packaging/homebrew/Formula/yoke.rb")
PRODUCT_CLI_PACKAGE = "yoke-cli"


def render_formula(
    *,
    manifest_path: Path,
    template_path: Path,
    manifest_url: str,
) -> str:
    manifest = _load_manifest(manifest_path)
    template = template_path.read_text(encoding="utf-8")
    packages = _manifest_packages(manifest)
    cli = _package_by_name(packages, PRODUCT_CLI_PACKAGE)
    replacements = {
        "PACKAGE_INDEX_MANIFEST_URL": manifest_url,
        "PACKAGE_INDEX_MANIFEST_SHA256": _sha256(manifest_path),
        "YOKE_CLI_VERSION": str(cli["version"]),
        "HOMEBREW_RESOURCES": _render_resources(
            packages,
            base_url=str(manifest["base_url"]),
        ),
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def _load_manifest(path: Path) -> dict[str, object]:
    payload = json_helper._load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("release manifest root must be an object")
    return payload


def _manifest_packages(manifest: dict[str, object]) -> list[dict[str, object]]:
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("release manifest packages must be a non-empty array")
    result: list[dict[str, object]] = []
    for entry in packages:
        if not isinstance(entry, dict):
            raise ValueError("release manifest package entries must be objects")
        for key in ("name", "version", "filename", "sha256", "size"):
            if key not in entry:
                raise ValueError(f"release manifest package missing {key}")
        result.append(entry)
    _package_by_name(result, PRODUCT_CLI_PACKAGE)
    _package_by_name(result, "yoke-harness")
    _package_by_name(result, "yoke-contracts")
    _package_by_name(result, "yoke-core")
    return result


def _package_by_name(
    packages: Sequence[dict[str, object]],
    name: str,
) -> dict[str, object]:
    for package in packages:
        if str(package.get("name")) == name:
            return package
    raise ValueError(f"release manifest missing required package {name}")


def _render_resources(
    packages: Sequence[dict[str, object]],
    *,
    base_url: str,
) -> str:
    blocks: list[str] = []
    for package in packages:
        name = str(package["name"])
        filename = str(package["filename"])
        url = _join_public_url(base_url, filename)
        url_line = f'    url "{url}", using: :nounzip'
        blocks.append(
            "\n".join(
                [
                    f'  resource "{name}" do',
                    url_line,
                    f'    sha256 "{package["sha256"]}"',
                    "  end",
                ]
            )
        )
    return "\n\n".join(blocks)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _join_public_url(base: str, *parts: str) -> str:
    value = _quote_url_path(base.rstrip("/"))
    for part in parts:
        value += "/" + quote(part.strip("/"), safe="%")
    return value


def _quote_url_path(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            quote(parsed.path, safe="/%"),
            parsed.query,
            parsed.fragment,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render packaging/homebrew/Formula/yoke.rb from a release manifest."
        ),
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE,
        help=f"Formula template path (default: {DEFAULT_TEMPLATE})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Rendered formula path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--manifest-url",
        required=True,
        help="Public URL for the manifest used as the formula source URL.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        rendered = render_formula(
            manifest_path=args.manifest,
            template_path=args.template,
            manifest_url=args.manifest_url,
        )
    except (OSError, ValueError) as exc:
        print(f"homebrew-formula: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

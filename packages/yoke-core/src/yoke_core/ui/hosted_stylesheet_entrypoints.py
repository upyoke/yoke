"""Render the raw HTML stylesheet blocks from the published host contract."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Optional, Sequence

from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


CONTRACT_REL = Path(
    "packages/yoke-core/src/yoke_core/ui/contracts/hosted-stylesheets.json"
)
STATIC_REL = Path("packages/yoke-core/src/yoke_core/ui/static")
GENERATED_BEGIN = "<!-- BEGIN GENERATED: hosted-stylesheet-entrypoints -->"
GENERATED_END = "<!-- END GENERATED: hosted-stylesheet-entrypoints -->"
IMPORT_PATTERN = re.compile(r'@import\s+url\(\s*["\']([^"\']+)["\']')


@dataclass(frozen=True)
class StylesheetEntrypoint:
    asset: str
    hosted_href: Optional[str] = None


@dataclass(frozen=True)
class HostedStylesheetContract:
    default_hosted_href_prefix: str
    entrypoints: tuple[StylesheetEntrypoint, ...]

    def hosted_hrefs(self) -> tuple[str, ...]:
        return tuple(
            entry.hosted_href or f"{self.default_hosted_href_prefix}{entry.asset}"
            for entry in self.entrypoints
        )


DOCUMENT_PREFIXES = {
    "index.html": "./assets/",
    "hosted-frame-harness.html": "./",
}


class HostedStylesheetContractError(ValueError):
    """The published stylesheet contract is malformed or inconsistent."""


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HostedStylesheetContractError(f"{label} must be an object")
    return value


def load_contract(path: Path) -> HostedStylesheetContract:
    raw = _require_dict(json.loads(path.read_text(encoding="utf-8")), "contract")
    if raw.get("schemaVersion") != 1:
        raise HostedStylesheetContractError("schemaVersion must be 1")
    prefix = raw.get("defaultHostedHrefPrefix")
    if (
        not isinstance(prefix, str)
        or not prefix.startswith("/")
        or not prefix.endswith("/")
    ):
        raise HostedStylesheetContractError(
            "defaultHostedHrefPrefix must be an absolute directory URL"
        )
    entries = raw.get("entrypoints")
    if not isinstance(entries, list) or not entries:
        raise HostedStylesheetContractError("entrypoints must be a non-empty array")
    parsed: list[StylesheetEntrypoint] = []
    seen: set[str] = set()
    for index, raw_entry in enumerate(entries):
        entry = _require_dict(raw_entry, f"entrypoints[{index}]")
        unknown = set(entry) - {"asset", "hostedHref"}
        if unknown:
            raise HostedStylesheetContractError(
                f"entrypoints[{index}] has unknown fields: {sorted(unknown)}"
            )
        asset = entry.get("asset")
        if (
            not isinstance(asset, str)
            or Path(asset).name != asset
            or not asset.endswith(".css")
        ):
            raise HostedStylesheetContractError(
                f"entrypoints[{index}].asset must be a CSS basename"
            )
        if asset in seen:
            raise HostedStylesheetContractError(f"duplicate entrypoint: {asset}")
        seen.add(asset)
        hosted_href = entry.get("hostedHref")
        if hosted_href is not None and (
            not isinstance(hosted_href, str) or not hosted_href.startswith("/")
        ):
            raise HostedStylesheetContractError(
                f"entrypoints[{index}].hostedHref must be an absolute URL path"
            )
        parsed.append(StylesheetEntrypoint(asset, hosted_href))
    return HostedStylesheetContract(prefix, tuple(parsed))


def render_link_block(contract: HostedStylesheetContract, href_prefix: str) -> str:
    links = "\n".join(
        f'  <link rel="stylesheet" href="{href_prefix}{entry.asset}">'
        for entry in contract.entrypoints
    )
    return f"  {GENERATED_BEGIN}\n{links}\n  {GENERATED_END}"


def render_document(
    source: str, contract: HostedStylesheetContract, href_prefix: str
) -> str:
    pattern = re.compile(
        rf"  {re.escape(GENERATED_BEGIN)}.*?  {re.escape(GENERATED_END)}",
        re.DOTALL,
    )
    if pattern.search(source) is None:
        raise HostedStylesheetContractError(
            "document has no generated stylesheet block"
        )
    return pattern.sub(render_link_block(contract, href_prefix), source, count=1)


def detect_drift(*, target_root: Path) -> list[str]:
    contract = load_contract(target_root / CONTRACT_REL)
    static_root = target_root / STATIC_REL
    drift: list[str] = []
    for document_name, href_prefix in DOCUMENT_PREFIXES.items():
        path = static_root / document_name
        source = path.read_text(encoding="utf-8")
        if source != render_document(source, contract, href_prefix):
            drift.append(document_name)
    return drift


def sync(*, target_root: Path) -> list[str]:
    contract = load_contract(target_root / CONTRACT_REL)
    static_root = target_root / STATIC_REL
    written: list[str] = []
    for document_name, href_prefix in DOCUMENT_PREFIXES.items():
        path = static_root / document_name
        source = path.read_text(encoding="utf-8")
        rendered = render_document(source, contract, href_prefix)
        if rendered == source:
            continue
        assert_target_under_session_work_authority(path)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, path)
        written.append(document_name)
    return written


def stylesheet_reachability_gaps(*, target_root: Path) -> list[str]:
    contract = load_contract(target_root / CONTRACT_REL)
    static_root = target_root / STATIC_REL
    reachable = {entry.asset for entry in contract.entrypoints}
    pending = list(reachable)
    while pending:
        asset = pending.pop()
        path = static_root / asset
        if not path.is_file():
            continue
        for imported_path in IMPORT_PATTERN.findall(path.read_text(encoding="utf-8")):
            imported = Path(imported_path).name
            if imported not in reachable:
                reachable.add(imported)
                pending.append(imported)
    shipped = {path.name for path in static_root.glob("*.css")}
    return sorted(shipped - reachable)


def _resolve_target_root(value: Optional[str]) -> Path:
    from yoke_core.domain.agents_render_workspace import resolve_target_root_for_cli

    return resolve_target_root_for_cli(value)


def run_cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("sync", "check"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--target-root", default=None)
    args = parser.parse_args(argv)
    target_root = _resolve_target_root(args.target_root)
    if args.command == "sync":
        written = sync(target_root=target_root)
        print("hosted stylesheet documents: " + (", ".join(written) or "in sync"))
        return 0
    drift = detect_drift(target_root=target_root)
    if drift:
        print("hosted stylesheet document drift: " + ", ".join(drift))
        print("Repair: python3 -m yoke_core.ui.hosted_stylesheet_entrypoints sync")
        return 1
    print("hosted stylesheet documents: in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())

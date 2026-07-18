"""Build an install bundle from one explicit Yoke source checkout.

This is a source-dev/admin subprocess boundary used by the product CLI. It
reads tracked bundle sources from the named checkout, emits JSON on stdout,
and never reads or writes Yoke server state. Apply mode performs only the
workspace-authority preflight; the product CLI remains the file writer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import runtime
import yoke_contracts

from yoke_contracts.install_binding import source_checkout_root
from yoke_contracts.project_contract.install_bundle import BUNDLE_SCHEMA
from yoke_core.domain import install_bundle
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


class SourceProjectBundleError(RuntimeError):
    """The explicit source checkout cannot produce a trustworthy bundle."""


SOURCE_MANAGED_PREFIXES = (
    ".agents/skills/yoke/",
    ".claude/skills/yoke/",
    ".codex/skills/yoke/",
    ".claude/agents/yoke-",
    ".claude/agents/references/",
    ".codex/agents/yoke-",
    ".claude/rules/",
)


def _assert_checkout_origin(source_checkout: Path) -> None:
    expected = source_checkout.resolve()
    modules = {
        "yoke_core": Path(install_bundle.__file__),
        "yoke_contracts": Path(yoke_contracts.__file__),
        "runtime": Path(runtime.__file__),
    }
    mismatched = []
    for name, module_file in modules.items():
        origin = source_checkout_root(module_file)
        if origin is None and name == "runtime":
            candidate = module_file.resolve().parent.parent
            origin = candidate if candidate == expected else None
        if origin is None or origin.resolve() != expected:
            mismatched.append(f"{name}={module_file.resolve()}")
    if mismatched:
        raise SourceProjectBundleError(
            "source bundle imports are not bound to the explicit checkout "
            f"{expected}: " + ", ".join(mismatched)
        )


def build_source_bundle(
    source_checkout: Path, *, project_id: int, project_slug: str,
) -> dict[str, Any]:
    """Render the DB-free portion of a project bundle deterministically."""
    source_checkout = source_checkout.expanduser().resolve()
    _assert_checkout_origin(source_checkout)
    files: list[dict[str, str]] = []
    files.extend(install_bundle._skill_files(source_checkout))
    files.extend(install_bundle._agent_files(source_checkout))
    files.extend(install_bundle._rules_files(source_checkout))
    files.sort(key=lambda entry: entry["path"])
    hooks = install_bundle._hooks_block()
    digest_source = json.dumps(
        {"files": files, "hooks": hooks},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    source_version = "source-" + hashlib.sha256(digest_source).hexdigest()[:16]
    return {
        "bundle_schema": BUNDLE_SCHEMA,
        "yoke_version": source_version,
        "project_id": int(project_id),
        "project_slug": project_slug,
        "files": files,
        # These surfaces require project DB state. A source refresh preserves
        # the receiving checkout's project-owned contract and strategy views.
        "project_contract_files": [],
        "strategy_files": [],
        "project_policy_capabilities": {},
        "hooks": hooks,
        "source_managed_prefixes": list(SOURCE_MANAGED_PREFIXES),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-checkout", required=True)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--project-id", required=True, type=int)
    parser.add_argument("--project-slug", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    source_checkout = Path(args.source_checkout).expanduser().resolve()
    target_root = Path(args.target_root).expanduser().resolve()
    if args.apply:
        assert_target_under_session_work_authority(target_root)
    bundle = build_source_bundle(
        source_checkout,
        project_id=args.project_id,
        project_slug=args.project_slug,
    )
    print(json.dumps(bundle, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SourceProjectBundleError",
    "SOURCE_MANAGED_PREFIXES",
    "build_source_bundle",
    "main",
]

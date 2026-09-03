from __future__ import annotations

import json
from pathlib import Path
import re

from yoke_contracts.packs import PACK_DESCRIPTOR_SCHEMA


ROOT = Path(__file__).resolve().parents[3]
PACKS = ROOT / "packs"

EXPECTED_TOOLS = {
    "branch-preview-hosting": {"docker", "node"},
    "container-runtime": {"docker"},
    "domain-cdn-edge": {"pulumi"},
    "ephemeral-environments": set(),
    "host-maintenance": {"docker"},
    "machine-qa": {"ssh"},
    "managed-database": {"pulumi"},
    "production-deploy": {"docker", "ssh"},
    "pulumi-foundation": {"pulumi"},
    "registry-oidc": {"pulumi"},
    "self-hosted-runners": {"pulumi"},
    "smoke-testing": set(),
    "structured-events": set(),
    "vps-hosting": {"pulumi", "ssh"},
    "webapp-environment-infrastructure": {"pulumi"},
    "webapp-scaffold": {"node", "npm"},
}

_DIRECT_INVOCATIONS = {
    "docker": re.compile(r'(?:shutil\.which\(|\[)["\']docker["\']'),
    "node": re.compile(r"^#!.*\bnode\b", re.MULTILINE),
    "npm": re.compile(r"(?:^[ \t]*|[;&|][ \t]*)(?:npm|npx)[ \t]", re.MULTILINE),
    "pulumi": re.compile(r"^(?:from|import) pulumi\b", re.MULTILINE),
    "ssh": re.compile(
        r"(?:^[ \t]*(?:#[ \t]*)?|[;&|][ \t]*)(?:ssh|scp)[ \t]", re.MULTILINE
    ),
}


def _descriptor(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _invoked_tools(pack_root: Path, version: dict) -> set[str]:
    discovered: set[str] = set()
    source_root = pack_root / version["source"]
    verification = "\n".join(row["command"] for row in version["verification"])
    for tool, pattern in _DIRECT_INVOCATIONS.items():
        if pattern.search(verification):
            discovered.add(tool)
    for file_record in version["files"]:
        path = source_root / file_record["source"]
        if path.relative_to(source_root).parts[0] in {"docs", ".github"}:
            continue
        if path.name.startswith("Pulumi") and path.suffix in {".yaml", ".yml"}:
            discovered.add("pulumi")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for tool, pattern in _DIRECT_INVOCATIONS.items():
            if pattern.search(content):
                discovered.add(tool)
    return discovered


def test_every_shipped_pack_version_declares_a_complete_tool_contract() -> None:
    observed: dict[str, set[str]] = {}
    for path in sorted(PACKS.glob("*/pack.json")):
        descriptor = _descriptor(path)
        assert descriptor["schema"] == PACK_DESCRIPTOR_SCHEMA, path
        versions = descriptor["versions"]
        for version, record in versions.items():
            declarations = record["prerequisites"]
            tools = {row["tool"] for row in declarations}
            assert len(tools) == len(declarations), (path, version)
            assert tools == EXPECTED_TOOLS[descriptor["slug"]], (path, version)
            for row in declarations:
                assert set(row["install"]) == {"darwin", "linux", "windows"}
                assert row["probe"]["version_args"]
        latest = versions[descriptor["latest_version"]]
        observed[descriptor["slug"]] = {row["tool"] for row in latest["prerequisites"]}

    assert observed == EXPECTED_TOOLS


def test_pack_files_do_not_invoke_an_undeclared_machine_tool() -> None:
    offenders: list[str] = []
    for path in sorted(PACKS.glob("*/pack.json")):
        descriptor = _descriptor(path)
        version_name = descriptor["latest_version"]
        version = descriptor["versions"][version_name]
        declared = {row["tool"] for row in version["prerequisites"]}
        missing = _invoked_tools(path.parent, version) - declared
        if missing:
            offenders.append(
                f"{descriptor['slug']}@{version_name}: {', '.join(sorted(missing))}"
            )

    assert not offenders, "Pack tool invocations need prerequisites:\n" + "\n".join(
        offenders
    )

"""Packets may only point at docs that reach a managed project.

Packet bodies travel two ways: managed-project session orientation renders the
main-agent packet, and every rendered subagent adapter carries its role's packet
verbatim. Both reach projects that are not Yoke checkouts, so a doc pointer
only helps if that doc ships. ``.yoke/docs/`` is the shipped set; every other
docs tree exists only in the Yoke source repo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain import schema_api_context_seed as seed


SHIPPED_DOCS_PREFIX = ".yoke/docs/"
ROOT = Path(__file__).resolve().parents[3]
PORTABLE_HOMES = (
    ".yoke/docs/agents/rules/code-and-cli.md",
    ".yoke/docs/documentation/index.md",
)

# Backticked path ending in .md with a `docs/` segment somewhere in it —
# the shape every doc pointer in a packet note uses.
_DOC_POINTER = re.compile(r"`([^`\s]*docs/[^`\s]+\.md)`")


def _doc_pointers(text: str) -> set[str]:
    return set(_DOC_POINTER.findall(text))


def test_every_topic_packet_points_only_at_shipped_docs() -> None:
    offenders = sorted(
        {
            pointer
            for topic in seed.TOPICS
            for pointer in _doc_pointers(sac.render_topic_packet(topic))
            if not pointer.startswith(SHIPPED_DOCS_PREFIX)
        }
    )

    assert offenders == [], (
        "packets point at Yoke source-repo docs that a managed project does "
        f"not have; ship them under {SHIPPED_DOCS_PREFIX} or drop the "
        f"pointer: {offenders}"
    )


def test_every_role_packet_points_only_at_shipped_docs() -> None:
    # Role packets are what the subagent adapters actually carry, so they
    # are checked as assembled rather than trusting per-topic coverage.
    offenders = sorted(
        {
            f"{role}: {pointer}"
            for role in seed.ROLE_TOPICS
            for pointer in _doc_pointers(sac.render_role_packet(role))
            if not pointer.startswith(SHIPPED_DOCS_PREFIX)
        }
    )

    assert offenders == [], (
        "role packets point at Yoke source-repo docs that a managed project "
        f"does not have: {offenders}"
    )


def test_the_pointer_pattern_recognizes_both_shipped_and_source_paths() -> None:
    # Guards the guard: a regex that matched nothing would make the two
    # tests above pass no matter what the packets say.
    sample = (
        "see `.yoke/docs/functions/index.md` and also "
        "`docs/atlas.md` plus `runtime/agents/notes.md`"
    )

    assert _doc_pointers(sample) == {
        ".yoke/docs/functions/index.md",
        "docs/atlas.md",
    }


def test_every_role_receives_portable_rule_reads_before_action() -> None:
    for role in seed.ROLE_TOPICS:
        packet = sac.render_role_packet(role)
        for home in PORTABLE_HOMES:
            assert f"`cat {home}`" in packet, (role, home)


def test_packet_shipped_targets_exist_in_the_canonical_bundle() -> None:
    bundle = ROOT / "packages/yoke-core/src/yoke_core/install_bundle_tree/docs/public"
    pattern = re.compile(r"\.yoke/docs/([A-Za-z0-9_./-]+\.md)")
    for role in seed.ROLE_TOPICS:
        for relative in pattern.findall(sac.render_role_packet(role)):
            target = (bundle / relative).resolve()
            assert target.is_relative_to(bundle.resolve()), (role, relative)
            assert target.is_file(), (role, relative)


def test_native_main_entry_and_claude_rules_teach_the_same_homes() -> None:
    for relative in ("AGENTS.md", "runtime/harness/claude/rules/session.md"):
        text = (ROOT / relative).read_text()
        for home in PORTABLE_HOMES:
            assert f"`{home}`" in text, (relative, home)
        assert ".yoke/docs/projects/execution-instructions.md" in text


def test_public_extraction_contract_keeps_private_rollback_and_delivery() -> None:
    text = (ROOT / "docs/public/projects/execution-instructions.md").read_text()
    for instruction in (
        "neutral summaries",
        "fresh durable private rollback",
        "actual receiving context",
        "Preserve\nthe instruction's scope and delivery settings",
    ):
        assert instruction in text
    assert "a global session cannot assume this directory contains `.yoke/docs`" in text


def test_every_rendered_worker_receives_the_portable_homes() -> None:
    for harness, extension in (("claude", "md"), ("codex", "toml"), ("cursor", "md")):
        adapters = ROOT / "runtime/harness" / harness / "agents"
        paths = list(adapters.glob(f"yoke-*.{extension}"))
        assert len(paths) == 8
        for path in paths:
            text = path.read_text()
            for home in PORTABLE_HOMES:
                assert home in text, (path, home)


def test_conditional_procedures_are_available_before_their_action() -> None:
    references = {
        "engineer": ("implementation", "before editing or running checks"),
        "architect": ("task-templates", "Before authoring a plan or task"),
        "tester": ("reporting", "Before writing or recording a verdict"),
    }
    bundle = ROOT / "packages/yoke-core/src/yoke_core/install_bundle_tree"
    for role, (name, moment) in references.items():
        source = ROOT / f"runtime/agents/{role}.md"
        assert moment in source.read_text()
        relative = f"runtime/harness/claude/agents/references/{role}/{name}.md"
        assert (ROOT / relative).read_bytes() == (bundle / relative).read_bytes()
        for harness, ext in (("claude", "md"), ("codex", "toml"), ("cursor", "md")):
            prompt = ROOT / f"runtime/harness/{harness}/agents/yoke-{role}.{ext}"
            assert f".claude/agents/references/{role}/{name}.md" in prompt.read_text()


def test_active_machine_pack_pointer_is_portable_and_retains_sign_in_boundary() -> None:
    catalog = ROOT / "packs/machine-qa/pack.json"
    descriptor = json.loads(catalog.read_text())
    latest = descriptor["versions"][descriptor["latest_version"]]
    payload = catalog.parent / latest["source"] / "docs/packs/machine-qa"
    assert (
        ".yoke/docs/verification/browser-identities.md"
        in (payload / "browser-identities.md").read_text()
    )
    for os_name in ("linux", "macos", "windows"):
        text = (payload / f"{os_name}-host-provisioning.md").read_text()
        assert "project-owned sign-in policy" in text
        assert "only types their own\n   password or credential" in text
        assert "https://github.com/upyoke/yoke/blob/" not in text
        assert "docs/public/" not in text

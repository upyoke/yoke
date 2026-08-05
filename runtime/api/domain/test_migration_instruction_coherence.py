"""Active migration instructions agree on permanent boot-applied history."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

ACTIVE_INSTRUCTIONS = (
    ".agents/skills/yoke/idea/body-and-sync-functions.md",
    ".agents/skills/yoke/idea/body-and-sync.md",
    ".agents/skills/yoke/advance/implementing/test-and-record.md",
    "runtime/harness/claude/agents/references/engineer/migration-protocol.md",
    "runtime/agents/engineer/migration-protocol.md",
    "packages/yoke-core/src/yoke_core/install_bundle_tree/AGENTS.md",
    (
        "packages/yoke-core/src/yoke_core/install_bundle_tree/runtime/"
        "harness/claude/agents/references/engineer/migration-protocol.md"
    ),
)

FORBIDDEN_TEACHING = (
    "retire-the-module",
    "retire-AC",
    "migration_apply` lifecycle hook",
    "python3 -m yoke_core.domain.migration_apply rehearse",
    "followed by ``live-apply``",
    "safe to delete",
)


def test_active_migration_instructions_have_one_lifecycle() -> None:
    violations: list[str] = []
    for relative in ACTIVE_INSTRUCTIONS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for phrase in FORBIDDEN_TEACHING:
            if phrase in text:
                violations.append(f"{relative}: {phrase}")
    assert not violations, "conflicting migration teaching:\n" + "\n".join(violations)


def test_every_active_engineer_reference_teaches_registered_rehearsal() -> None:
    references = [path for path in ACTIVE_INSTRUCTIONS if path.endswith(
        "engineer/migration-protocol.md"
    )]
    for relative in references:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "yoke migration rehearse PREFIX-N" in text, relative
        assert "Never delete it afterwards" in text, relative

"""The source checkout shares one native project instruction contract."""

import json
from pathlib import Path

from yoke_contracts.project_contract.managed_block import extract_block_body

REPO = Path(__file__).resolve().parents[2]


def test_shared_rules_retain_the_harness_neutral_tool_contract():
    text = (REPO / "AGENTS.md").read_text()
    assert "Bash tool calls" in text
    assert "Subagent Bash calls" not in text
    assert extract_block_body(text)


def test_all_harnesses_declare_the_same_canonical_instruction_source():
    for harness in ("claude", "codex", "cursor"):
        manifest = json.loads(
            (REPO / "runtime/harness" / harness / "manifest.json").read_text()
        )
        assert manifest["cli"]["project_discovery"]["instruction_file"] == "AGENTS.md"
    for name in ("CLAUDE.md", "CODEX.md", "CURSOR.md"):
        assert not (REPO / name).exists()


def test_shared_rules_let_the_work_claim_holder_attest_its_overlap():
    text = (REPO / "AGENTS.md").read_text()
    assert "The session holding the work claim attests independent overlaps" in text
    assert "from its own skill" in text
    assert "When no live work-claim holder exists, route to `/yoke refine`" in text

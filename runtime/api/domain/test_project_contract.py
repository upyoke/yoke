"""Tests for the project-local ``.yoke`` contract bundle content."""

from __future__ import annotations

import json
from dataclasses import MISSING, fields
from pathlib import Path


from yoke_contracts.project_contract.board_art.config import (
    BLACK,
    WHITE,
    derive_letter_bounds,
    parse_art_config,
)
from yoke_contracts.board.config import BoardConfig, parse_config
from yoke_core.domain import lint_config, project_contract
from yoke_contracts.project_contract.board_art import (
    FALLBACK_ART_WORD,
    MAX_ART_WORD_LEN,
    choose_art_word,
    render_board_art,
)

EXPECTED_CONTRACT_PATHS = {
    ".yoke/.gitignore",
    ".yoke/README.md",
    ".yoke/file-line-exceptions",
    ".yoke/lint-config",
    ".yoke/labels",
    ".yoke/board.json",
    ".yoke/board-art",
    ".yoke/deployment-flows.json",
    ".yoke/test-inventory.md",
    ".yoke/runbooks/deploy.md",
    ".yoke/runbooks/deploy-checklist.md",
    ".yoke/runbooks/recovery.md",
}


def _entries() -> dict[str, dict[str, str]]:
    return {
        e["path"]: e for e in project_contract.bundle_contract_files("Acme")
    }


def test_bundle_contract_files_shape() -> None:
    entries = project_contract.bundle_contract_files("Acme")
    assert [e["path"] for e in entries] == sorted(e["path"] for e in entries)
    assert {e["path"] for e in entries} == EXPECTED_CONTRACT_PATHS
    for e in entries:
        assert e["install_policy"] == project_contract.SEED_IF_MISSING
        assert e["category"] == project_contract.CATEGORY_PROJECT_POLICY
        assert e["content"].endswith("\n")
        assert e["path"].startswith(".yoke/")


def test_no_forbidden_or_generated_paths_in_bundle() -> None:
    paths = {e["path"] for e in project_contract.bundle_contract_files("Acme")}
    assert not paths & set(project_contract.FORBIDDEN_CONTRACT_RELATIVE_PATHS)
    assert ".yoke/BOARD.md" not in paths
    assert ".yoke/BOARD.md.ts" not in paths
    assert ".yoke/board-art.example" not in paths
    assert ".yoke/install-manifest.json" not in paths


def test_yoke_gitignore_covers_generated_and_machine_state_names() -> None:
    body = _entries()[".yoke/.gitignore"]["content"]
    lines = [
        line for line in body.splitlines() if line and not line.startswith("#")
    ]
    assert lines == list(project_contract.YOKE_TREE_IGNORED_NAMES)
    for required in ("BOARD.md", "backups/", "install-manifest.json"):
        assert required in lines
    # The tracked Yoke-repo copy must stay byte-identical to the seed so
    # refresh adoption and uninstall byte-equality semantics hold.
    repo_copy = Path(__file__).resolve().parents[3] / ".yoke/.gitignore"
    assert repo_copy.read_text(encoding="utf-8") == body


def test_lint_config_is_canonical_render_covering_guard_catalog() -> None:
    body = _entries()[".yoke/lint-config"]["content"]
    assert body == lint_config.render_lint_config(), (
        "one source of truth: the bundle ships render_lint_config() verbatim"
    )
    for spec in lint_config.GUARD_CATALOG:
        assert f"{spec.guard}={lint_config.DENY}" in body


def test_render_label_policy_uses_key_value_format() -> None:
    body = _entries()[".yoke/labels"]["content"]
    assert body == project_contract.render_label_policy()
    assert "label_color_type_epic=" in body
    assert "label_color_status_done=" in body
    assert "label_color_frozen=" in body
    assert "{" not in body


def test_board_config_covers_every_recognized_knob_at_default() -> None:
    payload = json.loads(_entries()[".yoke/board.json"]["content"])
    recognized = {
        f.name: f.default for f in fields(BoardConfig) if f.default is not MISSING
    }
    assert payload == recognized, (
        "seeded board.json must carry exactly the recognized scalar knobs "
        "at their dataclass defaults"
    )
    assert "rainbow_sub_weights" not in payload
    # Machine view binding never leaks into the project file.
    assert "scope" not in payload
    assert "render_path" not in payload


def test_seeded_board_config_parses_to_default_render_behavior(
    tmp_path: Path,
) -> None:
    target = tmp_path / "board.json"
    target.write_text(_entries()[".yoke/board.json"]["content"], "utf-8")
    parsed = parse_config(str(target))
    defaults = BoardConfig()
    for f in fields(BoardConfig):
        if f.name == "rainbow_sub_weights":
            continue
        assert getattr(parsed, f.name) == getattr(defaults, f.name)
    # All-zero rainbow sub-weights are behavior-equivalent to unset: the
    # selector falls back to equal weights when the pool total is 0.
    assert set(parsed.rainbow_sub_weights.values()) <= {0}


def test_board_art_parses_and_master_map_spells_display_name(
    tmp_path: Path,
) -> None:
    content = _entries()[".yoke/board-art"]["content"]
    target = tmp_path / "board-art"
    target.write_text(content, encoding="utf-8")

    cfg = parse_art_config(str(target))
    assert cfg.master_map, "master map section must parse nonempty"
    assert cfg.ascii_variants, "an ASCII variant must parse"
    assert cfg.mixed_variants, "a Mixed variant must parse"

    rows = cfg.master_map
    assert len({len(row) for row in rows}) == 1, "rows are equal width"
    assert set("".join(rows)) <= {WHITE, BLACK}, "only fill/structural cells"
    assert set(rows[0]) == {BLACK}, "all-structural top border"
    assert set(rows[-1]) == {BLACK}, "all-structural bottom border"
    assert len(derive_letter_bounds(rows)) == len("ACME"), (
        "separator columns must isolate the project display-name letters"
    )


def test_board_art_is_project_specific_not_generic() -> None:
    content = _entries()[".yoke/board-art"]["content"]
    assert content == render_board_art("Acme")
    for line in content.splitlines():
        if line.startswith("#"):
            continue  # header comments name the Yoke renderer; that's fine
        assert "P R O J E C T" not in line.upper()


def test_choose_art_word_prefers_name_then_acronym_then_truncation() -> None:
    assert choose_art_word("Acme") == "ACME"
    assert choose_art_word("Customer Support Portal") == "CSP"
    assert choose_art_word("HypergraphKnowledgeWorkbench") == "HYPERGRA"
    assert (
        len(choose_art_word("HypergraphKnowledgeWorkbench"))
        == MAX_ART_WORD_LEN
    )
    assert choose_art_word("!!!", slug="validsluglong") == "VALIDSLU"
    assert choose_art_word("!!!") == FALLBACK_ART_WORD


def test_render_board_art_truncates_long_single_token_without_project_fallback(
    tmp_path: Path,
) -> None:
    content = render_board_art("HypergraphKnowledgeWorkbench")
    assert "P R O J E C T" not in content

    target = tmp_path / "board-art"
    target.write_text(content, encoding="utf-8")
    cfg = parse_art_config(str(target))
    assert set(cfg.master_map[0]) == {BLACK}
    assert set(cfg.master_map[-1]) == {BLACK}
    assert len(derive_letter_bounds(cfg.master_map)) == MAX_ART_WORD_LEN




def test_readme_documents_the_three_way_split() -> None:
    body = _entries()[".yoke/README.md"]["content"]
    assert "# Acme Yoke Project Contract" in body
    assert "~/.yoke/config.json" in body
    assert "board.json" in body
    assert "render_path" in body
    assert "seeded once" in body


def test_readme_maps_where_settings_live() -> None:
    body = _entries()[".yoke/README.md"]["content"]
    assert "## Where settings live" in body
    # Repo-owned families.
    for token in ("file-line-exceptions", "board.json",
                  "deployment-flows.json", "lint-config", "labels", "strategy/"):
        assert token in body, token
    assert "project.config" not in body
    # DB-owned families each name their read/write command.
    for token in (
        "project-policy",
        "session-routing",
        "projects get|update",
        "yoke projects capability has",
        "yoke projects capability-secret set",
        "Project Structure patches",
        "project-onboarding surfaces",
        "project-structure command-definitions get|list",
        "project-structure patch apply",
        "deployment-flows reconcile-project",
        "sites.settings",
    ):
        assert token in body, token


def test_file_line_exceptions_seed_explains_policy() -> None:
    body = _entries()[".yoke/file-line-exceptions"]["content"]
    assert "one repo-relative glob per line" in body.lower()
    assert "Blank lines and lines starting with #" in body
    assert "Do not use this to avoid splitting normal source code" in body
    assert "# docs/generated-reference/**" in body


def test_runbooks_are_fill_me_in_scaffolds() -> None:
    entries = _entries()
    for rel in (
        ".yoke/runbooks/deploy.md",
        ".yoke/runbooks/recovery.md",
        ".yoke/runbooks/deploy-checklist.md",
    ):
        body = entries[rel]["content"]
        assert "Acme" in body
        assert "TODO" in body, f"{rel} must invite filling in"


def test_scaffolds_are_parameterized_by_display_name() -> None:
    one = {
        e["path"]: e["content"]
        for e in project_contract.bundle_contract_files("Acme")
    }
    other = {
        e["path"]: e["content"]
        for e in project_contract.bundle_contract_files("Widget Co")
    }
    assert "# Test Inventory: Widget Co" in other[".yoke/test-inventory.md"]
    assert one[".yoke/board-art"] == render_board_art("Acme")
    assert other[".yoke/board-art"] == render_board_art("Widget Co")
    assert one[".yoke/board-art"] != other[".yoke/board-art"]
    # Recognizer-generated config does not vary by project name.
    for rel in (
        ".yoke/file-line-exceptions",
        ".yoke/lint-config",
        ".yoke/labels",
        ".yoke/board.json",
    ):
        assert one[rel] == other[rel]

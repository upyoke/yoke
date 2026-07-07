"""Board-art onboarding step: name ladder, generators, flow, and shortcut."""

from __future__ import annotations

from pathlib import Path

import pytest

# The flow + helper modules pull Textual/Rich (via the wizard widgets); skip the
# whole file where that optional dep is absent, matching the other wizard suites.
pytest.importorskip("textual")

from yoke_cli.config import onboard_wizard_board_art as art  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardResult  # noqa: E402
from yoke_cli.config.onboard_wizard_flow_board_art import BoardArtFlow  # noqa: E402
from yoke_contracts.project_contract.board_art import (  # noqa: E402
    MAX_ART_WORD_LEN,
    generate_random_ascii_variant_detail,
    generate_random_mixed_variant_detail,
    normalize_header_art_word,
    normalize_master_map_word,
    resolve_project_art_word,
)


# ── name ladder ─────────────────────────────────────────────
def test_resolve_word_short_display_name_used_whole():
    assert resolve_project_art_word("Buzz", slug="buzz", short_code="BUZZ") == "BUZZ"


def test_resolve_word_long_name_falls_to_first_word():
    # whole join is too long; the first word fits and is most recognizable.
    assert resolve_project_art_word(
        "Buzz Marketing Platform", slug="buzz-marketing-platform",
        short_code="BUZZ",
    ) == "BUZZ"


def test_resolve_word_acronym_when_every_word_is_long():
    assert resolve_project_art_word(
        "International Business Machines", slug="international-business-machines",
        short_code="IBM",
    ) == "IBM"


def test_resolve_word_smart_truncation_last_resort():
    word = resolve_project_art_word("Constantinople")
    assert 1 <= len(word) <= MAX_ART_WORD_LEN
    assert word[0] == "C"


def test_resolve_word_empty_falls_back_to_project():
    assert resolve_project_art_word("", slug=None, short_code=None) == "PROJECT"


# ── normalizers ─────────────────────────────────────────────
def test_normalize_master_map_word_caps_and_uppercases():
    assert normalize_master_map_word("my cool app") == "MYCOOLAP"  # 9 -> 8
    assert normalize_master_map_word("!!!") == ""


def test_normalize_header_art_word_keeps_spaces_allows_longer():
    out = normalize_header_art_word("Buzz Marketing Platform")
    assert out == "BUZZ MARKETING PLATFORM"
    assert len(out) > MAX_ART_WORD_LEN  # header art is not capped at the map limit


# ── generator word override ─────────────────────────────────
def test_ascii_generator_word_override_bypasses_choose_art_word():
    variant = generate_random_ascii_variant_detail(
        word="SHIP IT", seed_text="seed", attempt=0,
    )
    assert variant.kind == "ASCII"
    assert variant.word == "SHIP IT"
    assert variant.text.strip()


def test_mixed_generator_word_override():
    variant = generate_random_mixed_variant_detail(
        word="BUZZ", seed_text="seed", attempt=0,
    )
    assert variant.kind == "Mixed"
    assert variant.word == "BUZZ"


def test_generate_variant_helper_shuffle_changes_output():
    first = art.generate_variant(kind="ASCII", word="BUZZ", seed_text="seed", attempt=0)
    second = art.generate_variant(kind="ASCII", word="BUZZ", seed_text="seed", attempt=1)
    assert first.text != second.text  # a different attempt picks a different font


# ── render + write helpers ──────────────────────────────────
def test_render_master_map_returns_board_header():
    rendered = art.render_master_map("BUZZ")
    assert "\n" in rendered
    # render_header composed the stats box, so we got the real board header,
    # not the bare-map fallback.
    assert "THE BOARD" in rendered


def test_write_board_art_writes_sections(tmp_path: Path):
    variants = [
        art.generate_variant(kind="ASCII", word="BUZZ", seed_text="s", attempt=0),
        art.generate_variant(kind="Mixed", word="BUZZ", seed_text="s", attempt=0),
    ]
    art.write_board_art(tmp_path, "BUZZ", variants)
    content = (tmp_path / ".yoke" / "board-art").read_text(encoding="utf-8")
    assert "## Master Map" in content
    assert "## ASCII" in content
    assert "## Mixed" in content


def test_repo_root_prefers_report_then_fallback(tmp_path: Path):
    report = {"project_onboarding": {"checkout": str(tmp_path)}}
    assert art.repo_root_from_report(report, "/other") == tmp_path
    structured = {"project_onboarding": {"checkout": {"path": str(tmp_path)}}}
    assert art.repo_root_from_report(structured, "/other") == tmp_path
    assert art.repo_root_from_report({}, str(tmp_path)) == tmp_path
    assert art.repo_root_from_report({}, None) is None


def test_preview_rows_shape_by_kind():
    ascii_values = [r.value for r in art.preview_rows("ASCII", is_image=False)]
    assert ascii_values == ["save", "shuffle", "customize", "back"]
    emoji_values = [r.value for r in art.preview_rows("Emoji", is_image=True)]
    assert emoji_values == ["save", "reimage", "back"]  # no shuffle/customize


# ── flow navigation (no Textual loop) ───────────────────────
class _FakeShell(BoardArtFlow):
    """Drives BoardArtFlow without the Textual app: records goto/input/finish."""

    def __init__(self, result: WizardResult) -> None:
        self.result = result
        self.goto_views: list = []
        self.input_calls: list = []
        self.finished = False
        self.exited = False

    def _board_art_view(self, step, builder, on_select):
        return {"step": step, "builder": builder, "on_select": on_select}

    def _selection_view(self, step, title, subtitle, rows, on_select):
        return {"step": step, "title": title, "rows": rows, "on_select": on_select}

    def _goto(self, view):
        self.goto_views.append(view)

    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password=False, allow_placeholder=True):
        self.input_calls.append({"placeholder": placeholder, "on_done": on_done})

    def _goto_finish(self):
        self.finished = True

    def exit(self):
        self.exited = True


def _shell() -> _FakeShell:
    return _FakeShell(WizardResult(
        config_path="cfg", env_name="prod", api_url="https://x",
        project_name="Buzz", project_slug="buzz", project_public_item_prefix="BUZZ",
    ))


def test_flow_intro_seeds_default_word_and_seed():
    shell = _shell()
    shell._goto_board_art_intro()
    assert shell.result.board_art_word == "BUZZ"
    assert shell.result.board_art_seed


def test_flow_save_then_continue_gated_on_one_header():
    shell = _shell()
    shell._goto_board_art_intro()
    shell._on_board_art_intro("design")
    shell._on_board_art_map_preview("continue")
    shell._on_board_art_style("ascii")
    assert shell._art_variant.kind == "ASCII"
    # continue is impossible with zero saved (gallery only reached after a save)
    shell._on_board_art_preview("save")
    assert len(shell.result.board_art_variants) == 1
    shell._on_board_art_gallery("continue")
    assert shell.finished is True


def test_flow_shuffle_increments_attempt():
    shell = _shell()
    shell._goto_board_art_intro()
    shell._on_board_art_style("ascii")
    first = shell._art_variant.text
    shell._on_board_art_preview("shuffle")
    assert shell._art_attempt == 1
    assert shell._art_variant.text != first


def test_flow_customize_text_allows_long_header():
    shell = _shell()
    shell._goto_board_art_intro()
    shell._on_board_art_style("ascii")
    shell._after_board_art_text("Ship It Now")
    assert shell._art_variant.word == "SHIP IT NOW"


def test_flow_edit_master_letters_caps_at_limit():
    shell = _shell()
    shell._goto_board_art_intro()
    shell._after_board_art_map_word("my cool app")
    assert shell.result.board_art_word == "MYCOOLAP"


def test_flow_after_apply_writes_and_shows_payoff(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(art, "rebuild_board", lambda repo_root: None)
    shell = _shell()
    shell._goto_board_art_intro()
    shell._on_board_art_style("ascii")
    shell._on_board_art_preview("save")
    report = {"project_onboarding": {"checkout": str(tmp_path)}}
    assert shell._board_art_after_apply(report) is True
    assert (tmp_path / ".yoke" / "board-art").exists()
    # payoff view was pushed; the wizard did not exit yet.
    assert shell.goto_views and not shell.exited


def test_flow_after_apply_noop_without_variants(tmp_path: Path):
    shell = _shell()
    report = {"project_onboarding": {"checkout": str(tmp_path)}}
    assert shell._board_art_after_apply(report) is False


# ── yoke board shortcut ───────────────────────────────────
def test_board_shortcut_injects_print(monkeypatch):
    from yoke_cli.commands.adapters import board as board_mod

    captured: list = []
    monkeypatch.setattr(board_mod, "board_rebuild", lambda args: captured.append(args) or 0)
    board_mod.board([])
    assert captured == [["--print"]]


def test_board_shortcut_respects_explicit_mode(monkeypatch):
    from yoke_cli.commands.adapters import board as board_mod

    captured: list = []
    monkeypatch.setattr(board_mod, "board_rebuild", lambda args: captured.append(args) or 0)
    board_mod.board(["--json"])
    assert captured == [["--json"]]


def test_board_shortcut_registered_tool_shaped():
    from yoke_cli.commands.tool_shaped import resolve_tool_shaped

    resolved = resolve_tool_shaped(["board"])
    assert resolved is not None

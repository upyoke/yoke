"""Board-art onboarding step: name ladder, generators, flow, and shortcut."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_resolve_word_short_display_name_used_whole():
    assert resolve_project_art_word("ExternalWebapp", slug="externalwebapp", short_code="EXT") == "EXT"


def test_resolve_word_long_name_falls_to_first_word():
    # whole join is too long; the first word fits and is most recognizable.
    assert resolve_project_art_word(
        "External Marketing Platform", slug="external-marketing-platform", short_code="EXT",
    ) == "EXTERNAL"


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


def test_normalize_master_map_word_caps_and_uppercases():
    assert normalize_master_map_word("my cool app") == "MYCOOLAP"  # 9 -> 8
    assert normalize_master_map_word("!!!") == ""


def test_normalize_header_art_word_keeps_spaces_allows_longer():
    out = normalize_header_art_word("External Marketing")
    assert out == "EXTERNAL MARKETING"
    assert len(out) > MAX_ART_WORD_LEN  # header art is not capped at the map limit


def test_ascii_generator_word_override_bypasses_choose_art_word():
    variant = generate_random_ascii_variant_detail(
        word="SHIP IT", seed_text="seed", attempt=0,
    )
    assert variant.kind == "ASCII"
    assert variant.word == "SHIP IT"
    assert variant.text.strip()


def test_mixed_generator_word_override():
    variant = generate_random_mixed_variant_detail(
        word="EXT", seed_text="seed", attempt=0,
    )
    assert variant.kind == "Mixed"
    assert variant.word == "EXT"


def test_generate_variant_helper_shuffle_changes_output():
    first = art.generate_variant(kind="ASCII", word="EXT", seed_text="seed", attempt=0)
    second = art.generate_variant(kind="ASCII", word="EXT", seed_text="seed", attempt=1)
    assert first.text != second.text  # a different attempt picks a different font


def test_render_master_map_returns_board_header():
    rendered = art.render_master_map("EXT")
    assert "\n" in rendered
    # render_header composed the stats box, so we got the real board header,
    # not the bare-map fallback.
    assert "THE BOARD" in rendered


def test_write_board_art_writes_sections(tmp_path: Path):
    variants = [
        art.generate_variant(kind="ASCII", word="EXT", seed_text="s", attempt=0),
        art.generate_variant(kind="Mixed", word="EXT", seed_text="s", attempt=0),
    ]
    art.write_board_art(tmp_path, "EXT", variants)
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


class _FakeShell(BoardArtFlow):
    """Drives BoardArtFlow without the Textual app: records goto/input/finish."""

    def __init__(self, result: WizardResult) -> None:
        self.result = result
        self._history: list = []
        self.goto_views = self._history
        self.input_calls: list = []
        self.finished = False
        self.exited = False

    def _board_art_view(self, step, builder, on_select):
        return {"step": step, "builder": builder, "on_select": on_select}

    def _selection_view(self, step, title, subtitle, rows, on_select):
        return {"step": step, "title": title, "rows": rows, "on_select": on_select}

    def _goto(self, view):
        self._history.append(view)

    def _replace_current(self, view):
        if self._history:
            self._history[-1] = view
        else:
            self._history.append(view)

    def _render_current(self):
        return None

    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password=False, allow_placeholder=True):
        view = {"step": step, "placeholder": placeholder, "on_done": on_done}
        self.input_calls.append(view)
        self._goto(view)

    def _goto_finish(self):
        self.finished = True

    def exit(self):
        self.exited = True


def _shell() -> _FakeShell:
    return _FakeShell(WizardResult(
        config_path="cfg", env_name="prod", api_url="https://x",
        project_name="ExternalWebapp", project_slug="externalwebapp", project_public_item_prefix="EXT",
    ))


def test_flow_intro_seeds_default_word_and_seed():
    shell = _shell()
    shell._goto_board_art_intro()
    assert shell.result.board_art_word == "EXT"
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


def test_flow_repeated_preview_transitions_keep_history_bounded():
    shell = _shell()
    shell._goto_board_art_intro()
    shell._on_board_art_intro("design")
    map_depth = len(shell._history)
    for word in ("First", "Second", "Third"):
        shell._on_board_art_map_preview("edit")
        shell._after_board_art_map_word(word)
    assert len(shell._history) == map_depth

    shell._on_board_art_map_preview("continue")
    shell._on_board_art_style("ascii")
    preview_depth = len(shell._history)

    for _ in range(5):
        shell._on_board_art_preview("shuffle")
    assert len(shell._history) == preview_depth

    for word in ("First", "Second", "Third"):
        shell._on_board_art_preview("customize")
        shell._after_board_art_text(word)
    assert len(shell._history) == preview_depth


def test_flow_image_error_retry_and_back_reuse_real_views(monkeypatch):
    shell = _shell()
    shell._goto_board_art_intro()
    shell._on_board_art_intro("design")
    shell._on_board_art_map_preview("continue")
    style_view = shell._history[-1]
    shell._on_board_art_style("image")
    input_depth = len(shell._history)
    monkeypatch.setattr(
        art, "build_image",
        lambda **_: (_ for _ in ()).throw(ValueError("not an image")),
    )

    for _ in range(4):
        shell._after_board_art_image_path("/tmp/not-an-image")
        assert len(shell._history) == input_depth
        shell._on_board_art_image_error("retry")
        assert len(shell._history) == input_depth

    shell._after_board_art_image_path("/tmp/not-an-image")
    shell._on_board_art_image_error("back")
    assert shell._history[-1] is style_view
    assert len(shell._history) == input_depth - 1


def test_flow_repeated_image_previews_reuse_input_slot(monkeypatch):
    shell = _shell()
    shell._goto_board_art_intro()
    shell._on_board_art_intro("design")
    shell._on_board_art_map_preview("continue")
    style_view = shell._history[-1]
    shell._on_board_art_style("image")
    input_depth = len(shell._history)
    variant = art.generate_variant(
        kind="ASCII", word="EXT", seed_text="seed", attempt=0,
    )
    monkeypatch.setattr(
        art, "build_image", lambda **_: ("Emoji", variant, "🟩"),
    )

    for _ in range(4):
        shell._after_board_art_image_path("/tmp/logo.png")
        assert len(shell._history) == input_depth
        shell._on_board_art_preview("reimage")
        assert len(shell._history) == input_depth

    shell._after_board_art_image_path("/tmp/logo.png")
    shell._on_board_art_preview("back")
    assert shell._history[-1] is style_view


def test_flow_preview_back_and_gallery_another_return_to_style():
    shell = _shell()
    shell._goto_board_art_intro()
    shell._on_board_art_intro("design")
    shell._on_board_art_map_preview("continue")
    style_view = shell._history[-1]

    shell._on_board_art_style("ascii")
    shell._on_board_art_preview("back")
    assert shell._history[-1] is style_view

    shell._on_board_art_style("ascii")
    shell._on_board_art_preview("save")
    shell._on_board_art_gallery("another")
    assert shell._history[-1] is style_view


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

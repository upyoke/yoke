"""Board-art onboarding step: name ladder, generators, flow, and shortcut."""

from __future__ import annotations


import pytest

pytest.importorskip("textual")

from yoke_cli.config.onboard_wizard import WizardResult  # noqa: E402
from yoke_cli.config.onboard_wizard_flow_board_art import BoardArtFlow  # noqa: E402
from yoke_cli.config.setup_run_facts import RunFacts  # noqa: E402
from yoke_contracts.project_contract.board_art import (  # noqa: E402
    MAX_ART_WORD_LEN,
    generate_default_variants,
    MIXED_EMOJI_COLUMNS,
    DEFAULT_VARIANT_MAX_WIDTH,
    generate_random_ascii_variant_detail,
    generate_random_mixed_variant_detail,
    normalize_header_art_word,
    normalize_master_map_word,
    resolve_project_art_word,
)


def test_resolve_word_short_display_name_used_whole():
    assert (
        resolve_project_art_word(
            "ExternalWebapp", slug="externalwebapp", short_code="EXT"
        )
        == "EXT"
    )


def test_resolve_word_long_name_falls_to_first_word():
    # whole join is too long; the first word fits and is most recognizable.
    assert (
        resolve_project_art_word(
            "External Marketing Platform",
            slug="external-marketing-platform",
            short_code="EXT",
        )
        == "EXTERNAL"
    )


def test_resolve_word_acronym_when_every_word_is_long():
    assert (
        resolve_project_art_word(
            "International Business Machines",
            slug="international-business-machines",
            short_code="IBM",
        )
        == "IBM"
    )


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
        word="SHIP IT",
        seed_text="seed",
        attempt=0,
    )
    assert variant.kind == "ASCII"
    assert variant.word == "SHIP IT"
    assert variant.text.strip()


def test_mixed_generator_word_override():
    variant = generate_random_mixed_variant_detail(
        word="EXT",
        seed_text="seed",
        attempt=0,
    )
    assert variant.kind == "Mixed"
    assert variant.word == "EXT"


class _Shell(BoardArtFlow):
    def __init__(self, **kwargs):
        self.result = WizardResult(
            config_path="cfg",
            env_name="prod",
            api_url="https://example.com",
            project_name="ExternalWebapp",
            project_slug="externalwebapp",
            project_public_item_prefix="EXT",
            **kwargs,
        )
        self._run_facts = RunFacts()
        self.hosting_visits = 0

    def _goto_hosting(self):
        self.hosting_visits += 1


def test_prepare_art_goes_directly_to_hosting_with_three_styles():
    shell = _Shell()
    shell._prepare_board_art_and_continue()
    assert shell.hosting_visits == 1
    assert shell.result.board_art_word == "EXT"
    assert shell.result.board_art_seed
    assert [v.kind for v in shell.result.board_art_variants] == [
        "ASCII",
        "Emoji",
        "Mixed",
    ]
    assert all(v.text.strip() for v in shell.result.board_art_variants)


def test_back_navigation_preserves_default_art_and_seed():
    shell = _Shell()
    shell._prepare_board_art_and_continue()
    seed = shell.result.board_art_seed
    variants = shell.result.board_art_variants
    shell._prepare_board_art_and_continue()
    assert shell.hosting_visits == 2
    assert shell.result.board_art_seed == seed
    assert shell.result.board_art_variants is variants


def test_new_setup_chooses_a_new_random_seed():
    first, second = _Shell(), _Shell()
    first._prepare_board_art_and_continue()
    second._prepare_board_art_and_continue()
    assert first.result.board_art_seed != second.result.board_art_seed


def test_default_art_is_reproducible_and_width_bounded():
    from yoke_contracts.project_contract.board_art import _art_visual_width

    first = generate_default_variants("EXT", seed_text="seed")
    assert first == generate_default_variants("EXT", seed_text="seed")
    assert first != generate_default_variants("EXT", seed_text="another seed")
    assert all(_art_visual_width(v.text) <= DEFAULT_VARIANT_MAX_WIDTH for v in first)
    assert first[1].text in [column.strip() for column in MIXED_EMOJI_COLUMNS]
    assert first[0].font != first[2].font
    assert first[1].emoji_index != first[2].emoji_index


def test_seeded_install_art_has_exactly_three_headers(tmp_path):
    from yoke_contracts.project_contract.board_art import render_board_art
    from yoke_contracts.project_contract.board_art.config import parse_art_config

    target = tmp_path / "board-art"
    target.write_text(render_board_art("Acme"), encoding="utf-8")
    config = parse_art_config(str(target))
    assert config.master_map
    assert len(config.ascii_variants) == 1
    assert len(config.emoji_variants) == 1
    assert len(config.mixed_variants) == 1

from pathlib import Path

from yoke_core.api.routing_config import (
    ProcessOfferPolicy,
    config_path_from_db_path,
    load_process_offer_policy,
    load_routing_config,
    normalize_token,
    resolve_execution_lane,
)


def test_normalize_token_rewrites_harness_names():
    assert normalize_token("claude-code") == "claude_code"
    assert normalize_token("Codex Desktop") == "codex_desktop"


def test_load_routing_config_parses_executor_defaults_and_lane_paths(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text(
        "\n".join(
            [
                "executor_default_lane_claude_code=DARIUS",
                "executor_default_lane_codex=ALTMAN",
                "lane_paths_darius=shepherd,advance,conduct,usher",
                "lane_paths_altman=refine,polish",
            ],
        ),
        encoding="utf-8",
    )

    routing = load_routing_config(config_path)

    assert routing.default_lane_for_executor("claude-code") == "DARIUS"
    assert routing.default_lane_for_executor("codex") == "ALTMAN"
    assert routing.default_lane_for_executor("unknown-harness") == "primary"
    assert routing.lane_allowed_paths["DARIUS"] == [
        "shepherd",
        "advance",
        "conduct",
        "usher",
    ]
    assert routing.lane_allowed_paths["ALTMAN"] == ["refine", "polish"]


def test_load_routing_config_normalizes_lane_tokens(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text("lane_paths_altman_review=refine\n", encoding="utf-8")

    routing = load_routing_config(config_path)

    assert routing.lane_allowed_paths["ALTMAN_REVIEW"] == ["refine"]


def test_resolve_execution_lane_prefers_explicit_override(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text("executor_default_lane_codex=ALTMAN\n", encoding="utf-8")
    routing = load_routing_config(config_path)

    assert resolve_execution_lane(
        executor="codex",
        explicit_lane="DARIUS",
        routing_config=routing,
    ) == "DARIUS"
    assert resolve_execution_lane(
        executor="codex",
        explicit_lane=None,
        routing_config=routing,
    ) == "ALTMAN"


def test_resolve_execution_lane_treats_default_as_executor_default(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text("executor_default_lane_claude_code=DARIUS\n", encoding="utf-8")
    routing = load_routing_config(config_path)

    assert resolve_execution_lane(
        executor="claude-code",
        explicit_lane="default",
        routing_config=routing,
    ) == "DARIUS"
    assert resolve_execution_lane(
        executor="claude-code",
        explicit_lane=" DEFAULT ",
        routing_config=routing,
    ) == "DARIUS"


def test_config_path_from_db_path_points_at_sibling_config(tmp_path):
    db_path = tmp_path / "runtime" / "yoke.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("", encoding="utf-8")

    assert config_path_from_db_path(db_path) == Path(tmp_path / "runtime" / "config").resolve()


# wildcard lane resolution + fallback chain ---------------------------------


def test_default_lane_wildcard_resolves_unconfigured_surfaces(tmp_path):
    """Wildcard keys cover every surface that shares a prefix."""
    config_path = tmp_path / "config"
    config_path.write_text(
        "executor_default_lane_claude*=DARIUS\n"
        "executor_default_lane_codex*=ALTMAN\n",
        encoding="utf-8",
    )
    routing = load_routing_config(config_path)
    assert routing.default_lane_for_executor("claude-code") == "DARIUS"
    assert routing.default_lane_for_executor("claude-desktop") == "DARIUS"
    assert routing.default_lane_for_executor("claude-vscode") == "DARIUS"
    assert routing.default_lane_for_executor("claude-cli") == "DARIUS"
    assert routing.default_lane_for_executor("codex") == "ALTMAN"
    assert routing.default_lane_for_executor("codex-desktop") == "ALTMAN"
    assert routing.default_lane_for_executor("codex-vscode") == "ALTMAN"
    assert routing.default_lane_for_executor("codex-cli") == "ALTMAN"


def test_default_lane_exact_key_wins_over_wildcard(tmp_path):
    """A specific override key beats a wildcard default that would also match."""
    config_path = tmp_path / "config"
    config_path.write_text(
        "executor_default_lane_claude*=DARIUS\n"
        "executor_default_lane_claude_vscode=ALTMAN\n",
        encoding="utf-8",
    )
    routing = load_routing_config(config_path)
    assert routing.default_lane_for_executor("claude-vscode") == "ALTMAN"
    # Other claude surfaces still pick up the wildcard default.
    assert routing.default_lane_for_executor("claude-desktop") == "DARIUS"
    assert routing.default_lane_for_executor("claude-code") == "DARIUS"


def test_default_lane_longer_wildcard_prefix_wins(tmp_path):
    """When multiple wildcards match a token, the longest prefix wins."""
    config_path = tmp_path / "config"
    config_path.write_text(
        "executor_default_lane_claude*=DARIUS\n"
        "executor_default_lane_claude_v*=ALTMAN\n",
        encoding="utf-8",
    )
    routing = load_routing_config(config_path)
    assert routing.default_lane_for_executor("claude-vscode") == "ALTMAN"
    assert routing.default_lane_for_executor("claude-desktop") == "DARIUS"


def test_default_lane_wildcard_preserves_star_through_config_loading(tmp_path):
    """A naive normalize that strips ``*`` would store ``claude`` as an exact
    token and miss every actual surface. This regression test pins down that
    failure mode."""
    config_path = tmp_path / "config"
    config_path.write_text("executor_default_lane_claude*=DARIUS\n", encoding="utf-8")
    routing = load_routing_config(config_path)
    # No exact match was stored under ``claude`` — the wildcard form must win.
    assert "claude" not in routing.executor_default_lanes
    assert "claude" in routing.executor_wildcard_lanes
    # Surfaces with a separator after ``claude`` still resolve via wildcard.
    assert routing.default_lane_for_executor("claude-vscode") == "DARIUS"
    assert routing.default_lane_for_executor("claude-code") == "DARIUS"


def test_default_lane_claude_code_remains_valid_exact_token(tmp_path):
    """``claude_code`` still works as a literal exact key, but it is no longer a
    hidden fallback target — sibling surfaces like ``claude-desktop`` must NOT
    inherit from it without a wildcard."""
    config_path = tmp_path / "config"
    config_path.write_text(
        "executor_default_lane_claude_code=DARIUS\n",
        encoding="utf-8",
    )
    routing = load_routing_config(config_path)
    assert routing.default_lane_for_executor("claude-code") == "DARIUS"
    # Without a wildcard, sibling surfaces fall to ``primary`` — there is no
    # implicit fallback from one specific surface to another.
    assert routing.default_lane_for_executor("claude-desktop") == "primary"
    assert routing.default_lane_for_executor("claude-vscode") == "primary"


def test_default_lane_underscore_wildcard_distinguishes_from_bare_prefix(tmp_path):
    """``claude_*`` is more specific than ``claude*``: it requires a separator
    after ``claude`` and must NOT match a hypothetical bare ``claude`` token."""
    config_path = tmp_path / "config"
    config_path.write_text(
        "executor_default_lane_claude*=DARIUS\n"
        "executor_default_lane_claude_*=ALTMAN\n",
        encoding="utf-8",
    )
    routing = load_routing_config(config_path)
    # ``claude_vscode`` has the separator, longer prefix wins.
    assert routing.default_lane_for_executor("claude-vscode") == "ALTMAN"
    # Bare ``claude`` token only matches the shorter wildcard.
    assert routing.default_lane_for_executor("claude") == "DARIUS"


def test_default_lane_malformed_mid_string_wildcard_is_ignored(tmp_path):
    """Mid-string ``*`` is not supported; the line is silently dropped so a
    malformed config cannot crash session offer."""
    config_path = tmp_path / "config"
    config_path.write_text(
        "executor_default_lane_cla*ude=DARIUS\n"
        "executor_default_lane_codex*=ALTMAN\n",
        encoding="utf-8",
    )
    routing = load_routing_config(config_path)
    # The malformed key did not register as a wildcard or as an exact key.
    assert "cla" not in routing.executor_wildcard_lanes
    assert "cla_ude" not in routing.executor_default_lanes
    # The well-formed wildcard still resolves.
    assert routing.default_lane_for_executor("codex-desktop") == "ALTMAN"
    # Tokens that would have matched the malformed key fall through to primary.
    assert routing.default_lane_for_executor("claude-desktop") == "primary"


def test_default_lane_uses_unknown_fallback_for_unrelated_executors(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text(
        "executor_default_lane_claude*=DARIUS\n"
        "executor_default_lane_unknown=ALTMAN\n",
        encoding="utf-8",
    )
    routing = load_routing_config(config_path)
    # Unknown executor with no exact or wildcard match uses the unknown fallback.
    assert routing.default_lane_for_executor("acme-bot") == "ALTMAN"
    assert routing.default_lane_for_executor("mystery") == "ALTMAN"


def test_default_lane_returns_primary_when_no_keys_match(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text("", encoding="utf-8")  # no executor keys at all
    routing = load_routing_config(config_path)
    # Nothing configured; the sentinel lane remains available.
    assert routing.default_lane_for_executor("claude-desktop") == "primary"
    assert routing.default_lane_for_executor("codex-cli") == "primary"
    assert routing.default_lane_for_executor("acme-bot") == "primary"


def test_default_lane_unknown_key_only_fires_when_no_exact_or_wildcard_match(tmp_path):
    """Synthetic unknown executor exercises unknown and primary fallback paths."""
    config_with_unknown = tmp_path / "with-unknown"
    config_with_unknown.write_text("executor_default_lane_unknown=DARIUS\n", encoding="utf-8")
    routing_with = load_routing_config(config_with_unknown)
    assert routing_with.default_lane_for_executor("acme-bot") == "DARIUS"

    config_without_unknown = tmp_path / "without-unknown"
    config_without_unknown.write_text("", encoding="utf-8")
    routing_without = load_routing_config(config_without_unknown)
    assert routing_without.default_lane_for_executor("acme-bot") == "primary"


# Process-offer policy

def test_process_offer_policy_default_disabled_when_config_empty(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text("", encoding="utf-8")
    policy = load_process_offer_policy(config_path)
    assert isinstance(policy, ProcessOfferPolicy)
    assert policy.default_enabled is False
    assert policy.is_enabled("STRATEGIZE") is False
    assert policy.is_enabled("FEED") is False
    assert policy.is_enabled("DOCTOR") is False


def test_process_offer_policy_per_process_overrides_default(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text(
        "\n".join(
            [
                "do_process_offer_default=true",
                "do_process_offer_strategize=false",
                "do_process_offer_feed=false",
                "do_process_offer_doctor=true",
            ],
        ),
        encoding="utf-8",
    )
    policy = load_process_offer_policy(config_path)
    assert policy.default_enabled is True
    assert policy.is_enabled("STRATEGIZE") is False
    assert policy.is_enabled("FEED") is False
    assert policy.is_enabled("DOCTOR") is True


def test_process_offer_policy_unknown_process_falls_back_to_default(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text(
        "do_process_offer_default=true\n",
        encoding="utf-8",
    )
    policy = load_process_offer_policy(config_path)
    # A future process key with no explicit override inherits the default.
    assert policy.is_enabled("FUTURE_PROCESS") is True


def test_process_offer_policy_invalid_value_falls_back_to_false(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text(
        "\n".join(
            [
                "do_process_offer_default=maybe",
                "do_process_offer_strategize=truthy_typo",
                "do_process_offer_feed=disabled",
            ],
        ),
        encoding="utf-8",
    )
    policy = load_process_offer_policy(config_path)
    # Garbage default and per-process values fall back to ``False`` so a
    # config typo cannot silently flip an autonomy gate on.
    assert policy.default_enabled is False
    assert policy.is_enabled("STRATEGIZE") is False
    assert policy.is_enabled("FEED") is False


def test_process_offer_policy_normalizes_process_key_case(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text(
        "do_process_offer_strategize=true\n",
        encoding="utf-8",
    )
    policy = load_process_offer_policy(config_path)
    # Callers may pass the registry-canonical upper-case form; the policy
    # case-folds internally so STRATEGIZE / strategize / Strategize all work.
    assert policy.is_enabled("STRATEGIZE") is True
    assert policy.is_enabled("strategize") is True
    assert policy.is_enabled("Strategize") is True


def test_process_offer_policy_config_key_for_process(tmp_path):
    policy = ProcessOfferPolicy()
    assert policy.config_key_for("STRATEGIZE") == "do_process_offer_strategize"
    assert policy.config_key_for("Feed") == "do_process_offer_feed"
    assert policy.config_key_for("doctor") == "do_process_offer_doctor"


def test_process_offer_policy_recognized_truthy_falsy_strings(tmp_path):
    config_path = tmp_path / "config"
    config_path.write_text(
        "\n".join(
            [
                "do_process_offer_strategize=YES",
                "do_process_offer_feed=Off",
                "do_process_offer_doctor=1",
            ],
        ),
        encoding="utf-8",
    )
    policy = load_process_offer_policy(config_path)
    assert policy.is_enabled("STRATEGIZE") is True
    assert policy.is_enabled("FEED") is False
    assert policy.is_enabled("DOCTOR") is True

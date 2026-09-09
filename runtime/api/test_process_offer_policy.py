"""Coverage for the ``/yoke do`` process-offer policy and chain budget.

Split from the routing-config tests alongside the module itself: where a
session runs and whether an autonomous loop may dispatch a process at
all are separate questions that happen to read the same two scopes.
"""

from yoke_core.api.process_offer_policy import (
    ProcessOfferPolicy,
    load_process_offer_policy,
)


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

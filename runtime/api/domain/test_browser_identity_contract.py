"""Browser identity declarations, names, paths and QA method configuration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.browser_identity import (
    DEFAULT_IDENTITY,
    BrowserIdentityError,
    case_browser_identity,
    live_identity_store_relative_path,
    mission_browser_identities,
    parse_identity_declarations,
    select_identity,
    validate_identity_name,
)
from yoke_contracts.machine_config.capability_secrets import (
    browser_profile_relative_path,
)
from yoke_core.domain.agent_mission_browser_identities import walker_identity_dispatch
from yoke_core.domain.qa_method_config_validation import (
    QaMethodConfigError,
    validate_method_config,
)

BUYER = {
    "sites": [
        {
            "site": "google",
            "origin": "https://accounts.google.com",
            "account": "buyer@example.com",
            "probe": {
                "url": "https://myaccount.google.com/",
                "signed_in_selector": "#me",
            },
        },
        {
            "site": "shop",
            "origin": "https://shop.example.com",
            "probe": {
                "url": "https://shop.example.com/api/me",
                "signed_in_status": 200,
            },
        },
    ]
}


def test_a_project_declaring_nothing_has_only_the_default_identity():
    identities = parse_identity_declarations({})
    assert list(identities) == [DEFAULT_IDENTITY]
    assert identities[DEFAULT_IDENTITY].sites == ()
    assert select_identity(identities, None).name == DEFAULT_IDENTITY


def test_identities_take_arbitrary_names_with_their_own_sites():
    identities = parse_identity_declarations(
        {"identities": {"buyer": BUYER, "night-auditor": {"sites": []}}}
    )
    assert set(identities) == {DEFAULT_IDENTITY, "buyer", "night-auditor"}
    google, shop = identities["buyer"].sites
    assert google.account == "buyer@example.com"
    assert google.as_probe() == {
        "site": "google",
        "url": "https://myaccount.google.com/",
        "signed_in_selector": "#me",
    }
    assert shop.as_probe()["signed_in_status"] == 200


@pytest.mark.parametrize(
    "body, reason",
    [
        (
            {
                "sites": [
                    {"site": "x", "origin": "https://x", "probe": {"url": "https://x"}}
                ]
            },
            "exactly one",
        ),
        (
            {
                "sites": [
                    {
                        "site": "x",
                        "origin": "ftp://x",
                        "probe": {"url": "https://x", "signed_in_status": 200},
                    }
                ]
            },
            "absolute",
        ),
        (
            {
                "sites": [
                    {
                        "site": "x",
                        "origin": "https://x",
                        "probe": {"url": "https://x", "signed_in_status": 9},
                    }
                ]
            },
            "HTTP status",
        ),
        ({"sites": [{**BUYER["sites"][0]}, {**BUYER["sites"][0]}]}, "second identity"),
        ({"sites": [], "extra": 1}, "only key is sites"),
    ],
)
def test_malformed_declarations_refuse_with_the_location(body, reason):
    with pytest.raises(BrowserIdentityError, match=reason):
        parse_identity_declarations({"identities": {"buyer": body}})


@pytest.mark.parametrize("name", ["", "Admin", "-x", "a" * 41, "../up", "x y"])
def test_identity_names_are_safe_path_components(name):
    with pytest.raises(BrowserIdentityError, match="browser_identity_name_invalid"):
        validate_identity_name(name)


def test_an_undeclared_identity_refuses_naming_the_declared_ones():
    identities = parse_identity_declarations({"identities": {"buyer": BUYER}})
    with pytest.raises(
        BrowserIdentityError, match="browser_identity_undeclared.*buyer, default"
    ):
        select_identity(identities, "admin")


def test_each_identity_has_its_own_profile_and_default_keeps_the_original_path():
    default = browser_profile_relative_path("acme")
    assert default == Path("capability-secrets/acme/browser-control/profile")
    assert browser_profile_relative_path("acme", "admin") == Path(
        "capability-secrets/acme/browser-control/identities/admin/profile"
    )
    assert browser_profile_relative_path(
        "acme", "member"
    ) != browser_profile_relative_path("acme", "admin")
    assert str(live_identity_store_relative_path("acme", "admin")) == (
        ".yoke-browser-identities/acme/admin"
    )


def test_browser_cases_and_missions_name_their_identities():
    assert case_browser_identity({}) == DEFAULT_IDENTITY
    assert case_browser_identity({"browser_identity": "admin"}) == "admin"
    assert mission_browser_identities({"browser_identities": ["member", "admin"]}) == [
        "member",
        "admin",
    ]
    with pytest.raises(BrowserIdentityError, match="twice"):
        mission_browser_identities({"browser_identities": ["admin", "admin"]})


def test_method_config_validation_accepts_and_refuses_identities():
    steps = [
        {"action": "navigate", "route": "/"},
        {"action": "screenshot", "capture": True, "label": "home"},
    ]
    config = validate_method_config(
        "browser-inspection", {"steps": steps, "browser_identity": "admin"}
    )
    assert config["browser_identity"] == "admin"
    with pytest.raises(QaMethodConfigError, match="browser_identity_name_invalid"):
        validate_method_config(
            "browser-inspection", {"steps": steps, "browser_identity": "A"}
        )
    mission = validate_method_config(
        "agent-mission",
        {"executor": "informed_subagent", "browser_identities": ["member", "admin"]},
    )
    assert mission["browser_identities"] == ["member", "admin"]
    with pytest.raises(QaMethodConfigError, match="browser_identities_invalid"):
        validate_method_config(
            "agent-mission",
            {"executor": "informed_subagent", "browser_identities": "x"},
        )


def test_walker_dispatch_verifies_each_named_identity_before_browsing():
    base = (
        "yoke qa mission host-command --item YOK-1 --execution-id 9 --requirement-id 3"
    )
    identities, commands, clause = walker_identity_dispatch(
        {"method_config": {"browser_identities": ["member", "admin"]}}, base
    )
    assert identities == ["member", "admin"]
    assert commands == [
        f"{base} -- yoke browser verify --project PROJECT --identity member "
        "--declarations-json DECLARATIONS_JSON --json",
        f"{base} -- yoke browser verify --project PROJECT --identity admin "
        "--declarations-json DECLARATIONS_JSON --json",
    ]
    assert "HUMAN_GATE" in clause and "--identity NAME" in clause
    assert walker_identity_dispatch({"method_config": {}}, base) == ([], [], "")


def test_browser_control_settings_refuse_a_malformed_identity_on_write():
    from yoke_core.domain.projects_capability_settings_validation import (
        canonicalize_capability_settings,
    )

    good = '{"identities": {"buyer": ' + json.dumps(BUYER) + "}}"
    assert "buyer" in canonicalize_capability_settings("browser-control", good)
    assert canonicalize_capability_settings("browser-control", "{}") == "{}"
    with pytest.raises(BrowserIdentityError, match="browser_identity_name_invalid"):
        canonicalize_capability_settings(
            "browser-control", '{"identities": {"Bad Name": {"sites": []}}}'
        )

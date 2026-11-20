"""Setup's item-prefix default skips taken prefixes and refuses a taken one."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_cli.config import (
    existing_project_lookup,
    onboard_preflight,
    onboard_project,
    onboard_project_prefixes as prefixes,
    onboard_wizard_project_details as project_details,
)
from yoke_contracts.onboard_destinations import DESTINATION_LOCAL

RETIRED = "project 'qa-nw-accept-old' (id 65) (retired)"


def _list_response(*rows: dict) -> dict:
    return {"success": True, "result": {"fields": [], "rows": list(rows)}}


def test_holders_name_each_project_and_mark_retired_ones() -> None:
    holders = prefixes.holders_from_response(
        _list_response(
            {"id": 65, "slug": "qa-nw-accept-old", "public_item_prefix": "qanwac",
             "retired_at": "2026-11-01T00:00:00Z"},
            {"id": 3, "slug": "yoke", "public_item_prefix": "YOK", "retired_at": None},
        )
    )

    assert holders == {"QANWAC": RETIRED, "YOK": "project 'yoke' (id 3)"}


def test_holders_are_unknown_when_the_list_read_fails() -> None:
    assert prefixes.holders_from_response({"success": False}) is None
    assert prefixes.holders_from_response({"success": True, "result": {}}) is None


def test_proposal_skips_taken_prefixes_including_retired() -> None:
    assert prefixes.propose("qa-nw-accept-2", None) == "QANWAC"
    assert prefixes.propose("qa-nw-accept-2", {"QANWAC": RETIRED}) == "QANWA2"
    taken = {"QANWAC": RETIRED, "QANWA2": "project 'b' (id 66)"}
    assert prefixes.propose("qa-nw-accept-3", taken) == "QANWA3"
    assert prefixes.propose("ab", {"AB": "x", "AB2": "y"}) == "AB3"


def test_proposal_falls_back_to_a_valid_free_prefix() -> None:
    assert prefixes.propose("7", None) == "PRJ"
    assert prefixes.propose("9lives", {"PRJ": "project 'p' (id 1)"}) == "PRJ2"


def test_details_form_proposes_a_free_prefix_and_refuses_a_taken_one() -> None:
    fields = project_details.fields(
        slug="qa-nw-accept-2",
        branch_from_source="main",
        holders={"QANWAC": RETIRED},
    )
    prefix = next(field for field in fields if field.key == "prefix")

    assert prefix.initial_value == "QANWA2"
    assert prefix.validate("qanwac") == (
        f"Item prefix QANWAC is already used by {RETIRED}. Choose another prefix."
    )
    assert prefix.validate("QANWA2") is None
    assert prefix.validate("1BAD") is not None


def _new_project(prefix: str) -> SimpleNamespace:
    return SimpleNamespace(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=None,
        project_public_item_prefix=prefix,
        existing_project_id=None,
        destination="hosted",
    )


def test_review_refuses_a_taken_prefix_naming_its_project() -> None:
    probes = onboard_preflight.PreflightProbes(
        prefix_holders=lambda: {"QANWAC": RETIRED}
    )

    problems = onboard_preflight.preflight(_new_project("QANWAC"), probes=probes).problems

    assert (
        f"Item prefix QANWAC is already used by {RETIRED}. Go back to Project "
        "details and choose another prefix."
    ) in problems
    assert not any(
        "Item prefix" in problem
        for problem in onboard_preflight.preflight(
            _new_project("QANWA2"), probes=probes
        ).problems
    )


def test_review_skips_the_prefix_check_for_an_existing_project() -> None:
    result = _new_project("QANWAC")
    result.existing_project_id = 65
    probes = onboard_preflight.PreflightProbes(
        prefix_holders=lambda: {"QANWAC": RETIRED}
    )

    assert not any(
        "Item prefix" in problem
        for problem in onboard_preflight.preflight(result, probes=probes).problems
    )


def test_local_destination_reads_retired_projects_from_the_local_universe(
    monkeypatch,
) -> None:
    calls: list[dict] = []

    def fake_call(**kwargs):
        calls.append(kwargs)
        return _list_response(
            {"id": 65, "slug": "qa-nw-accept-old", "public_item_prefix": "QANWAC",
             "retired_at": "2026-11-01T00:00:00Z"}
        )

    monkeypatch.setattr(existing_project_lookup, "_call_local_function", fake_call)
    result = SimpleNamespace(destination=DESTINATION_LOCAL, config_path="/cfg")

    assert prefixes.read_holders(result, lambda: None) == {"QANWAC": RETIRED}
    assert calls[0]["function"] == "projects.list"
    assert calls[0]["payload"]["include_retired"] is True


def test_hosted_read_is_unknown_without_a_token_or_on_failure(monkeypatch) -> None:
    result = SimpleNamespace(destination="hosted", api_url="https://example.test")

    assert prefixes.read_holders(result, lambda: None) is None

    def failing(**_kwargs):
        raise existing_project_lookup.ExistingProjectLookupError("offline")

    monkeypatch.setattr(prefixes, "call_function", failing)
    assert prefixes.read_holders(result, lambda: "token") is None

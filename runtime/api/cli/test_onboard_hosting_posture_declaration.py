"""Declaring that Yoke manages no host, and that declaration surviving apply.

Skipping and declaring are different answers to the same question, and the
difference has to hold all the way from the wizard row to the project row:
the wizard offers the declaration wherever it offers a skip, choosing it
collects no credential, apply writes the singleton family entry, and deciding
later writes nothing at all so onboarding knows to ask again.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_apply_hosting_posture  # noqa: E402
from yoke_cli.config import onboard_plan_labels  # noqa: E402
from yoke_cli.config import onboard_wizard_hosting_steps as hosting_steps  # noqa: E402
from yoke_contracts import hosting_posture  # noqa: E402

from runtime.api.cli.onboard_wizard_hosting_support import (  # noqa: E402,F401
    _isolated_machine_home,
    _stub_path_doctor,
    body_text,
    drive,
    reach_connect_screen,
    seed_project,
)
from runtime.api.cli.onboard_wizard_test_helpers import make_app  # noqa: E402


DECLARED_ROW = "no-managed-host"


# --------------------------------------------------------------------------- #
# The row is reachable from every screen that offers a skip
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "rows",
    [
        hosting_steps.HOSTING_CONNECT_ROWS,
        hosting_steps.HOSTING_RETRY_ROWS,
        hosting_steps.HOSTING_UNVERIFIED_ROWS,
    ],
    ids=["connect", "retry", "unverified"],
)
def test_every_skippable_screen_also_offers_the_declaration(rows) -> None:
    """Wherever an operator can defer, they can also tell the truth instead."""
    keys = [row.key for row in rows]
    assert DECLARED_ROW in keys
    assert "skip" in keys


def test_the_subtitle_does_not_present_aws_as_the_only_world() -> None:
    """"AWS for now" read as "AWS eventually", which was never the offer."""
    subtitle = hosting_steps.HOSTING_CONNECT_SUBTITLE
    assert "AWS" in subtitle
    assert "yourself" in subtitle


# --------------------------------------------------------------------------- #
# Choosing it collects nothing and settles the answer
# --------------------------------------------------------------------------- #


def test_declaring_reaches_a_screen_that_asks_for_no_credential() -> None:
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await reach_connect_screen(a, pilot)
        a._on_hosting_choice(DECLARED_ROW)
        await pilot.pause()

    screen = drive(app, action)
    assert hosting_steps.HOSTING_NO_MANAGED_HOST_TITLE in screen
    assert "Access key ID" not in screen
    assert "Secret access key" not in screen


def test_declaring_records_the_posture_and_the_optional_provider_note() -> None:
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await reach_connect_screen(a, pilot)
        a._on_hosting_choice(DECLARED_ROW)
        await pilot.pause()
        a._after_no_managed_host_note({
            hosting_steps.HOSTING_PROVIDER_NOTE_FIELD.key: "  Render  ",
        })
        await pilot.pause()

    drive(app, action)
    assert app.result.hosting_choice == (
        hosting_posture.POSTURE_NO_YOKE_MANAGED_HOST
    )
    assert app.result.hosting_provider_note == "Render"
    assert app.result.hosting_verification is None


def test_an_empty_provider_note_stays_absent_rather_than_blank() -> None:
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await reach_connect_screen(a, pilot)
        a._after_no_managed_host_note({
            hosting_steps.HOSTING_PROVIDER_NOTE_FIELD.key: "   ",
        })
        await pilot.pause()

    drive(app, action)
    assert app.result.hosting_provider_note is None


def test_deciding_later_stays_undecided_and_names_no_provider() -> None:
    """Skip must not masquerade as a declaration; the two drive different work."""
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await reach_connect_screen(a, pilot)
        a._on_hosting_choice("skip")
        await pilot.pause()

    drive(app, action)
    assert app.result.hosting_choice == hosting_posture.POSTURE_UNDECIDED
    assert app.result.hosting_provider_note is None


def test_backing_out_returns_to_the_connect_screen() -> None:
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await reach_connect_screen(a, pilot)
        a._on_hosting_choice(DECLARED_ROW)
        await pilot.pause()
        a._on_no_managed_host_choice("back")
        await pilot.pause()

    assert hosting_steps.HOSTING_CONNECT_TITLE in drive(app, action)


# --------------------------------------------------------------------------- #
# The declaration survives apply as a project row
# --------------------------------------------------------------------------- #


def test_a_declared_posture_becomes_a_singleton_family_put(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        onboard_apply_hosting_posture,
        "call_dispatcher",
        lambda **kwargs: calls.append(kwargs) or _ok_response(),
    )
    result = onboard_apply_hosting_posture.record(
        project="acme-app",
        posture=hosting_posture.POSTURE_NO_YOKE_MANAGED_HOST,
        provider_note="Render",
    )
    assert result == {}
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload["project_id"] == "acme-app"
    assert payload["ops"] == [{
        "op": "put",
        "family": hosting_posture.HOSTING_POSTURE_FAMILY,
        "attachment": "project",
        "payload": {
            "posture": hosting_posture.POSTURE_NO_YOKE_MANAGED_HOST,
            "provider": "Render",
        },
    }]


def test_re_running_the_same_answer_is_the_same_put(monkeypatch) -> None:
    """A singleton put converges, so a second wizard run must not conflict."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        onboard_apply_hosting_posture,
        "call_dispatcher",
        lambda **kwargs: calls.append(kwargs) or _ok_response(),
    )
    for _ in range(2):
        onboard_apply_hosting_posture.record(
            project="acme-app",
            posture=hosting_posture.POSTURE_NO_YOKE_MANAGED_HOST,
        )
    assert calls[0]["payload"] == calls[1]["payload"]
    assert "provider" not in calls[0]["payload"]["ops"][0]["payload"]


def test_undecided_writes_nothing_at_all(monkeypatch) -> None:
    """Absence is how "not answered" is stored, so there is nothing to write."""
    def _refuse(**_kwargs):
        raise AssertionError("undecided must not reach the dispatcher")

    monkeypatch.setattr(
        onboard_apply_hosting_posture, "call_dispatcher", _refuse,
    )
    assert onboard_apply_hosting_posture.record(
        project="acme-app", posture=hosting_posture.POSTURE_UNDECIDED,
    ) is None


# --------------------------------------------------------------------------- #
# The review plan says what each answer actually does
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "posture, expected",
    [
        (hosting_posture.POSTURE_YOKE_MANAGED_AWS, "AWS hosting credential"),
        (hosting_posture.POSTURE_NO_YOKE_MANAGED_HOST, "manages no host"),
        (hosting_posture.POSTURE_UNDECIDED, "later"),
    ],
)
def test_the_review_line_matches_the_answer(posture, expected) -> None:
    line = onboard_plan_labels.friendly_line(
        hosting_posture.HOSTING_POSTURE_ACTION, posture,
    )
    assert expected in line


def test_only_the_aws_answer_promises_a_credential() -> None:
    """A declaration writes no secret, so its line must not claim one."""
    declared = onboard_plan_labels.friendly_line(
        hosting_posture.HOSTING_POSTURE_ACTION,
        hosting_posture.POSTURE_NO_YOKE_MANAGED_HOST,
    )
    assert "credential" not in declared.lower()


def test_the_posture_vocabulary_has_exactly_one_home() -> None:
    """Two spellings of one value is how the wizard and the engine drift."""
    from pathlib import Path

    repo = Path(__file__).resolve()
    while not (repo / "pyproject.toml").exists():
        repo = repo.parent
    contracts = (
        repo / "packages/yoke-contracts/src/yoke_contracts/hosting_posture.py"
    )
    offenders = [
        str(candidate.relative_to(repo))
        for candidate in repo.glob("packages/**/*.py")
        if candidate != contracts
        and "install_bundle_tree" not in candidate.parts
        and "no-yoke-managed-host" in candidate.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "posture literals belong only in yoke_contracts.hosting_posture; "
        f"found in {offenders}"
    )


def _ok_response():
    class _Response:
        success = True
        error = None
        result: dict[str, Any] = {}

    return _Response()

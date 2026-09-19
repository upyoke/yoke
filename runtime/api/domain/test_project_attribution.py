"""Resolving a project argument, and refusing to invent one."""

from __future__ import annotations

import pytest

from yoke_core.domain import project_attribution as attribution


@pytest.fixture
def unbound_checkout(tmp_path):
    """A directory the machine config binds to no project."""
    return tmp_path / "somebody-elses-checkout"


def test_an_explicit_project_wins(unbound_checkout) -> None:
    assert (
        attribution.resolved_project("acme", checkout=unbound_checkout) == "acme"
    )


def test_an_explicit_project_id_is_kept(unbound_checkout) -> None:
    assert attribution.resolved_project(7, checkout=unbound_checkout) == "7"


def test_an_unbound_checkout_resolves_to_nothing(unbound_checkout) -> None:
    """Never a compiled-in slug: that is the silent misattribution."""
    assert (
        attribution.resolved_project(None, checkout=unbound_checkout)
        == attribution.UNATTRIBUTED
    )


def test_blank_is_the_same_as_absent(unbound_checkout) -> None:
    assert (
        attribution.resolved_project("   ", checkout=unbound_checkout)
        == attribution.UNATTRIBUTED
    )


def test_required_refuses_and_names_both_answers(unbound_checkout) -> None:
    with pytest.raises(attribution.UnattributedProjectError) as excinfo:
        attribution.required_project(
            None, operation="recording a lane head", checkout=unbound_checkout
        )

    message = str(excinfo.value)
    assert "recording a lane head" in message
    assert str(unbound_checkout) in message
    assert "yoke project register" in message


def test_required_returns_what_it_resolved(unbound_checkout) -> None:
    assert (
        attribution.required_project(
            "acme", operation="syncing labels", checkout=unbound_checkout
        )
        == "acme"
    )


def test_nothing_is_inferred_from_the_working_directory() -> None:
    """A row's project is not answered by wherever the process is running."""
    assert attribution.resolved_project(None) == attribution.UNATTRIBUTED

    with pytest.raises(attribution.UnattributedProjectError) as excinfo:
        attribution.required_project(None, operation="reading an epic")

    assert "reading an epic" in str(excinfo.value)

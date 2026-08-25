"""Tests for carrying an explicit ``--session-id`` across one invocation."""

from __future__ import annotations

import os

import pytest

from yoke_cli.session_id_propagation import (
    SESSION_ID_ENV_VAR,
    explicit_session_id,
    propagated_session_identity,
)


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["merge", "item", "YOK-1", "--session-id", "abc"], "abc"),
        (["merge", "item", "--session-id=abc"], "abc"),
        (["merge", "item", "YOK-1"], None),
        (["merge", "item", "--session-id"], None),
        (["merge", "item", "--session-id", ""], None),
        (["merge", "item", "--session-id", "--json"], None),
    ],
)
def test_explicit_session_id_reads_both_argparse_spellings(
    argv: list[str],
    expected: str | None,
) -> None:
    assert explicit_session_id(argv) == expected


def test_flags_after_a_bare_separator_belong_to_the_wrapped_command() -> None:
    """``yoke watch pytest -- ...`` forwards flags Yoke must not interpret."""
    assert (
        explicit_session_id(["watch", "pytest", "--", "-k", "--session-id", "not-ours"])
        is None
    )


def test_override_reaches_downstream_resolution_then_is_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The nested half of a delegating command re-resolves identity, and
    used to find nothing because the flag reached only the first parser."""
    from yoke_core.domain.session_ambient_identity import (
        resolve_ambient_session_id,
    )

    monkeypatch.delenv(SESSION_ID_ENV_VAR, raising=False)

    with propagated_session_identity(["merge", "item", "--session-id", "op"]):
        assert os.environ[SESSION_ID_ENV_VAR] == "op"
        assert resolve_ambient_session_id() == "op"

    assert SESSION_ID_ENV_VAR not in os.environ


def test_a_preexisting_stamp_is_restored_not_clobbered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SESSION_ID_ENV_VAR, "ambient")

    with propagated_session_identity(["x", "--session-id", "override"]):
        assert os.environ[SESSION_ID_ENV_VAR] == "override"

    assert os.environ[SESSION_ID_ENV_VAR] == "ambient"


def test_no_override_leaves_the_environment_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SESSION_ID_ENV_VAR, "ambient")

    with propagated_session_identity(["items", "get", "YOK-1"]) as propagated:
        assert propagated is None
        assert os.environ[SESSION_ID_ENV_VAR] == "ambient"


@pytest.mark.parametrize(
    "argv",
    [
        # Landed the GitHub merge, then refused the evidence write with
        # actor_session_missing — twice observed, on two separate items.
        ["merge", "item", "YOK-1", "--session-id", "op", "--result", "r"],
        ["direct-workflow", "dash", "evidence", "YOK-1", "--session-id", "op"],
    ],
)
def test_every_observed_nested_write_site_carries_the_override(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both reported failures were a delegating command whose second half
    re-resolved identity somewhere the flag had never reached."""
    from yoke_core.domain.session_ambient_identity import (
        resolve_ambient_session_id,
    )

    monkeypatch.delenv(SESSION_ID_ENV_VAR, raising=False)

    with propagated_session_identity(argv):
        assert resolve_ambient_session_id() == "op"


def test_the_stamped_variable_heads_the_canonical_ambient_chain() -> None:
    from yoke_contracts.session_identity import AMBIENT_ENV_VARS

    assert AMBIENT_ENV_VARS[0] == SESSION_ID_ENV_VAR

"""Unit coverage for the machine-GitHub connect-success detail copy.

The connect-success screen reports, in one line, where the token can push:
the existing repos it can write to plus whether it can also publish a brand-new
repo (create AND push). The "create the repo on GitHub first" remedy is deferred
to the publish step, so it is deliberately absent here. The line is honest for
both classic and fine-grained PATs — fine-grained push comes from non-mutating
probes, classic from X-OAuth-Scopes. These pin the copy at the function seam so
the wording can't silently regress under the SVG goldens.
"""

from __future__ import annotations

from yoke_cli.config.onboard_wizard_flow_github import (
    _detail_lines,
    _push_capability_line,
)


def _classic_publish_capability() -> dict:
    return {
        "kind": "classic",
        "can_create": True,
        "create_private": True,
        "can_push_new": True,
        "can_publish": True,
        "writable": ["me/a", "me/b"],
        "readonly": [],
        "see_private": 1,
        "see_public": 1,
        "write_probed_count": 0,
        "write_probe_total": 0,
    }


# --------------------------------------------------------------------------- #
# Combined push line
# --------------------------------------------------------------------------- #


def test_push_line_fine_grained_select_repositories() -> None:
    # The user's real case: can push to a granted repo, not to new repos.
    cap = {
        "kind": "fine_grained", "can_publish": False,
        "writable": ["machine-user/buzz"], "readonly": [],
        "see_private": 1, "see_public": 0,
        "write_probed_count": 1, "write_probe_total": 1,
    }
    assert _push_capability_line(cap) == (
        "Can push to machine-user/buzz, but not to new repos."
    )


def test_push_line_classic_all_and_new() -> None:
    assert _push_capability_line(_classic_publish_capability()) == (
        "Can push to all 2 repos you can see, and to new repos."
    )


def test_push_line_classic_except_readonly() -> None:
    cap = _classic_publish_capability() | {"readonly": ["org/ro"], "see_private": 2}
    assert _push_capability_line(cap) == (
        "Can push to all 3 you can see except org/ro, and to new repos."
    )


def test_push_line_classic_except_counts_readonly_from_total() -> None:
    # ``readonly`` is a display sample capped upstream, so the "and N more" tail
    # must count from ``readonly_count`` — else the "except" list understates the
    # reader-only repos and over-promises push access.
    cap = _classic_publish_capability() | {
        "readonly": ["org/r1", "org/r2", "org/r3", "org/r4", "org/r5"],
        "readonly_count": 30,
        "see_private": 40,
    }
    assert _push_capability_line(cap) == (
        "Can push to all 41 you can see except "
        "org/r1, org/r2, org/r3, org/r4, and 26 more, and to new repos."
    )


def test_push_line_classic_public_only() -> None:
    cap = {"kind": "classic", "create_private": False, "can_publish": True}
    assert _push_capability_line(cap) == (
        "Can push to public repos you can see, and to new repos."
    )


def test_push_line_no_existing_cannot_publish() -> None:
    cap = {"kind": "fine_grained", "writable": [], "can_publish": False}
    assert _push_capability_line(cap) == (
        "Can't push to any of the repos checked with this token."
    )


def test_push_line_no_existing_can_publish() -> None:
    cap = {"kind": "fine_grained", "writable": [], "can_publish": True}
    assert _push_capability_line(cap) == "Can push to new repos you create."


def test_push_line_unknown_publish() -> None:
    cap = {"kind": "fine_grained", "writable": ["me/a"], "can_publish": None}
    assert _push_capability_line(cap) == "Can push to me/a."


# --------------------------------------------------------------------------- #
# Full detail block
# --------------------------------------------------------------------------- #


def test_detail_lines_classic_renders_push_line() -> None:
    verification = {
        "identity": {"login": "machine-user"},
        "access": {
            "owners": ["machine-user", "octo-org"],
            "repos": ["machine-user/private-tool", "octo-org/app"],
        },
        "scopes": ["repo", "workflow"],
        "capability": _classic_publish_capability(),
    }
    lines = _detail_lines(verification)
    joined = " ".join(lines)
    assert any(line.startswith("Repos this token can see:") for line in lines)
    assert "(1 private, 1 public)" in joined
    assert "Can push to all 2 repos you can see, and to new repos." in lines
    # The old verbose create/publish lines and the deferred remedy are gone.
    assert "Create new repos" not in joined
    assert "create the repo on github first" not in joined.lower()


def test_detail_lines_fine_grained_select_repositories() -> None:
    """The user's real case: can push to buzz, not to new repos — one line."""
    verification = {
        "identity": {"login": "machine-user"},
        "access": {"owners": ["machine-user"], "repos": ["machine-user/buzz"]},
        "capability": {
            "kind": "fine_grained",
            "can_create": True,
            "create_private": None,
            "can_push_new": False,
            "can_publish": False,
            "writable": ["machine-user/buzz"],
            "readonly": [],
            "see_private": 1,
            "see_public": 0,
            "write_probed_count": 1,
            "write_probe_total": 1,
        },
    }
    lines = _detail_lines(verification)
    assert "Can push to machine-user/buzz, but not to new repos." in lines
    assert "Create new repos" not in " ".join(lines)

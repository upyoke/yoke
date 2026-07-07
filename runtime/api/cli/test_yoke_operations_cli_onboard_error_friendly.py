"""Unit coverage for the onboarding permission-error friendlify helper.

The control plane raises terse authorization errors (``actor N lacks 'PERM' on
org M`` / ``on project M``) and, once the name-bearing server build ships, the
``on org 'NAME' (id M)`` form. ``friendly_permission_error`` rewrites all of
them into one actionable sentence and leaves every other error untouched. These
tests pin both the id-only and name-bearing inputs the client must handle while
the server change deploys separately.
"""

from __future__ import annotations

from yoke_cli.config.onboard_error_friendly import (
    friendly_permission_error,
    friendly_publish_error,
)


def test_id_only_org_denial_is_friendlified() -> None:
    raw = "actor 37 lacks 'project.create' on org 1"
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "Your API token lacks project.create rights for org 1. "
        "Contact your Yoke administrator."
    )


def test_name_bearing_org_denial_uses_the_name() -> None:
    raw = "actor 37 lacks 'project.create' on org 'Acme Inc' (id 1)"
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "Your API token lacks project.create rights for Acme Inc. "
        "Contact your Yoke administrator."
    )


def test_id_only_project_denial_is_friendlified() -> None:
    raw = "actor 5 lacks 'items.write' on project 9"
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "Your API token lacks items.write rights for project 9. "
        "Contact your Yoke administrator."
    )


def test_name_bearing_project_denial_uses_the_name() -> None:
    raw = "actor 5 lacks 'items.write' on project 'My App' (myapp, id 9)"
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "Your API token lacks items.write rights for My App. "
        "Contact your Yoke administrator."
    )


def test_double_quoted_permission_is_handled() -> None:
    # repr() can render with double quotes on some inputs; the helper accepts
    # both quote styles so the match never depends on the repr quote choice.
    raw = 'actor 1 lacks "org.admin" on org 2'
    friendly = friendly_permission_error(raw)
    assert "lacks org.admin rights for org 2" in friendly


def test_non_permission_error_is_unchanged() -> None:
    raw = "token from argument is empty"
    assert friendly_permission_error(raw) == raw


def test_partial_denial_shape_is_left_unchanged() -> None:
    # Missing the "on <scope>" tail is not a recognized denial; leave it as-is
    # rather than emit a half-built sentence.
    raw = "actor 7 lacks 'project.create'"
    assert friendly_permission_error(raw) == raw


def test_wrapped_denial_inside_a_longer_message_is_friendlified() -> None:
    # The server may wrap the denial in an outer "projects.create failed: …"
    # prefix; the helper finds the denial clause and rewrites the whole message.
    raw = "projects.create failed: actor 37 lacks 'project.create' on org 1"
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "Your API token lacks project.create rights for org 1. "
        "Contact your Yoke administrator."
    )


def test_generic_dispatch_permission_denial_names_permission_path() -> None:
    raw = "projects.create failed: permission denied for org acme"
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "Your API token lacks project.create rights. "
        "Contact your Yoke administrator."
    )


def test_friendly_publish_error_rewrites_write_access_denial() -> None:
    raw = "git push failed with 128: remote: Write access to repository not granted."
    friendly = friendly_publish_error(raw)
    assert friendly == (
        "Your GitHub token doesn't have permission to create a repo. "
        "Create the repo on GitHub first, then re-run and choose Clone or "
        "an existing folder."
    )


def test_friendly_publish_error_rewrites_permission_denied() -> None:
    raw = "remote: Permission to acme/widget.git denied to user."
    assert "create the repo on github first" in friendly_publish_error(raw).lower()


def test_friendly_publish_error_passes_unrelated_message_through() -> None:
    raw = "token from argument is empty"
    assert friendly_publish_error(raw) == raw

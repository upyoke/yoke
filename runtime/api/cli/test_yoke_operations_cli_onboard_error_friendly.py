"""Unit coverage for the onboarding permission-error friendlify helper.

The control plane raises terse authorization errors (``actor N lacks 'PERM' on
org M`` / ``on project M``) and, once the name-bearing server build ships, the
``on org 'NAME' (id M)`` form. ``friendly_permission_error`` rewrites all of
them into one actionable sentence and leaves every other error untouched. These
tests pin both the id-only and name-bearing inputs the client must handle while
the server change deploys separately, plus the denial that carries its own
recovery clause — where "contact your administrator" would be advice to
contact yourself, and dropping the clause would cost the operator the one
command that repairs it.
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
        "You lack project.create rights for org 1. "
        "Contact your Yoke administrator."
    )


def test_name_bearing_org_denial_uses_the_name() -> None:
    raw = "actor 37 lacks 'project.create' on org 'Acme Inc' (id 1)"
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "You lack project.create rights for Acme Inc. "
        "Contact your Yoke administrator."
    )


def test_id_only_project_denial_is_friendlified() -> None:
    raw = "actor 5 lacks 'items.write' on project 9"
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "You lack items.write rights for project 9. "
        "Contact your Yoke administrator."
    )


def test_name_bearing_project_denial_uses_the_name() -> None:
    raw = "actor 5 lacks 'items.write' on project 'My App' (myapp, id 9)"
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "You lack items.write rights for My App. "
        "Contact your Yoke administrator."
    )


def test_double_quoted_permission_is_handled() -> None:
    # repr() can render with double quotes on some inputs; the helper accepts
    # both quote styles so the match never depends on the repr quote choice.
    raw = 'actor 1 lacks "org.admin" on org 2'
    friendly = friendly_permission_error(raw)
    assert "You lack org.admin rights for org 2" in friendly


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
        "You lack project.create rights for org 1. "
        "Contact your Yoke administrator."
    )


def test_generic_dispatch_permission_denial_names_permission_path() -> None:
    raw = "projects.create failed: permission denied for org acme"
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "You lack project.create rights. Contact your Yoke administrator."
    )


def test_friendly_publish_error_rewrites_write_access_denial() -> None:
    raw = "git push failed with 128: remote: Write access to repository not granted."
    friendly = friendly_publish_error(raw)
    assert friendly == (
        "GitHub authorization doesn't have permission to create a repo. "
        "Create the repo on GitHub first, then re-run and choose Clone or "
        "an existing folder."
    )


def test_friendly_publish_error_rewrites_permission_denied() -> None:
    raw = "remote: Permission to acme/widget.git denied to user."
    assert "create the repo on github first" in friendly_publish_error(raw).lower()


def test_friendly_publish_error_passes_unrelated_message_through() -> None:
    raw = "token from argument is empty"
    assert friendly_publish_error(raw) == raw


def test_denial_carrying_a_recovery_clause_closes_with_it() -> None:
    raw = (
        "actor 2 lacks 'claims.acquire' on project 'Yoke' (yoke, id 1). This "
        "universe's operating actor holds no org admin role, so every mutation "
        "its sessions attempt is denied. Repair: `yoke doctor run --quick "
        "--fix`, which grants exactly that role on this universe's own org."
    )
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "You lack claims.acquire rights for Yoke. This universe's "
        "operating actor holds no org admin role, so every mutation its "
        "sessions attempt is denied. Repair: `yoke doctor run --quick --fix`, "
        "which grants exactly that role on this universe's own org."
    )


def test_id_only_scope_with_a_recovery_clause_still_resolves_the_scope() -> None:
    """The scope must not swallow the clause and lose its own end anchor."""
    raw = "actor 2 lacks 'items.write' on project 9. Do the thing that fixes it."
    friendly = friendly_permission_error(raw)
    assert friendly == (
        "You lack items.write rights for project 9. "
        "Do the thing that fixes it."
    )


def test_org_role_denial_passes_the_role_recovery_through() -> None:
    """An org operator refused project.create reads their role, not a token."""
    recovery = (
        "Dana Lee holds org role operator; creating a project needs org role "
        "owner or admin. Ask an org owner or admin to do it for you, or to "
        "change your role with `yoke actors role set --member EMAIL --role admin`."
    )
    raw = f"actor 37 lacks 'project.create' on org 'Acme Inc' (id 1). {recovery}"
    friendly = friendly_permission_error(raw)
    assert friendly == f"You lack project.create rights for Acme Inc. {recovery}"
    assert "token" not in friendly.lower()
    assert "Contact your Yoke administrator" not in friendly

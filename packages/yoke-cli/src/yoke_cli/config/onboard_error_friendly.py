"""Rewrite server permission-denied errors into operator-readable copy.

The control plane raises terse authorization errors like
``actor 37 lacks 'project.create' on org 1`` (and, once the name-bearing server
build ships, ``... on org 'Acme' (id 1)``). Those leak an internal actor id and
name nothing the operator can act on. :func:`friendly_permission_error` detects
that shape — across both the old id-only and the new name-bearing forms — and
rewrites it to a single actionable sentence. Any message that is not a
permission denial is returned unchanged, so wrapping every surfaced onboarding
error in this helper is safe.
"""

from __future__ import annotations

import re

# actor <id> lacks '<perm>' on <scope>. The scope tail is captured whole and
# parsed by _scope_target so one regex covers org / project and id-only /
# name-bearing forms. Quotes around the permission may be ' or " (repr style).
_DENY_RE = re.compile(
    r"actor\s+\d+\s+lacks\s+['\"](?P<perm>[^'\"]+)['\"]\s+on\s+(?P<scope>.+?)\s*$"
)

# A scope that carries a name: ``org 'Acme' (id 1)`` or
# ``project 'My Project' (myproj, id 1)``. The quoted name is the target.
_NAMED_SCOPE_RE = re.compile(r"^(?:org|project)\s+['\"](?P<name>[^'\"]+)['\"]")

# An id-only scope: ``org 1`` or ``project 1`` — used verbatim as the target.
_ID_SCOPE_RE = re.compile(r"^(?:org|project)\s+\d+\s*$")

_GENERIC_DISPATCH_DENIED_RE = re.compile(
    r"(?P<function>[a-z][a-z0-9_.-]+)\s+failed:\s+(?P<detail>.*permission denied.*)",
    re.IGNORECASE,
)

_FUNCTION_PERMISSION_HINTS = {
    "projects.create": "project.create",
}


def _scope_target(scope: str) -> str | None:
    """Return the human target for a denial scope tail, or None if unrecognized.

    ``org 'Acme' (id 1)`` -> ``Acme``; ``org 1`` -> ``org 1``. Returning the
    raw id-only scope keeps the sentence meaningful even before the name-bearing
    server build ships.
    """
    named = _NAMED_SCOPE_RE.match(scope)
    if named:
        return named.group("name")
    if _ID_SCOPE_RE.match(scope):
        return scope
    return None


# Git/GitHub push-or-create denial signatures (case-insensitive). A raw git 403
# from publish_to_remote, or any create/push permission denial, rewrites to the
# create-the-repo-first guidance. Anything else passes through unchanged.
_PUBLISH_DENIED_RE = re.compile(
    r"write access to repository not granted|permission to .+ denied|\b403\b",
    re.IGNORECASE,
)


def friendly_publish_error(message: str) -> str:
    """Rewrite a GitHub create/push permission denial; return others unchanged."""
    if _PUBLISH_DENIED_RE.search(message):
        return (
            "Your GitHub token doesn't have permission to create a repo. "
            "Create the repo on GitHub first, then re-run and choose Clone or "
            "an existing folder."
        )
    return message


def friendly_permission_error(message: str) -> str:
    """Rewrite a permission-denied message; return others unchanged.

    ``actor 37 lacks 'project.create' on org 1`` becomes
    ``Your API token lacks project.create rights for org 1. Contact your Yoke
    administrator.`` and the name-bearing variant names the org/project instead
    of the id. A message that does not match the denial shape is returned as-is.
    """
    match = _DENY_RE.search(message.strip())
    if not match:
        generic = _GENERIC_DISPATCH_DENIED_RE.search(message.strip())
        if not generic:
            return message
        function_id = generic.group("function")
        permission = _FUNCTION_PERMISSION_HINTS.get(function_id, function_id)
        return (
            f"Your API token lacks {permission} rights. "
            "Contact your Yoke administrator."
        )
    target = _scope_target(match.group("scope"))
    if target is None:
        return message
    perm = match.group("perm")
    return (
        f"Your API token lacks {perm} rights for {target}. "
        "Contact your Yoke administrator."
    )


__all__ = ["friendly_permission_error", "friendly_publish_error"]

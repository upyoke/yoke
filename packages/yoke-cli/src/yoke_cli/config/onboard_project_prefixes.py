"""Item prefixes already held in the setup destination's universe.

A project's item prefix is universe-unique, and a retired project keeps its
prefix. Setup reads the holders so the Project details default skips a taken
prefix and both the details form and Review refuse one before Apply. The read
answers ``None`` when the destination cannot say (no local universe yet, no
token, a failed read); ``projects.create`` stays the final authority then.
Hosted reads list the projects this person can see, so a prefix held in an
org they cannot see is still refused by ``projects.create`` at Apply.
"""

from __future__ import annotations

from itertools import count
from typing import Any, Callable, Mapping

from yoke_contracts.onboard_destinations import DESTINATION_LOCAL

from yoke_cli.config import existing_project_lookup
from yoke_cli.config.existing_project_http import (
    ExistingProjectLookupError,
    call_function,
)

FALLBACK_PREFIX = "PRJ"
MAX_PREFIX_LENGTH = 6
DETAILS_RECOVERY = "Choose another prefix."
REVIEW_RECOVERY = "Go back to Project details and choose another prefix."
_LIST_PAYLOAD = {
    "fields": ["id", "slug", "public_item_prefix", "retired_at"],
    "include_retired": True,
}

#: Upper-cased prefix -> the project holding it, e.g. ``project 'qa' (id 65)``.
Holders = dict[str, str]


def read_holders(
    result: Any, read_token: Callable[[], str | None]
) -> Holders | None:
    """Return the destination's prefix holders, or None when it cannot say."""
    try:
        if getattr(result, "destination", None) == DESTINATION_LOCAL:
            response = existing_project_lookup._call_local_function(
                config_path=getattr(result, "config_path", None),
                function="projects.list",
                payload=_LIST_PAYLOAD,
            )
        else:
            api_url = str(getattr(result, "api_url", None) or "").strip()
            token = read_token() if api_url else None
            if not token:
                return None
            response = call_function(
                api_url=api_url,
                token=token,
                function="projects.list",
                payload=_LIST_PAYLOAD,
            )
    except ExistingProjectLookupError:
        return None
    return holders_from_response(response)


def holders_from_response(response: Mapping[str, Any]) -> Holders | None:
    """Map a ``projects.list`` envelope to prefix holders; None if unusable."""
    if not response.get("success"):
        return None
    payload = response.get("result")
    rows = payload.get("rows") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return None
    holders: Holders = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        prefix = str(row.get("public_item_prefix") or "").strip().upper()
        if not prefix:
            continue
        retired = " (retired)" if row.get("retired_at") else ""
        holders[prefix] = (
            f"project {str(row.get('slug') or '')!r} "
            f"(id {row.get('id')}){retired}"
        )
    return holders


def propose(slug: str, holders: Holders | None) -> str:
    """Suggest a valid prefix from ``slug`` that no project holds yet."""
    base = "".join(c for c in slug.upper() if c.isalnum())[:MAX_PREFIX_LENGTH]
    if len(base) < 2 or not base[0].isalpha():
        base = FALLBACK_PREFIX
    taken = holders or {}
    if base not in taken:
        return base
    for number in count(2):
        suffix = str(number)
        candidate = base[: MAX_PREFIX_LENGTH - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
    raise AssertionError("unreachable")  # pragma: no cover


def holder_problem(
    prefix: str | None, holders: Holders | None, *, recovery: str
) -> str | None:
    """Name the project holding ``prefix``, with ``recovery``; None when free."""
    wanted = str(prefix or "").strip().upper()
    holder = (holders or {}).get(wanted) if wanted else None
    if holder is None:
        return None
    return f"Item prefix {wanted} is already used by {holder}. {recovery}"


__all__ = [
    "DETAILS_RECOVERY",
    "FALLBACK_PREFIX",
    "Holders",
    "REVIEW_RECOVERY",
    "holder_problem",
    "holders_from_response",
    "propose",
    "read_holders",
]

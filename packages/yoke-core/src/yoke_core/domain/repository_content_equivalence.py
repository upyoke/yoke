"""Whether a commit's content is already present in a candidate revision.

The merge boundary answers "this lane adds nothing" by merging the lane into
the base in memory and comparing trees (``standalone_item_merge_git.
lane_adds_nothing``). That is the definition, and a checkout answers it
directly. A control plane serving an HTTPS-only project holds no checkout and
cannot merge anything, so it reads the same fact from the two things the
repository provider will tell it: which paths the commit changed relative to
where it left the candidate, and what each of those paths holds on the
candidate itself.

The reading is sound because a merge can only differ from its base at paths
the incoming side changed. When every such path already holds the incoming
side's exact blob — and every path it deleted is already absent — merging
produces the base's own tree, which is precisely "adds nothing".

This reader answers ``True`` or ``None``, and never ``False``. Everything it
cannot see is unknown — a listing the provider truncated, a path count past
the budget, a blob it would not serve — and so is a blob that simply differs,
because two opposite stories produce that one shape: the head still carries
work the candidate lacks, or the candidate took that work and then moved the
same path further on. Only merging the trees separates them, which is exactly
what this reader cannot do. An unread answer keeps the caller on its other
rungs; a wrong ``True`` would close an item out against work that never
shipped, and a wrong ``False`` refuses a release that did ship it.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from yoke_core.domain.gh_rest_transport import RestRequest, request_with_retry
from yoke_core.domain.gh_rest_transport_errors import (
    RestNotFoundError,
    RestTransportError,
)


#: How many changed paths this reader will price. A commit whose content is
#: already present differs in a handful of paths at most, so a larger set is
#: a lane with real work rather than a budget to raise.
COMPARED_PATH_BUDGET = 40

#: GitHub caps a comparison's file listing. A listing at the cap may be
#: missing paths, so it proves nothing about the ones it did not name.
PROVIDER_FILE_LISTING_CAP = 300

#: The blob a path does not have, because the revision does not carry it.
ABSENT = ""


def blob_sha(
    repo: str, token: str, path: str, ref: str
) -> Optional[str]:
    """The blob object id at ``path`` on ``ref``, ``ABSENT``, or ``None``.

    ``None`` is "this reader could not tell", which includes a path that
    names a directory on this revision: the contents endpoint answers with a
    listing there, and a listing is not a blob identity to compare.
    """
    request = RestRequest(
        method="GET",
        path=f"/repos/{repo}/contents/{path}",
        query={"ref": ref},
    )
    try:
        response = request_with_retry(request, token=token)
    except RestNotFoundError:
        # The revision does not carry this path, which is an answer.
        return ABSENT
    except RestTransportError:
        return None
    body = response.body
    if not isinstance(body, Mapping):
        return None
    return str(body.get("sha") or "") or None


def content_already_present(
    body: Mapping[str, Any],
    read_blob: Callable[[str], Optional[str]],
) -> Optional[bool]:
    """Whether the compared head changes nothing the base does not already have.

    ``body`` is one comparison page whose BASE is the candidate revision, so
    its ``files`` are exactly the paths the head changed since the two
    diverged. ``read_blob`` answers what the candidate holds at one path.

    ``True`` or ``None`` only: see the module docstring for why a differing
    blob is unknown rather than a definite "still adds something".
    """
    files = body.get("files")
    if not isinstance(files, list):
        return None
    if not files:
        return True
    if len(files) > COMPARED_PATH_BUDGET or len(files) >= PROVIDER_FILE_LISTING_CAP:
        return None
    for entry in files:
        present = _path_already_present(entry, read_blob)
        if present is not True:
            return present
    return True


def _path_already_present(
    entry: Any, read_blob: Callable[[str], Optional[str]]
) -> Optional[bool]:
    """Whether the candidate already holds one changed path's content."""
    if not isinstance(entry, Mapping):
        return None
    path = str(entry.get("filename") or "")
    status = str(entry.get("status") or "")
    if not path or not status:
        return None
    expected = ABSENT if status == "removed" else str(entry.get("sha") or "")
    if status != "removed" and not expected:
        return None
    actual = read_blob(path)
    if actual is None:
        return None
    if actual != expected:
        # Not "the candidate lacks this" — "this reader cannot tell". The
        # candidate may hold a later revision of a path whose content it
        # already took from this head, which reads exactly the same here.
        return None
    if status != "renamed":
        return True
    # A rename also deletes where the path came from, so the candidate has
    # to have completed that half too.
    previous = str(entry.get("previous_filename") or "")
    if not previous:
        return None
    vacated = read_blob(previous)
    return True if vacated == ABSENT else None


__all__ = [
    "ABSENT",
    "COMPARED_PATH_BUDGET",
    "PROVIDER_FILE_LISTING_CAP",
    "blob_sha",
    "content_already_present",
]

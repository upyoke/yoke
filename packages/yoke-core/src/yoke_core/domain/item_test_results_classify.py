"""Pure classifier + reader for ``items.test_results`` content.

Domain-layer single source of truth for the verdict the merge engine
substitutes when no required CI checks are configured. Also consumed by
``check_polishing_implementation_to_implemented_gate`` so the polish
phase refuses to advance a project's items with empty/failed verdicts —
the symmetric upstream half of the merge gate. The ``items.test_results``
reader lives here too so the polish gate (domain layer) and the merge
engine (orchestration layer) consume one source of truth without the
domain→orchestration import the architecture model forbids.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from yoke_core.domain import db_helpers


def _p(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


_FAILURE_SIGNATURE = re.compile(r"\b(FAILED|ERROR|ERRORS)\b")
_PYTEST_PASS_VERDICT = re.compile(
    r"(?:=+\s*\d+\s+passed[^=]*=+)"
    r"|(?:^\s*\d+\s+passed(?:\s+in\s+[\d.]+s)?\s*$)",
    re.MULTILINE,
)

# Verdict head-SHA binding (freshness). Polish stamps the worktree HEAD
# SHA the verdict ran against into the captured blob as an HTML comment;
# the merge engine refuses a CI-substitute verdict whose stamp does not
# match the PR head SHA, closing the "stale local PASS sails through when
# CI is skipped" hole. The comment shape carries no FAILED / ERROR token
# and no pytest pass-verdict pattern, so it never perturbs
# ``classify_test_results``.
_VERDICT_SHA_MARKER = "yoke-verdict-head-sha"
_SHA_BODY = r"[0-9a-fA-F]{7,40}"
_VERDICT_SHA_RE = re.compile(
    r"<!--\s*" + _VERDICT_SHA_MARKER + r":\s*(" + _SHA_BODY + r")\s*-->"
)
_SHA_FULLMATCH = re.compile(r"^" + _SHA_BODY + r"$")


def classify_test_results(text: str) -> str:
    """Return ``"empty"`` | ``"failed"`` | ``"passed"`` for a captured pytest blob.

    ``"failed"`` when the text contains a pytest failure signature
    (``FAILED`` / ``ERROR`` / ``ERRORS`` on word boundaries — pytest
    emits these tokens uppercase). ``"passed"`` when a pytest PASS
    verdict appears with no failure tokens. Two pass-verdict shapes
    are first-class: the equals-banner pytest emits in normal mode
    (``=== N passed in TIMEs ===``) AND the line-anchored standalone
    verdict pytest emits in ``-q`` (quiet) mode (``N passed in TIMEs``
    on its own line, ``in TIMEs`` optional). Anything else — including
    prose summaries like ``all tests passed`` that lack a numeric
    verdict line — falls through to ``"empty"`` so callers refuse to
    substitute unclear evidence.
    """
    if not text or not text.strip():
        return "empty"
    if _FAILURE_SIGNATURE.search(text):
        return "failed"
    if _PYTEST_PASS_VERDICT.search(text):
        return "passed"
    return "empty"


def read_item_test_results(
    item_id: str | int,
    *,
    db_path: Optional[str] = None,
) -> str:
    """Return the ``items.test_results`` column for ``item_id``.

    Accepts both the bare integer id and the ``YOK-N`` operator form so
    callers hand through whichever shape they received. Returns ``""``
    when the id is empty / unparseable, when the row is missing, or
    when the column is NULL. Read-only; raises only on a genuine sqlite
    error the caller cannot recover from.
    """
    if item_id is None:
        return ""
    if isinstance(item_id, int):
        numeric_id = item_id
    else:
        text = str(item_id).strip()
        if not text:
            return ""
        try:
            numeric_id = int(text.removeprefix("YOK-").lstrip("0") or "0")
        except ValueError:
            return ""
    if numeric_id <= 0:
        return ""
    conn: Any = db_helpers.connect(db_path)
    try:
        p = _p(conn)
        row = conn.execute(
            f"SELECT test_results FROM items WHERE id={p}", (numeric_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return ""
    value = row[0]
    return value if isinstance(value, str) else ""


def format_verdict_head_sha_trailer(head_sha: str) -> str:
    """Return the HTML-comment trailer binding a verdict to ``head_sha``.

    Single source of truth for the trailer shape so the polish writer and
    the merge-engine reader never drift. Returns ``""`` for an empty or
    non-sha input so callers never stamp a meaningless marker.
    """
    sha = (head_sha or "").strip()
    if not _SHA_FULLMATCH.match(sha):
        return ""
    return f"<!-- {_VERDICT_SHA_MARKER}: {sha} -->"


def extract_verdict_head_sha(text: str) -> Optional[str]:
    """Return the head SHA stamped into a verdict blob (lowercased), or ``None``.

    Reads the LAST occurrence so a re-stamped verdict (polish re-ran the
    suite after a fix) reports the most recent binding rather than a stale
    earlier one.
    """
    if not text:
        return None
    matches = _VERDICT_SHA_RE.findall(text)
    if not matches:
        return None
    return matches[-1].lower()


def evaluate_ci_substitute(
    verdict: str,
    raw_results: str,
    head_sha: str,
    head_sha_err: Optional[str],
) -> tuple[bool, str, str]:
    """Decide whether a local verdict may substitute for skipped/absent CI.

    Returns ``(accept, evidence_state, reason_phrase)``. ``accept`` is True
    only when the verdict is a PASS provably bound to ``head_sha``.
    Otherwise ``evidence_state`` names why the substitute is refused
    (``empty`` / ``failed`` / ``head_sha_unresolved`` / ``stale_or_unbound``)
    and ``reason_phrase`` is the operator-facing fragment for the block
    message. The merge engine owns event emission; this owns the decision.
    """
    if (
        verdict == "passed"
        and head_sha_err is None
        and verdict_is_fresh(raw_results, head_sha)
    ):
        return True, "fresh", ""
    if verdict != "passed":
        phrase = "empty" if verdict == "empty" else "a failure verdict"
        return False, verdict, phrase
    if head_sha_err is not None:
        return (
            False,
            "head_sha_unresolved",
            "a PASS verdict but the PR head SHA could not be read",
        )
    return (
        False,
        "stale_or_unbound",
        f"a PASS verdict not bound to the PR head SHA ({head_sha[:12] or '?'})",
    )


def verdict_is_fresh(text: str, head_sha: str) -> bool:
    """Return ``True`` when the verdict blob is provably bound to ``head_sha``.

    Freshness requires a stamped sha that matches ``head_sha`` — exact, or
    one a prefix of the other (>=7 chars) so abbreviated and full sha forms
    compare equal. An unstamped verdict, an empty ``head_sha``, or a
    mismatch is NOT fresh; the merge engine then refuses the CI substitute.
    """
    stamped = extract_verdict_head_sha(text)
    head = (head_sha or "").strip().lower()
    if not stamped or not head:
        return False
    if stamped == head:
        return True
    shorter, longer = sorted((stamped, head), key=len)
    return len(shorter) >= 7 and longer.startswith(shorter)


__all__ = [
    "classify_test_results",
    "read_item_test_results",
    "format_verdict_head_sha_trailer",
    "extract_verdict_head_sha",
    "verdict_is_fresh",
]

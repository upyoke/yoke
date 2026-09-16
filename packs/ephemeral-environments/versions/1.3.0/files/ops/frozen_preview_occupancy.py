#!/usr/bin/env python3
"""Who owns a preview occupancy, and whether this deploy may take it.

A preview's slug is its occupancy: the deploy directory, the derived ports
and the public URL all follow from it, so two previews resolving to one slug
are not two previews — the second replaces the first. For a branch preview
that is the point; for a frozen release preview it is the one thing that
must never happen, because its URL gets cited as evidence that a reviewer
saw one specific commit.

A frozen preview is therefore named by the deployment run that created it,
and that name arrives already decided: the dispatcher sends ``preview_slug``
and this publishes exactly that string. Nothing here derives it, because a
derivation is something the two sides can disagree about — and they did,
each hashing a different value until the deployed host and the probed host
were two different machines. That namespace is closed to branches, as is the
shape previews published before it still occupy here. The occupancy record —
not the caller's arguments — decides whether a deploy may write there, and
cleanup refuses to remove one it cannot prove it owns.

Subcommands: ``resolve``, ``claim``, ``assert-unreserved``,
``check-cleanup``, ``teardown-slug``."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

OWNER_FILENAME = ".yoke-preview-owner.json"
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
#: What a release preview may be published under: the run id, plus a stage
#: discriminator when one run publishes more than one preview. Parity
#: contract with the dispatching side, which builds the same shape.
RELEASE_SLUG_RE = re.compile(
    r"^run-[0-9]{8}-[0-9]{3,}(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?$"
)
#: Also closed to branches: previews published before run-naming still hold
#: this shape here, and a branch taking one would serve a moving branch at a
#: candidate's URL. Nothing new is published under it.
RETAINED_SLUG_RE = re.compile(r"^rel-[0-9a-f]{32}$")
UNREADABLE = "occupancy owner metadata is unreadable. Do not reuse or delete."
RETIRED_OWNER = (
    "this occupancy predates run-named previews and is not addressable by "
    "preview_slug. Do not reuse or delete it here; remove it on the host."
)


class FrozenPreviewError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _safe(value: str | None, name: str) -> str:
    raw = value or ""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise FrozenPreviewError(
            "unsafe_token", f"{name} contains a control character; pass one line."
        )
    return raw.strip()


def require_commit_sha(commit_sha: str) -> str:
    sha = _safe(commit_sha, "commit_sha").lower()
    if not sha:
        raise FrozenPreviewError(
            "missing_revision", "commit_sha is required: one 40-hex candidate SHA."
        )
    if not FULL_SHA_RE.fullmatch(sha):
        raise FrozenPreviewError(
            "malformed_revision",
            f"commit_sha must be one 40-hex SHA (got {commit_sha!r}).",
        )
    return sha


def require_preview_slug(preview_slug: str) -> str:
    slug = _safe(preview_slug, "preview_slug")
    if not slug:
        raise FrozenPreviewError(
            "missing_preview_slug",
            "preview_slug is required: the run this preview is named for.",
        )
    if not RELEASE_SLUG_RE.fullmatch(slug):
        raise FrozenPreviewError(
            "unreserved_preview_slug",
            f"preview_slug {slug!r} is not the reserved release shape "
            "run-YYYYMMDD-NNN[-discriminator]; only that namespace is "
            "protected from a branch of the same name.",
        )
    return slug


def branch_slug(branch_name: str) -> str:
    """Slugify a branch, refusing one that lands in a reserved namespace.

    A branch may be named anything, including the exact shape a frozen
    preview uses, and deploying it would take that preview's directory,
    ports and URL.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", _safe(branch_name, "branch").lower()).strip("-")
    if not slug:
        raise FrozenPreviewError(
            "missing_preview_slug", "branch name produced an empty occupancy slug"
        )
    assert_unreserved(slug)
    return slug


def read_owner(preview_dir: Path) -> dict | None:
    """The recorded owner, or ``None`` when nothing occupies this slug.

    An unreadable record is neither, and refuses: treating it as unoccupied
    is how a candidate under review gets overwritten. So does a record this
    path cannot address, left by the naming before it.
    """
    path = preview_dir / OWNER_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrozenPreviewError("unknown_ownership", UNREADABLE) from exc
    data = payload if isinstance(payload, dict) else {}
    preview_slug = _safe(str(data.get("preview_slug", "")), "preview_slug")
    commit_sha = _safe(str(data.get("commit_sha", "")), "commit_sha").lower()
    if not preview_slug and data.get("yoke_dispatch_id"):
        raise FrozenPreviewError("retired_ownership", RETIRED_OWNER)
    if not preview_slug or not FULL_SHA_RE.fullmatch(commit_sha):
        raise FrozenPreviewError("unknown_ownership", UNREADABLE)
    return {"preview_slug": preview_slug, "commit_sha": commit_sha}


def assert_reuse_or_refuse(preview_dir: Path, preview_slug: str, commit_sha: str) -> str:
    """Decide whether this deploy may write into *preview_dir*.

    Redeploying the same candidate under the same name is the ordinary retry
    that makes a lost dispatch safe to repeat; anything else replaces what
    some reviewer is looking at.
    """
    expected_slug = require_preview_slug(preview_slug)
    expected_sha = require_commit_sha(commit_sha)
    existing = read_owner(preview_dir)
    if existing is None:
        return "create"
    if existing["preview_slug"] != expected_slug:
        raise FrozenPreviewError(
            "ownership_mismatch",
            "this occupancy is owned by a different preview_slug.",
        )
    if existing["commit_sha"] != expected_sha:
        raise FrozenPreviewError(
            "occupancy_conflict",
            f"this occupancy already serves {existing['commit_sha']}, not "
            f"{expected_sha}; a frozen preview is not redeployed onto another.",
        )
    return "reuse"


def read_fields(count: int, stream=None) -> list[str]:
    """Read exactly *count* values, one per line, from stdin.

    Slugs and revisions arrive this way rather than inside a remote command
    string, where a value containing a quote would end its argument and run
    whatever followed — nothing here is parsed by a shell. Exactly, because a
    token carrying a newline would shift every field after it.
    """
    raw = (stream or sys.stdin).read().split("\n")
    if raw and raw[-1] == "":
        # Exactly one: the writer's terminator. Dropping every trailing blank
        # would erase an empty final field, meaning "no slug supplied".
        raw.pop()
    if len(raw) != count:
        raise FrozenPreviewError(
            "unsafe_token",
            f"expected {count} newline-separated values on stdin, got {len(raw)}; "
            "a value spanning lines cannot be told from the next field",
        )
    return [_safe(value, "stdin field") for value in raw]


def occupancy_dir(preview_root: str, preview_slug: str, supplied_slug: str) -> Path:
    """The directory this name owns, refusing a slug it does not match.

    A caller free to name any slug could claim any occupancy, so the
    preview's own name is the authority.
    """
    supplied = _safe(supplied_slug, "slug")
    if not _safe(preview_slug, "preview_slug"):
        assert_unreserved(supplied)
        return Path(preview_root).expanduser() / supplied
    owned = require_preview_slug(preview_slug)
    if supplied and supplied != owned:
        raise FrozenPreviewError(
            "ownership_mismatch",
            f"slug {supplied!r} is not the occupancy {owned!r} this preview names.",
        )
    return Path(preview_root).expanduser() / owned


def claim(preview_dir: Path, preview_slug: str, commit_sha: str) -> str:
    """Check, then record — one call, because they are one decision: split in
    two, an interruption leaves an occupancy nobody owns."""
    outcome = assert_reuse_or_refuse(preview_dir, preview_slug, commit_sha)
    write_owner(preview_dir, preview_slug, commit_sha)
    return outcome


def assert_unreserved(slug: str) -> None:
    """Refuse a reserved branch occupancy — again, because the deploy does
    not trust whoever resolved it."""
    value = _safe(slug, "slug")
    if RELEASE_SLUG_RE.fullmatch(value) or RETAINED_SLUG_RE.fullmatch(value):
        raise FrozenPreviewError(
            "reserved_slug",
            f"branch occupancy {value!r} is reserved for frozen release "
            "previews. Recovery: rename the branch and push again.",
        )


def write_owner(preview_dir: Path, preview_slug: str, commit_sha: str) -> Path:
    preview_dir.mkdir(parents=True, exist_ok=True)
    path = preview_dir / OWNER_FILENAME
    payload = {
        "preview_slug": require_preview_slug(preview_slug),
        "commit_sha": require_commit_sha(commit_sha),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def assert_cleanup_owner(preview_dir: Path, preview_slug: str = "") -> None:
    """Refuse to remove an occupancy this caller cannot prove it owns."""
    live = read_owner(preview_dir)
    named = _safe(preview_slug, "preview_slug")
    if live is None:
        if named:
            raise FrozenPreviewError(
                "ownership_mismatch",
                "cleanup named a preview_slug but this occupancy has no owner.",
            )
        return
    if live["preview_slug"] != named:
        # Both ways a caller fails to own this: wrong preview, and none.
        raise FrozenPreviewError(
            "ownership_mismatch",
            f"{named or 'no preview_slug'} does not own this occupancy. "
            "Recovery: name the preview_slug it was created under.",
        )


def resolve_dispatch(
    *,
    commit_sha: str = "",
    preview_slug: str = "",
    branch_name: str = "",
    github_sha: str = "",
) -> dict:
    commit_sha = _safe(commit_sha, "commit_sha")
    preview_slug = _safe(preview_slug, "preview_slug")
    if commit_sha or preview_slug:
        # Both or neither: a name with no candidate would publish a frozen
        # preview of whatever the ref happens to point at.
        sha = require_commit_sha(commit_sha)
        slug = require_preview_slug(preview_slug)
        mode = "frozen"
    else:
        sha = require_commit_sha(github_sha)
        slug, mode = branch_slug(branch_name), "branch"
        preview_slug = ""
    return {
        "mode": mode,
        "candidate_sha": sha,
        "occupancy_slug": slug,
        "preview_slug": preview_slug,
        "branch_exists": "true",
    }


def _emit(mapping: dict) -> None:
    for key, value in mapping.items():
        print(f"{_safe(key, 'key')}={_safe(str(value), key)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen preview occupancy guard")
    sub = parser.add_subparsers(dest="command", required=True)
    resolve = sub.add_parser("resolve")
    for flag in ("--commit-sha", "--preview-slug", "--branch", "--github-sha"):
        resolve.add_argument(flag, default="")
    for name in ("claim", "check-cleanup"):
        remote = sub.add_parser(name)
        remote.add_argument("--preview-root", required=True)
    unreserved = sub.add_parser("assert-unreserved")
    unreserved.add_argument("--slug", required=True)
    slug = sub.add_parser("teardown-slug")
    slug.add_argument("--preview-slug", default="")
    slug.add_argument("--branch", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            _emit(
                resolve_dispatch(
                    commit_sha=args.commit_sha,
                    preview_slug=args.preview_slug,
                    branch_name=args.branch,
                    github_sha=args.github_sha,
                )
            )
        elif args.command == "claim":
            preview_slug, commit_sha, slug = read_fields(3)
            print(
                claim(
                    occupancy_dir(args.preview_root, preview_slug, slug),
                    preview_slug,
                    commit_sha,
                )
            )
        elif args.command == "assert-unreserved":
            assert_unreserved(args.slug)
            print("ok")
        elif args.command == "check-cleanup":
            preview_slug, slug = read_fields(2)
            assert_cleanup_owner(
                occupancy_dir(args.preview_root, preview_slug, slug), preview_slug
            )
            print("ok")
        else:
            named = _safe(args.preview_slug, "preview_slug")
            _emit(
                {
                    "occupancy_slug": (
                        require_preview_slug(named)
                        if named
                        else branch_slug(args.branch)
                    ),
                    "preview_slug": named,
                }
            )
    except FrozenPreviewError as exc:
        print(f"ERROR [{exc.code}]: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

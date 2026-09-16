#!/usr/bin/env python3
"""Who owns a preview occupancy, and whether this deploy may take it.

A preview's slug is its occupancy: the deploy directory, the derived ports
and the public URL all follow from it, so two previews resolving to one slug
are not two previews — the second replaces the first. For a branch preview
that is the point; for a frozen release preview it is the one thing that
must never happen, because its URL gets cited as evidence that a reviewer
saw one specific commit.

A frozen preview is therefore named by hashing its dispatch identity, which
lands it in the reserved ``rel-`` namespace no branch may enter, and the
occupancy on the host records who created it and on which commit. That
record — not the caller's arguments — decides whether a deploy may write
there, and cleanup refuses to remove an occupancy it cannot prove it owns.

Subcommands: ``resolve``, ``claim``, ``assert-unreserved``,
``check-cleanup``, ``teardown-slug``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

OWNER_FILENAME = ".yoke-preview-owner.json"
FROZEN_SLUG_PREFIX = "rel-"
SLUG_HASH_HEX = 32
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RESERVED_SLUG_RE = re.compile(
    rf"{FROZEN_SLUG_PREFIX}[0-9a-f]{{{SLUG_HASH_HEX}}}"
)
UNREADABLE = "occupancy owner metadata is unreadable. Do not reuse or delete."


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


def require_dispatch_id(yoke_dispatch_id: str) -> str:
    token = _safe(yoke_dispatch_id, "yoke_dispatch_id")
    if not token:
        raise FrozenPreviewError(
            "missing_correlation",
            "yoke_dispatch_id is required: the correlation this preview is named for.",
        )
    return token


def frozen_occupancy_slug(yoke_dispatch_id: str) -> str:
    """``rel-`` plus 32 hex of the SHA-256 of the identity, hashed whole.

    Parity contract with the dispatching side, which derives this URL before
    this workflow reports one; a drift points its proof at another host.
    """
    digest = hashlib.sha256(require_dispatch_id(yoke_dispatch_id).encode()).hexdigest()
    return f"{FROZEN_SLUG_PREFIX}{digest[:SLUG_HASH_HEX]}"


def branch_slug(branch_name: str) -> str:
    """Slugify a branch, refusing one that lands in the frozen namespace.

    A branch may be named anything, including the exact shape a frozen
    preview uses — and deploying it would take that preview's directory,
    ports and URL.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", _safe(branch_name, "branch").lower()).strip("-")
    if not slug:
        raise FrozenPreviewError(
            "missing_correlation", "branch name produced an empty occupancy slug"
        )
    if RESERVED_SLUG_RE.fullmatch(slug):
        raise FrozenPreviewError(
            "reserved_slug",
            f"branch occupancy {slug!r} is in the {FROZEN_SLUG_PREFIX!r} namespace "
            "reserved for frozen dispatch previews. Recovery: rename the branch "
            "and push again.",
        )
    return slug


def read_owner(preview_dir: Path) -> dict | None:
    """The recorded owner, or ``None`` when nothing occupies this slug.

    An unreadable record is neither, and refuses: treating it as unoccupied
    is how a candidate under review gets overwritten.
    """
    path = preview_dir / OWNER_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrozenPreviewError("unknown_ownership", UNREADABLE) from exc
    data = payload if isinstance(payload, dict) else {}
    dispatch_id = _safe(str(data.get("yoke_dispatch_id", "")), "yoke_dispatch_id")
    commit_sha = _safe(str(data.get("commit_sha", "")), "commit_sha").lower()
    if not dispatch_id or not FULL_SHA_RE.fullmatch(commit_sha):
        raise FrozenPreviewError("unknown_ownership", UNREADABLE)
    return {"yoke_dispatch_id": dispatch_id, "commit_sha": commit_sha}


def assert_reuse_or_refuse(preview_dir: Path, dispatch_id: str, commit_sha: str) -> str:
    """Decide whether this deploy may write into *preview_dir*.

    Redeploying the same candidate under the same identity is the ordinary
    retry that makes a lost dispatch safe to repeat. Anything else would
    replace what some reviewer is looking at.
    """
    expected_id = require_dispatch_id(dispatch_id)
    expected_sha = require_commit_sha(commit_sha)
    existing = read_owner(preview_dir)
    if existing is None:
        return "create"
    if existing["yoke_dispatch_id"] != expected_id:
        raise FrozenPreviewError(
            "ownership_mismatch",
            "this occupancy is owned by a different yoke_dispatch_id.",
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

    Correlations and slugs arrive this way rather than inside a remote
    command string, where a value containing a quote would end its argument
    and run whatever followed — nothing here is parsed by a shell. Exactly,
    because a token carrying a newline would otherwise shift every field
    after it and claim an occupancy nobody named.
    """
    raw = (stream or sys.stdin).read().split("\n")
    if raw and raw[-1] == "":
        # Exactly one: the writer's terminator. Dropping every trailing blank
        # would erase an empty final field, which legitimately means "no
        # slug supplied".
        raw.pop()
    if len(raw) != count:
        raise FrozenPreviewError(
            "unsafe_token",
            f"expected {count} newline-separated values on stdin, got {len(raw)}; "
            "a value spanning lines cannot be told from the next field",
        )
    return [_safe(value, "stdin field") for value in raw]


def occupancy_dir(preview_root: str, dispatch_id: str, supplied_slug: str) -> Path:
    """The directory this identity owns, refusing a slug it does not derive.

    A caller that could name any slug could claim any occupancy, so the
    identity is the authority.
    """
    supplied = _safe(supplied_slug, "slug")
    if not _safe(dispatch_id, "yoke_dispatch_id"):
        assert_unreserved(supplied)
        return Path(preview_root).expanduser() / supplied
    derived = frozen_occupancy_slug(dispatch_id)
    if supplied and supplied != derived:
        raise FrozenPreviewError(
            "ownership_mismatch",
            f"slug {supplied!r} is not the occupancy {derived!r} this identity names.",
        )
    return Path(preview_root).expanduser() / derived


def claim(preview_dir: Path, dispatch_id: str, commit_sha: str) -> str:
    """Check, then record — one call, because they are one decision: split
    across two workflow steps, an interruption leaves an occupancy nobody
    owns."""
    outcome = assert_reuse_or_refuse(preview_dir, dispatch_id, commit_sha)
    write_owner(preview_dir, dispatch_id, commit_sha)
    return outcome


def assert_unreserved(slug: str) -> None:
    """Refuse a branch occupancy inside the frozen namespace — again,
    because the deploy does not trust whoever resolved it."""
    value = _safe(slug, "slug")
    if RESERVED_SLUG_RE.fullmatch(value):
        raise FrozenPreviewError(
            "reserved_slug",
            f"branch occupancy {value!r} is in the {FROZEN_SLUG_PREFIX!r} namespace "
            "reserved for frozen dispatch previews. Recovery: rename the branch "
            "and push again.",
        )


def write_owner(preview_dir: Path, dispatch_id: str, commit_sha: str) -> Path:
    preview_dir.mkdir(parents=True, exist_ok=True)
    path = preview_dir / OWNER_FILENAME
    payload = {
        "yoke_dispatch_id": require_dispatch_id(dispatch_id),
        "commit_sha": require_commit_sha(commit_sha),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def assert_cleanup_owner(preview_dir: Path, dispatch_id: str = "") -> None:
    """Refuse to remove an occupancy this caller cannot prove it owns."""
    live = read_owner(preview_dir)
    named = _safe(dispatch_id, "yoke_dispatch_id")
    if live is None:
        if named:
            raise FrozenPreviewError(
                "ownership_mismatch",
                "cleanup named a yoke_dispatch_id but this occupancy has no owner.",
            )
        return
    if live["yoke_dispatch_id"] != named:
        # Both ways a caller can fail to own this: naming the wrong identity,
        # and naming none at all.
        raise FrozenPreviewError(
            "ownership_mismatch",
            f"{named or 'no yoke_dispatch_id'} does not own this occupancy. "
            "Recovery: name the yoke_dispatch_id it was created under.",
        )


def resolve_dispatch(
    *,
    commit_sha: str = "",
    yoke_dispatch_id: str = "",
    branch_name: str = "",
    github_sha: str = "",
) -> dict:
    commit_sha = _safe(commit_sha, "commit_sha")
    yoke_dispatch_id = _safe(yoke_dispatch_id, "yoke_dispatch_id")
    if commit_sha or yoke_dispatch_id:
        # Both or neither: an identity with no candidate would publish a
        # frozen preview of whatever the ref happens to point at.
        sha = require_commit_sha(commit_sha)
        token = require_dispatch_id(yoke_dispatch_id)
        slug, mode = frozen_occupancy_slug(token), "frozen"
    else:
        sha = require_commit_sha(github_sha)
        token, slug, mode = "", branch_slug(branch_name), "branch"
    return {
        "mode": mode,
        "candidate_sha": sha,
        "occupancy_slug": slug,
        "yoke_dispatch_id": token,
        "branch_exists": "true",
    }


def _emit(mapping: dict) -> None:
    for key, value in mapping.items():
        print(f"{_safe(key, 'key')}={_safe(str(value), key)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen preview occupancy guard")
    sub = parser.add_subparsers(dest="command", required=True)
    resolve = sub.add_parser("resolve")
    for flag in ("--commit-sha", "--yoke-dispatch-id", "--branch", "--github-sha"):
        resolve.add_argument(flag, default="")
    for name in ("claim", "check-cleanup"):
        remote = sub.add_parser(name)
        remote.add_argument("--preview-root", required=True)
    unreserved = sub.add_parser("assert-unreserved")
    unreserved.add_argument("--slug", required=True)
    slug = sub.add_parser("teardown-slug")
    slug.add_argument("--yoke-dispatch-id", default="")
    slug.add_argument("--branch", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            _emit(
                resolve_dispatch(
                    commit_sha=args.commit_sha,
                    yoke_dispatch_id=args.yoke_dispatch_id,
                    branch_name=args.branch,
                    github_sha=args.github_sha,
                )
            )
        elif args.command == "claim":
            dispatch_id, commit_sha, slug = read_fields(3)
            print(
                claim(
                    occupancy_dir(args.preview_root, dispatch_id, slug),
                    dispatch_id,
                    commit_sha,
                )
            )
        elif args.command == "assert-unreserved":
            assert_unreserved(args.slug)
            print("ok")
        elif args.command == "check-cleanup":
            dispatch_id, slug = read_fields(2)
            assert_cleanup_owner(
                occupancy_dir(args.preview_root, dispatch_id, slug), dispatch_id
            )
            print("ok")
        else:
            token = _safe(args.yoke_dispatch_id, "yoke_dispatch_id")
            _emit(
                {
                    "occupancy_slug": (
                        frozen_occupancy_slug(token)
                        if token
                        else branch_slug(args.branch)
                    ),
                    "yoke_dispatch_id": token,
                }
            )
    except FrozenPreviewError as exc:
        print(f"ERROR [{exc.code}]: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

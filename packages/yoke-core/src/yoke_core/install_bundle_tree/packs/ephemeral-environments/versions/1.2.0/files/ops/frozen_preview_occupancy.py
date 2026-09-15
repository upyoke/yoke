#!/usr/bin/env python3
"""Who owns a preview occupancy, and whether this deploy may take it.

A preview's slug is its occupancy: the deploy directory, the derived ports
and the public URL all follow from it, so two previews resolving to one slug
are not two previews — the second replaces the first. For a branch preview
that is the point; for a frozen release preview it is the one thing that
must never happen, because its URL gets cited as evidence that a reviewer
saw one specific commit. Two rules keep them apart, and both live here so
the workflows stay declarative.

**Naming.** A frozen preview is named by hashing its dispatch identity, so it
always lands in the reserved ``rel-`` namespace, and a branch that slugifies
into that namespace is refused rather than allowed to collide with it.

**Ownership.** The occupancy on the host records who created it and on which
commit. Before anything is written there, that record — not the caller's
arguments — decides whether this deploy may proceed, and cleanup refuses to
remove an occupancy it cannot prove it owns.

Subcommands, each printing ``KEY=value`` lines or a single word:
``resolve`` (slug, candidate and ports for either kind of preview),
``claim`` (may this deploy write here, and record that it did),
``assert-unreserved`` (a branch may not enter the frozen namespace),
``check-cleanup`` (may this caller remove this occupancy), and
``teardown-slug``.
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
            "unsafe_token",
            f"{name} contains a control character. Recovery: pass a "
            "single-line value.",
        )
    return raw.strip()


def require_commit_sha(commit_sha: str) -> str:
    sha = _safe(commit_sha, "commit_sha").lower()
    if not sha:
        raise FrozenPreviewError(
            "missing_revision",
            "commit_sha is required; pass the frozen candidate as one 40-hex SHA.",
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
            "yoke_dispatch_id is required. Recovery: pass the dispatch "
            "correlation this preview is named for.",
        )
    return token


def frozen_occupancy_slug(yoke_dispatch_id: str) -> str:
    """``rel-`` plus 32 hex of the SHA-256 of the identity, hashed whole.

    Parity contract with the dispatching side, which derives this URL before
    this workflow reports one. A drift here points its proof at a host
    serving something else.
    """
    digest = hashlib.sha256(require_dispatch_id(yoke_dispatch_id).encode()).hexdigest()
    return f"{FROZEN_SLUG_PREFIX}{digest[:SLUG_HASH_HEX]}"


def branch_slug(branch_name: str) -> str:
    """Slugify a branch, refusing one that lands in the frozen namespace.

    A branch may be named anything, including the exact shape a frozen
    preview is published under — and deploying it would take over that
    preview's directory, ports and URL.
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


def ports_for_slug(slug: str, api_base: int, web_base: int, port_range: int):
    offset = int(hashlib.sha256(slug.encode()).hexdigest()[:8], 16) % port_range
    return api_base + offset, web_base + offset


def read_owner(preview_dir: Path) -> dict | None:
    """Return the recorded owner, or ``None`` when nothing occupies this slug.

    An unreadable record is neither: it refuses, because treating it as
    unoccupied is how a candidate under review gets overwritten.
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
    retry, and is what makes a lost dispatch safe to repeat. Anything else
    would replace what some reviewer is looking at.
    """
    expected_id = require_dispatch_id(dispatch_id)
    expected_sha = require_commit_sha(commit_sha)
    existing = read_owner(preview_dir)
    if existing is None:
        return "create"
    if existing["yoke_dispatch_id"] != expected_id:
        raise FrozenPreviewError(
            "ownership_mismatch",
            "preview occupancy is owned by a different yoke_dispatch_id. Do not "
            "overwrite.",
        )
    if existing["commit_sha"] != expected_sha:
        raise FrozenPreviewError(
            "occupancy_conflict",
            f"this occupancy already serves {existing['commit_sha']}, not "
            f"{expected_sha}; a frozen preview is not redeployed onto a "
            "different candidate.",
        )
    return "reuse"


def claim(preview_dir: Path, dispatch_id: str, commit_sha: str) -> str:
    """Check, then record — one call, because they are one decision.

    Split across two workflow steps, an interruption between them leaves an
    occupancy nobody owns.
    """
    outcome = assert_reuse_or_refuse(preview_dir, dispatch_id, commit_sha)
    write_owner(preview_dir, dispatch_id, commit_sha)
    return outcome


def assert_unreserved(slug: str) -> None:
    """Refuse a branch occupancy inside the frozen namespace.

    The caller resolving the slug already refuses this; the deploy refuses it
    again rather than trusting whoever called it.
    """
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
                "cleanup named a yoke_dispatch_id but this occupancy has no "
                "frozen owner.",
            )
        return
    if live["yoke_dispatch_id"] != named:
        # Covers both ways a caller can fail to own this: naming the wrong
        # identity, and naming none at all — a branch teardown reaching a
        # frozen occupancy.
        raise FrozenPreviewError(
            "ownership_mismatch",
            f"this occupancy is owned by a frozen preview, and "
            f"{named or 'no yoke_dispatch_id'} does not match its owner. "
            "Recovery: tear it down with the yoke_dispatch_id it was created "
            "under.",
        )


def resolve_dispatch(
    *,
    commit_sha: str = "",
    yoke_dispatch_id: str = "",
    branch_name: str = "",
    github_sha: str = "",
    api_base: int,
    web_base: int,
    port_range: int,
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
    api_port, web_port = ports_for_slug(slug, api_base, web_base, port_range)
    return {
        "mode": mode,
        "candidate_sha": sha,
        "occupancy_slug": slug,
        "yoke_dispatch_id": token,
        "api_port": str(api_port),
        "web_port": str(web_port),
        "branch_exists": "true",
    }


def _emit(mapping: dict) -> None:
    for key, value in mapping.items():
        line = f"{key}={value}"
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in line):
            raise FrozenPreviewError(
                "unsafe_token", "refusing output with a control character"
            )
        print(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen preview occupancy guard")
    sub = parser.add_subparsers(dest="command", required=True)
    resolve = sub.add_parser("resolve")
    for flag in ("--commit-sha", "--yoke-dispatch-id", "--branch", "--github-sha"):
        resolve.add_argument(flag, default="")
    resolve.add_argument("--api-base", type=int, required=True)
    resolve.add_argument("--web-base", type=int, required=True)
    resolve.add_argument("--port-range", type=int, required=True)
    owned = sub.add_parser("claim")
    owned.add_argument("--preview-dir", required=True)
    owned.add_argument("--yoke-dispatch-id", required=True)
    owned.add_argument("--commit-sha", required=True)
    unreserved = sub.add_parser("assert-unreserved")
    unreserved.add_argument("--slug", required=True)
    cleanup = sub.add_parser("check-cleanup")
    cleanup.add_argument("--preview-dir", required=True)
    cleanup.add_argument("--yoke-dispatch-id", default="")
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
                    api_base=args.api_base,
                    web_base=args.web_base,
                    port_range=args.port_range,
                )
            )
        elif args.command == "claim":
            print(
                claim(Path(args.preview_dir), args.yoke_dispatch_id, args.commit_sha)
            )
        elif args.command == "assert-unreserved":
            assert_unreserved(args.slug)
            print("ok")
        elif args.command == "check-cleanup":
            assert_cleanup_owner(Path(args.preview_dir), args.yoke_dispatch_id)
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

"""Validate the complete public corpus and its exact candidate identity."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess

from yoke_cli.transport.response_evidence import wrapped_lines
from yoke_contracts.project_contract.install_manifest import (
    PACKAGED_INSTALL_BUNDLE_TREE_REL,
)
from yoke_core.domain import documentation_links as links
from yoke_core.domain import documentation_navigation as nav
from yoke_core.domain.documentation_render import render_page


@dataclass(frozen=True)
class CorpusRefusal:
    code: str
    target: str
    detail: str
    repair: str

    def __str__(self) -> str:
        return f"{self.code} {self.target}: {self.detail}. Repair: {self.repair}"


# Public examples use placeholders, never a person's home, capture or identity.
_HEX = "[0-9a-fA-F]"
_PRIVATE = (
    re.compile(r"/(?:" + "Users|home" + r")/(?!(?:me|user|username)/)[A-Za-z0-9._-]+/"),
    re.compile(r"[A-Za-z]:\\\\?" + "Users" + r"\\"),
    re.compile("Mobile " + "Documents|com~apple~" + "CloudDocs"),
    re.compile(r"(?<![\w.])/(?:private/var|var/folders)/(?![.<])[A-Za-z0-9_-]+/"),
    re.compile(
        r"(?:session|user|machine)[ _-]?(?:id|identity)[\"\' ]*[:=][\"\' ]*"
        rf"(?!00000000-0000-0000-0000-){_HEX}{{8}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{12}}\b",
        re.I,
    ),
)
_COMMIT = re.compile(r"[0-9a-f]{40}")
_IDENTITY_REPAIR = "rebuild from the declared full candidate commit"
_PROOF_REPAIR = (
    "rebuild the consumer from the declared full commit and supply its evidence"
)


def _size(path: Path, text: str) -> list[CorpusRefusal]:
    count = wrapped_lines(text)
    return (
        [
            CorpusRefusal(
                "OVERSIZED_PAGE",
                str(path),
                f"{count} wrapped lines exceeds 350",
                "split the page at meaningful topic boundaries and regenerate its copies",
            )
        ]
        if count > 350
        else []
    )


def validate_public_corpus(root: Path) -> list[CorpusRefusal]:
    """Use tracked source pages, or present pages in materialized trees."""
    root = Path(root)
    refusals = [
        CorpusRefusal(r.code, r.target, r.detail, r.repair)
        for r in nav.validate_navigation(root, complete=True)
    ]
    try:
        pages = sorted(nav._tracked_pages(root))
    except (OSError, subprocess.SubprocessError):
        return refusals  # Navigation already reports unavailable tracked ownership.
    refusals.extend(
        CorpusRefusal(r.code, r.target, r.detail, r.repair)
        for r in links.validate_links(root, pages)
    )
    try:
        tree = nav.load_navigation(root)
    except nav.NavigationError:
        tree = None
    nodes = {n.path: n for n in nav.iter_nodes(tree)} if tree else {}
    for path in public_corpus_files(root):
        page = path.relative_to(root.resolve()).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue  # The link validator owns the unreadable-page refusal.
        if path.suffix == ".md":
            refusals.extend(_size(path, text))
        if any(pattern.search(text) for pattern in _PRIVATE[:-1]) or any(
            _PRIVATE[-1].search(line)
            and not re.search(r"\b(example|synthetic|schema)\b", line, re.I)
            for line in text.splitlines()
        ):
            refusals.append(
                CorpusRefusal(
                    "PRIVATE_CONTENT",
                    str(path),
                    "private path or identifier in public teaching",
                    "replace private material with portable placeholders and rebuild",
                )
            )
        if tree and page in nodes:
            try:
                current = render_page(tree, nodes[page], text)
            except ValueError as exc:
                refusals.append(
                    CorpusRefusal("NAV_SCHEMA", page, str(exc), "add a Markdown H1")
                )
                continue
            if current != text:
                refusals.append(
                    CorpusRefusal(
                        "STALE_NAV_BLOCK",
                        page,
                        "derived navigation blocks differ",
                        "run documentation_render write against the complete source corpus",
                    )
                )
    return refusals


def public_corpus_files(root: Path) -> list[Path]:
    """Tracked source payloads and present snapshot payloads share one boundary."""
    root = root.resolve()
    repo = root.parent.parent
    if root == repo / "docs/public" and (repo / ".git").exists():
        result = _git(repo, "ls-files", "-z", "--", "docs/public")
        if result.returncode:
            raise OSError("tracked public files unavailable")
        return [repo / p for p in result.stdout.decode().split("\0") if p]
    return sorted(p for p in root.rglob("*") if p.is_file())


def validate_published_copies(repo: Path) -> list[CorpusRefusal]:
    """Inspect every copy, including extras and oversized generated pages."""
    source = repo / "docs/public"
    try:
        expected = {
            p.relative_to(source): p.read_bytes() for p in public_corpus_files(source)
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return [
            CorpusRefusal(
                "CORPUS_READ_FAILED",
                str(source),
                str(exc),
                "restore readable source files and git metadata, then retry",
            )
        ]
    refusals = []
    for root in (
        repo / ".yoke/docs",
        repo / PACKAGED_INSTALL_BUNDLE_TREE_REL / "docs/public",
    ):
        actual = {p.relative_to(root): p for p in root.rglob("*") if p.is_file()}
        for name in sorted(set(expected) | set(actual)):
            path = root / name
            if (
                name not in expected
                or name not in actual
                or path.read_bytes() != expected[name]
            ):
                refusals.append(
                    CorpusRefusal(
                        "STALE_GENERATED_COPY",
                        str(path),
                        "copy differs from the public source",
                        "run install_bundle_tree_sync sync from the validated source checkout",
                    )
                )
            if name.suffix == ".md" and name in actual:
                refusals.extend(_size(path, path.read_text(encoding="utf-8")))
    return refusals


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, timeout=10
    )


def _consumer_proof(path: Path | None, commit: str) -> list[CorpusRefusal]:
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path else None
        valid = (
            isinstance(value, dict)
            and path is not None
            and path.name == "yoke-docs-build-evidence.json"
            and set(value) == {"consumer", "source_commit", "built_at"}
            and all(isinstance(v, str) and v for v in value.values())
            and _COMMIT.fullmatch(value["source_commit"])
            and value["source_commit"] == commit
            and re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value["built_at"]
            )
        )
        if valid:
            datetime.fromisoformat(value["built_at"].replace("Z", "+00:00"))
            return []
    except (OSError, ValueError, TypeError):
        value = "unreadable evidence"
    value = value.get("source_commit") if isinstance(value, dict) else None
    value = str(value) if _COMMIT.fullmatch(str(value)) else "malformed evidence"
    return [
        CorpusRefusal(
            "CONSUMER_PROOF_MISSING",
            str(path or "consumer_evidence"),
            f"expected consumer proof for {commit}; received {value!r}",
            _PROOF_REPAIR,
        )
    ]


def verify_candidate(
    repo: Path,
    declared_commit: str,
    *,
    receipt: Path | None = None,
    consumer_evidence: Path | None = None,
) -> list[CorpusRefusal]:
    """Refuse ambient or stale identity; the producer contract owns the format."""
    from yoke_core.domain import install_bundle_project as project

    repo = Path(repo)
    refusals = _consumer_proof(consumer_evidence, declared_commit)

    def mismatch(target, detail, repair=_IDENTITY_REPAIR):
        refusals.append(
            CorpusRefusal("CANDIDATE_IDENTITY_MISMATCH", str(target), detail, repair)
        )

    try:
        if (
            not _COMMIT.fullmatch(declared_commit)
            or _git(repo, "cat-file", "-e", f"{declared_commit}^{{commit}}").returncode
        ):
            mismatch("declared_commit", repr(declared_commit))
            return refusals
        head = _git(repo, "rev-parse", "HEAD").stdout.decode().strip()
        if head != declared_commit:
            mismatch("HEAD", f"{head!r} differs from {declared_commit}")
        try:
            proven = project.proven_source_build(repo, require_clean=True)
            if proven != declared_commit:
                mismatch(
                    repo,
                    f"proven source_build {proven!r} differs from {declared_commit}",
                )
        except project.CandidateIdentityError as exc:
            mismatch(
                ", ".join(exc.paths),
                "served source tree is dirty",
                "commit or discard the listed changes and rebuild from the declared full candidate commit",
            )
        status = _git(repo, "status", "--porcelain", "--untracked-files=all")
        if status.returncode:
            mismatch(repo, "cannot prove clean checkout state")
        elif status.stdout and not any(
            r.detail == "served source tree is dirty" for r in refusals
        ):
            paths = [line[3:] for line in status.stdout.decode().splitlines()]
            mismatch(
                ", ".join(paths),
                "served source tree is dirty",
                "commit or discard the listed changes and rebuild from the declared full candidate commit",
            )
        if receipt:
            try:
                value = json.loads(receipt.read_text(encoding="utf-8"))
                build = value.get("source_build") if isinstance(value, dict) else None
            except (OSError, ValueError):
                build = None
            if build != declared_commit:
                mismatch(
                    receipt, f"source_build {build!r} differs from {declared_commit}"
                )
        files = _git(
            repo, "ls-tree", "-r", "--name-only", declared_commit, "--", "docs/public"
        )
        if files.returncode:
            mismatch(repo, "cannot enumerate declared source corpus")
            return refusals
        expected = {
            p.removeprefix("docs/public/") for p in files.stdout.decode().splitlines()
        }
        if not expected:
            mismatch("docs/public", "declared commit contains no public corpus")
        for root in (
            repo / ".yoke/docs",
            repo / PACKAGED_INSTALL_BUNDLE_TREE_REL / "docs/public",
        ):
            actual = {
                p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
            }
            for name in sorted(expected | actual):
                path = root / name
                blob = _git(repo, "show", f"{declared_commit}:docs/public/{name}")
                if (
                    name not in expected
                    or not path.is_file()
                    or blob.returncode
                    or path.read_bytes() != blob.stdout
                ):
                    mismatch(
                        path,
                        f"published bytes differ from {declared_commit}:docs/public/{name}",
                    )
    except (OSError, subprocess.SubprocessError) as exc:
        mismatch(repo, f"candidate identity could not be read: {exc}")
    return refusals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "verify-candidate"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--consumer-evidence", type=Path)
    args = parser.parse_args(argv)
    if args.command == "verify-candidate":
        if not args.commit:
            parser.error("verify-candidate requires --commit")
        refusals = verify_candidate(
            args.root,
            args.commit,
            receipt=args.receipt,
            consumer_evidence=args.consumer_evidence,
        )
    else:
        refusals = validate_public_corpus(args.root)
    for refusal in refusals:
        print(refusal)
    if not refusals:
        print("PASS complete corpus candidate validation")
    return int(bool(refusals))


if __name__ == "__main__":
    raise SystemExit(main())

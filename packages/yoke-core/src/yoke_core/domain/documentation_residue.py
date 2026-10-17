"""Find retired documentation references in the current tracked repository."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

from yoke_core.domain.documentation_links import links, resolve_link
from yoke_core.domain.install_bundle_docs_validation import CorpusRefusal

_RETIRED_FILES = frozenset(
    name + ".md"
    for name in (
        "cli-and-config items-and-sessions events-doctor-ouroboros actors-members-billing "
        "databases-and-migrations operator-data-repair private-forks windows-wsl "
        "operating-with-agents concepts modes install qa delivery github projects "
        "strategy frontier workflows capabilities"
    ).split()
)
_PREFIXES = ("docs/" + "public/", ".yoke/" + "docs/")
_DEFERRED = "Enforcement of this teaching " + "is deferred."
_PACKED = "packages/yoke-core/src/yoke_core/install_bundle_tree/"


def _retired(path: str) -> bool:
    return path.startswith(("reference/", "guides/")) or path in _RETIRED_FILES


def _excluded(path: str) -> bool:
    canonical = path.removeprefix(_PACKED)
    return (
        path.startswith("docs/archive/")
        or re.match(r"^packs/[^/]+/versions/[^/]+/", canonical) is not None
        or path
        in {
            ".test_durations",
            "packages/yoke-cli/src/yoke_cli/project_install/released_bundle_hashes.json",
        }
    )


def scan_retired_references(repo: Path) -> list[CorpusRefusal]:
    """Scan tracked content, excluding only historical owners and timing data."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return [
            CorpusRefusal(
                "CORPUS_READ_FAILED",
                str(repo),
                "tracked content unavailable",
                "restore readable git metadata and retry",
            )
        ]
    refusals = []
    pattern = re.compile(
        "(?:" + "|".join(re.escape(p) for p in _PREFIXES) + r")([^\s`\"'<>\]\)]+)"
    )
    for path in result.stdout.decode().split("\0"):
        if not path or _excluded(path):
            continue
        try:
            text = (repo / path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            retired = any(
                _retired(m.group(1).split("#")[0].split("?")[0])
                for m in pattern.finditer(line)
            )
            old_nav = path == "docs/public/nav.yaml" and re.search(
                r"^\s*(sections|pages)\s*:", line
            )
            if retired or old_nav or _DEFERRED in line:
                refusals.append(
                    CorpusRefusal(
                        "RETIRED_REFERENCE",
                        f"{path}:{number}",
                        "retired documentation reference or teaching",
                        "cite the current concept-tree home and enforcing verification command",
                    )
                )
        if path.startswith("docs/public/") and path.endswith(".md"):
            page = path.removeprefix("docs/public/")
            for link in links(text):
                try:
                    resolved = resolve_link(page, link.target)
                except ValueError:
                    continue  # Public link validation owns escapes.
                if not resolved.external and _retired(resolved.path):
                    refusals.append(
                        CorpusRefusal(
                            "RETIRED_REFERENCE",
                            path,
                            f"relative link {link.target!r} resolves to a retired page",
                            "link directly to the current concept-tree home",
                        )
                    )
    return refusals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    refusals = scan_retired_references(args.root)
    for refusal in refusals:
        print(refusal)
    if not refusals:
        print("PASS no retired documentation references in tracked content")
    return int(bool(refusals))


if __name__ == "__main__":
    raise SystemExit(main())

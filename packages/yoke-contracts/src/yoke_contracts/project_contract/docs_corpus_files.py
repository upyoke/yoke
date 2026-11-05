"""Single owner of the public documentation corpus file allowlist."""

from dataclasses import dataclass
import re

ALLOWED_CORPUS_FILES = re.compile(
    r"(?:.*\.md|nav\.yaml|assets/[a-z0-9/._-]+\.(?:css|svg|html)|"
    r"materialization\.json|yoke-docs-build-evidence\.json)"
)


@dataclass(frozen=True)
class CorpusRefusal:
    code: str
    target: str
    detail: str
    repair: str

    def __str__(self) -> str:
        return f"{self.code} {self.target}: {self.detail}. Repair: {self.repair}"


def refuse_unexpected_file(rel: str, *, symlink: bool = False) -> list[CorpusRefusal]:
    """Return a diagnosed refusal for unsupported files, including symlinks."""
    if not symlink and ALLOWED_CORPUS_FILES.fullmatch(rel):
        return []
    return [CorpusRefusal(
        "DOCS_CORPUS_UNEXPECTED_FILE", rel,
        "symlinks are not allowed" if symlink else "file is outside the public corpus allowlist",
        "remove it from docs/public",
    )]

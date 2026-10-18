"""Coverage evidence a yoke-ci run publishes when it executes the suite.

A run's ``head_sha`` names the event's head, which is not the commit a pull
request run checks out: that is GitHub's synthetic merge of head and base.
The evidence therefore names the commit and tree the shards actually test,
the run and attempt that test them, and the interpreter coverage the matrix
executes. The artifact name carries the tree, so a later run with the same
tree finds candidate evidence with one exact-name lookup.
:class:`GitHubArtifacts` reads it back without sending the API token to the
storage host an artifact download redirects to.

The ``reuse-coverage`` job publishes it once it decides to run the suite.
Every matrix cell then executes pytest, so the evidence counts as completed
coverage only after its recorded attempt concludes ``success``; a failed,
cancelled or unfinished attempt covers nothing. A run that reuses coverage
publishes none, so every reuse points at an original executed proof and its
age cannot be renewed through a chain of reuses.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

from yoke_core.tools import ci_shards


SCHEMA = 1
ARTIFACT_PREFIX = "yoke-ci-coverage-"
EVIDENCE_FILE = "yoke-ci-coverage.json"
NEWEST_SCOPE = "all"
OLDER_SCOPE = "interpreter"
HTTP_TIMEOUT_S = 30
FETCH_ERRORS = (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError)


def artifact_name(tree: str) -> str:
    """The exact artifact name that holds evidence for *tree*."""
    return f"{ARTIFACT_PREFIX}{tree}"


def required_coverage() -> dict[str, Any]:
    """The interpreter scopes and shard count a complete suite run covers."""
    versions = ci_shards.python_versions()
    return {
        "python": {
            version: NEWEST_SCOPE if version == versions[-1] else OLDER_SCOPE
            for version in versions
        },
        "shards": ci_shards.SHARD_COUNT,
    }


def _git(worktree: str | Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()


def build_evidence(
    worktree: str | Path, *, run_id: int, run_attempt: int
) -> dict[str, Any]:
    """Evidence for the commit checked out in *worktree*."""
    return {
        "schema": SCHEMA,
        "commit": _git(worktree, "rev-parse", "HEAD"),
        "tree": _git(worktree, "rev-parse", "HEAD^{tree}"),
        "run_id": run_id,
        "run_attempt": run_attempt,
        "coverage": required_coverage(),
    }


def evidence_refusal(
    evidence: Any,
    *,
    candidate_tree: str,
    run_id: int,
    required: Mapping[str, Any],
) -> Optional[str]:
    """Why *evidence* cannot cover *candidate_tree*, or None when it can."""
    if not isinstance(evidence, dict) or evidence.get("schema") != SCHEMA:
        return "unreadable_evidence"
    if evidence.get("tree") != candidate_tree:
        return "evidence_tree_mismatch"
    if not str(evidence.get("commit") or "").strip():
        return "evidence_commit_missing"
    if evidence.get("run_id") != run_id:
        return "evidence_run_mismatch"
    attempt = evidence.get("run_attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        return "evidence_attempt_missing"
    if evidence.get("coverage") != dict(required):
        return "incomplete_coverage"
    return None


class _NoRedirect(HTTPRedirectHandler):
    """Artifact downloads redirect to storage that must not see the token."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


default_opener = build_opener(_NoRedirect).open


@dataclass(frozen=True)
class GitHubArtifacts:
    """Read-only GitHub API access to runs and their evidence artifacts."""

    api_url: str
    repository: str
    token: str
    opener: Callable[..., Any]

    def _request(self, url: str, *, authorized: bool = True) -> bytes:
        headers = {"User-Agent": "yoke-ci-coverage-evidence"}
        if authorized:
            headers.update(
                {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
            )
        request = Request(url, headers=headers, method="GET")
        with self.opener(request, timeout=HTTP_TIMEOUT_S) as response:
            return response.read()

    def get_json(self, path: str) -> Any:
        url = f"{self.api_url.rstrip('/')}/repos/{self.repository}/{path}"
        return json.loads(self._request(url).decode("utf-8"))

    def download(self, url: str) -> bytes:
        """Follow one storage redirect without forwarding the token."""
        try:
            return self._request(url)
        except HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers else None
            if exc.code not in (301, 302, 303, 307, 308) or not location:
                raise
        return self._request(location, authorized=False)

    def read_evidence(self, artifact: Mapping[str, Any]) -> Any:
        archive = self.download(str(artifact.get("archive_download_url") or ""))
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            return json.loads(bundle.read(EVIDENCE_FILE).decode("utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", default=".")
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--write-github-output", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        run_id = int(os.environ["GITHUB_RUN_ID"])
        run_attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])
    except (KeyError, ValueError):
        raise SystemExit(
            "coverage_evidence_run_identity_missing: GITHUB_RUN_ID and "
            "GITHUB_RUN_ATTEMPT must be set; publish evidence only from a "
            "yoke-ci job."
        )
    evidence = build_evidence(args.worktree, run_id=run_id, run_attempt=run_attempt)
    path = Path(args.output_dir) / EVIDENCE_FILE
    path.write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8")
    name = artifact_name(evidence["tree"])
    print(f"artifact_name={name}")
    print(path.read_text(encoding="utf-8"))
    output = os.environ.get("GITHUB_OUTPUT") if args.write_github_output else None
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"artifact_name={name}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_PREFIX",
    "EVIDENCE_FILE",
    "FETCH_ERRORS",
    "GitHubArtifacts",
    "artifact_name",
    "build_evidence",
    "evidence_refusal",
    "main",
    "required_coverage",
]

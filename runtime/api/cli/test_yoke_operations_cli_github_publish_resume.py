"""Idempotent repo-create on resume for the GitHub publish boundary.

When a make-it-mine onboarding run is re-run after the prior run already
created the GitHub repo (but its push had not landed), the create POST returns
422 ("name already exists"). ``create_repo`` treats that as a resume signal: it
GETs the existing repo, probes its commits, and reuses an EMPTY repo (the
prior run's half-finished work) while refusing a populated one. The network is
mocked at the ``urllib.request.urlopen`` seam so no scenario hits GitHub.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from yoke_cli.config import github_publish


class _FakeResponse(io.BytesIO):
    """A urlopen context manager returning canned JSON bytes."""

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


def _http_error(url: str, status: int, message: str) -> urllib.error.HTTPError:
    """Build an HTTPError whose body carries GitHub's ``message`` field.

    ``github_publish._error_detail`` calls ``exc.read()``, so the error needs a
    readable file object — the same shape urllib hands the caller on a non-2xx.
    """
    body = io.BytesIO(json.dumps({"message": message}).encode("utf-8"))
    return urllib.error.HTTPError(url, status, message, {}, body)


class _Recorder:
    """Replays a queued JSON response or error by path suffix.

    ``responses`` maps a path suffix to the JSON body for a 2xx reply; ``errors``
    maps a path suffix to a ``(status, message)`` pair that raises an
    ``HTTPError`` (so the 422/409 branches can be exercised). The error map is
    consulted first, and the longest matching suffix wins so a specific path
    (e.g. ``.../commits``) is not shadowed by a shorter prefix of it.
    """

    def __init__(
        self,
        responses: dict[str, Any],
        *,
        errors: dict[str, tuple[int, str]] | None = None,
    ) -> None:
        self._responses = responses
        self._errors = errors or {}
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request, timeout: float = 0.0):
        body = request.data.decode("utf-8") if request.data else None
        self.requests.append({
            "url": request.full_url,
            "method": request.get_method(),
            "body": json.loads(body) if body else None,
        })
        url_path = request.full_url.split("?", 1)[0]
        error_match = self._longest_suffix(url_path, self._errors)
        if error_match is not None:
            status, message = self._errors[error_match]
            raise _http_error(request.full_url, status, message)
        success_match = self._longest_suffix(url_path, self._responses)
        if success_match is not None:
            payload = self._responses[success_match]
            return _FakeResponse(json.dumps(payload).encode("utf-8"))
        raise AssertionError(f"no canned response for {request.full_url}")

    @staticmethod
    def _longest_suffix(url_path: str, mapping: dict[str, Any]) -> str | None:
        matches = [path for path in mapping if url_path.endswith(path)]
        return max(matches, key=len) if matches else None


def _install(monkeypatch, recorder: _Recorder) -> None:
    monkeypatch.setattr(github_publish.urllib.request, "urlopen", recorder)


def test_create_repo_reuses_empty_repo_on_name_exists(monkeypatch) -> None:
    # A resume after a prior run created the repo (push hadn't landed): the
    # create POST 422s, the repo is empty (commits 409), so it is reused.
    recorder = _Recorder(
        {
            "/repos/octocat/widget": {
                "full_name": "octocat/widget",
                "private": True,
                "clone_url": "https://github.com/octocat/widget.git",
                "ssh_url": "git@github.com:octocat/widget.git",
                "html_url": "https://github.com/octocat/widget",
                "default_branch": "main",
            },
        },
        errors={
            "/user/repos": (422, "name already exists on this account"),
            "/repos/octocat/widget/commits": (409, "Git Repository is empty"),
        },
    )
    _install(monkeypatch, recorder)

    reused = github_publish.create_repo(
        "https://api.github.com", "ghp_x",
        owner="octocat", name="widget", user_login="octocat",
    )

    assert reused == {
        "full_name": "octocat/widget",
        "private": True,
        "clone_url": "https://github.com/octocat/widget.git",
        "ssh_url": "git@github.com:octocat/widget.git",
        "html_url": "https://github.com/octocat/widget",
        "default_branch": "main",
        # The 422 resume path flags the summary as reused so the report can name
        # that the repo already existed rather than was created this run.
        "reused": True,
    }
    # POST create -> GET repo -> GET commits.
    methods = [(r["method"], r["url"]) for r in recorder.requests]
    assert methods[0][0] == "POST"
    assert methods[0][1].endswith("/user/repos")
    assert methods[1][1].endswith("/repos/octocat/widget")
    assert methods[2][1].endswith("/repos/octocat/widget/commits")


def test_create_repo_fresh_create_is_not_flagged_reused(monkeypatch) -> None:
    # The happy-path fresh create reports reused=False so a first run's report
    # reads as a fresh create, never as a resume.
    recorder = _Recorder(
        {
            "/user/repos": {
                "full_name": "octocat/widget",
                "private": True,
                "default_branch": "main",
            },
        },
    )
    _install(monkeypatch, recorder)

    created = github_publish.create_repo(
        "https://api.github.com", "ghp_x",
        owner="octocat", name="widget", user_login="octocat",
    )

    assert created["full_name"] == "octocat/widget"
    assert created["reused"] is False
    # Only the create POST ran — no reuse probe.
    assert [r["method"] for r in recorder.requests] == ["POST"]


def test_create_repo_reuses_empty_repo_when_commits_list_empty(monkeypatch) -> None:
    # GitHub may answer the commits probe with 200 + [] instead of 409; that is
    # still an empty repo and must be reused.
    recorder = _Recorder(
        {
            "/repos/octocat/widget": {
                "full_name": "octocat/widget",
                "private": True,
                "default_branch": "main",
            },
            "/repos/octocat/widget/commits": [],
        },
        errors={"/user/repos": (422, "name already exists on this account")},
    )
    _install(monkeypatch, recorder)

    reused = github_publish.create_repo(
        "https://api.github.com", "ghp_x",
        owner="octocat", name="widget", user_login="octocat",
    )

    assert reused["full_name"] == "octocat/widget"
    assert reused["default_branch"] == "main"


def test_create_repo_refuses_populated_repo_on_name_exists(monkeypatch) -> None:
    # A pre-existing repo with content is never adopted — a clear, recovery
    # shaped error fires instead of pushing into someone's populated repo.
    recorder = _Recorder(
        {
            "/repos/octocat/widget": {
                "full_name": "octocat/widget",
                "private": True,
                "default_branch": "main",
            },
            "/repos/octocat/widget/commits": [{"sha": "abc123"}],
        },
        errors={"/user/repos": (422, "name already exists on this account")},
    )
    _install(monkeypatch, recorder)

    with pytest.raises(github_publish.GitHubPublishError) as caught:
        github_publish.create_repo(
            "https://api.github.com", "ghp_x",
            owner="octocat", name="widget", user_login="octocat",
        )

    assert "already exists and has content" in str(caught.value)


def test_create_repo_propagates_non_422_create_error(monkeypatch) -> None:
    # A non-422 create failure (e.g. 403 forbidden) is not a name collision and
    # must not trigger the reuse probe — it propagates unchanged.
    recorder = _Recorder(
        {},
        errors={"/user/repos": (403, "Resource not accessible by token")},
    )
    _install(monkeypatch, recorder)

    with pytest.raises(github_publish.GitHubPublishError) as caught:
        github_publish.create_repo(
            "https://api.github.com", "ghp_x",
            owner="octocat", name="widget", user_login="octocat",
        )

    assert caught.value.status == 403
    # Only the create POST was attempted; no GET-repo/commits probe followed.
    assert [r["method"] for r in recorder.requests] == ["POST"]


def test_publish_error_status_defaults_to_none() -> None:
    # The status attribute is additive: errors raised without it read None, so
    # existing call sites keep working.
    err = github_publish.GitHubPublishError("boom")
    assert err.status is None

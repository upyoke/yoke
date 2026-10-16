"""Annotated tag writes bind exact source and note without moving references."""

from yoke_core.domain.handlers import github_release_tag as subject
from yoke_core.domain.gh_rest_transport_errors import RestTransportError
import pytest


def test_annotated_tag_writes_exact_commit_and_note(monkeypatch):
    posts = []

    def post(path, **kwargs):
        posts.append((path, kwargs))
        return {"sha": "b" * 40}

    monkeypatch.setattr(subject, "rest_post", post)
    subject._create_annotated_tag(
        "owner/repo", "0.2.0.202610140941", "a" * 40, "Note", "token"
    )
    assert posts[0][1]["body"] == {
        "tag": "0.2.0.202610140941",
        "message": "Yoke 0.2.0.202610140941\n\nNote",
        "object": "a" * 40,
        "type": "commit",
    }
    assert posts[1][1]["body"] == {
        "ref": "refs/tags/0.2.0.202610140941",
        "sha": "b" * 40,
    }
    assert all(p[1]["max_attempts"] == 1 for p in posts)
    assert all("force" not in p[1]["body"] for p in posts)


def test_invalid_tag_object_never_creates_ref(monkeypatch):
    posts = []
    monkeypatch.setattr(
        subject, "rest_post", lambda path, **kw: posts.append(path) or {}
    )
    with pytest.raises(RestTransportError, match="omitted its SHA"):
        subject._create_annotated_tag(
            "owner/repo", "0.2.0.202610140941", "a" * 40, "Note", "token"
        )
    assert len(posts) == 1

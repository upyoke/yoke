"""GitHub repository replay fixture for resumable onboarding tests."""

from __future__ import annotations

import io
import json
import urllib.error


class CreateRepoReplay:
    """Replay a fresh repository create followed by its idempotent resume."""

    def __init__(self) -> None:
        self.calls = 0

    def first_pass(self):
        self.calls = 0
        return self

    def resume_pass(self):
        self.calls = 1
        return self

    def __call__(self, request, timeout: float = 0.0):
        url_path = request.full_url.split("?", 1)[0]
        if url_path.endswith("/user/repos"):
            if self.calls == 0:
                return self._ok({
                    "full_name": "octocat/widget",
                    "private": True,
                    "default_branch": "main",
                })
            raise self._error(request.full_url, 422, "name already exists")
        if url_path.endswith("/octocat/widget/commits"):
            raise self._error(request.full_url, 409, "Git Repository is empty")
        if url_path.endswith("/repos/octocat/widget"):
            return self._ok({
                "full_name": "octocat/widget",
                "private": True,
                "default_branch": "main",
            })
        raise AssertionError(f"unexpected GitHub call: {request.full_url}")

    @staticmethod
    def _ok(payload: dict):
        class _Resp(io.BytesIO):
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        return _Resp(json.dumps(payload).encode("utf-8"))

    @staticmethod
    def _error(url: str, status: int, message: str) -> urllib.error.HTTPError:
        body = io.BytesIO(json.dumps({"message": message}).encode("utf-8"))
        return urllib.error.HTTPError(url, status, message, {}, body)

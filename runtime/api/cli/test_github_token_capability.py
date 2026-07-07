"""Unit coverage for the non-mutating GitHub-token capability detector.

The detector keys publish-ability on two safe probes that exploit GitHub's
auth-before-validation order (422 => the permission gate passed; 403 => blocked).
Every test patches the ``request_status`` seam so no probe reaches real GitHub;
the seam returns the HTTP status the live probe would return for that path.
"""

from __future__ import annotations

from yoke_cli.config import github_token_capability as cap


def _status_seam(statuses: dict[tuple[str, str], int | None]):
    """Build a request_status seam keyed on (method, path)."""

    def _seam(api_url, path, token, *, method, body):
        return statuses.get((method, path))

    return _seam


_CREATE_PATH = "/user/repos"


def _write_path(repo: str) -> str:
    return f"/repos/{repo}/contents/.yoke-capability-probe"


# --------------------------------------------------------------------------- #
# can_create_repo / can_write_repo status mapping
# --------------------------------------------------------------------------- #


def test_can_create_422_is_true() -> None:
    seam = _status_seam({("POST", _CREATE_PATH): 422})
    assert cap.can_create_repo("https://api", "t", request_status=seam) is True


def test_can_create_403_is_false() -> None:
    seam = _status_seam({("POST", _CREATE_PATH): 403})
    assert cap.can_create_repo("https://api", "t", request_status=seam) is False


def test_can_create_other_status_is_unknown() -> None:
    seam = _status_seam({("POST", _CREATE_PATH): 500})
    assert cap.can_create_repo("https://api", "t", request_status=seam) is None


def test_can_create_network_error_is_unknown() -> None:
    seam = _status_seam({})  # returns None for the create path
    assert cap.can_create_repo("https://api", "t", request_status=seam) is None


def test_can_write_422_is_true() -> None:
    seam = _status_seam({("PUT", _write_path("me/repo")): 422})
    assert cap.can_write_repo("https://api", "t", "me/repo", request_status=seam) is True


def test_can_write_403_is_false() -> None:
    seam = _status_seam({("PUT", _write_path("me/repo")): 403})
    assert (
        cap.can_write_repo("https://api", "t", "me/repo", request_status=seam) is False
    )


def test_can_write_other_status_is_unknown() -> None:
    seam = _status_seam({("PUT", _write_path("me/repo")): 404})
    assert cap.can_write_repo("https://api", "t", "me/repo", request_status=seam) is None


def test_probe_status_swallows_seam_exceptions() -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("network exploded")

    assert (
        cap.probe_status("https://api", "/x", "t", method="GET", body=None,
                         request_status=_boom)
        is None
    )


# --------------------------------------------------------------------------- #
# detect_capability — classic (no probes)
# --------------------------------------------------------------------------- #


def _classic_verification() -> dict:
    return {
        "scopes": ["repo", "workflow"],
        "access": {
            "repos": ["me/private", "me/public"],
            "repo_details": [
                {"full_name": "me/private", "private": True,
                 "permissions": {"push": True}},
                {"full_name": "me/public", "private": False,
                 "permissions": {"push": False}},
            ],
        },
    }


def test_detect_classic_repo_scope_can_publish() -> None:
    def _fail(*_a, **_k):
        raise AssertionError("classic must not probe")

    result = cap.detect_capability(
        "https://api", "t", _classic_verification(), request_status=_fail
    )
    assert result["kind"] == "classic"
    assert result["can_create"] is True
    assert result["can_push_new"] is True
    assert result["can_publish"] is True
    # Writable comes from the real per-repo push flag, not a probe.
    assert result["writable"] == ["me/private"]
    assert result["readonly"] == ["me/public"]
    assert result["see_private"] == 1
    assert result["see_public"] == 1


def test_detect_classic_caps_readonly_display_but_keeps_full_count() -> None:
    # The connect screen is fixed-width, so the readonly display list is capped
    # (like the fine-grained branch); readonly_count carries the true size so the
    # "except" summary counts the remainder instead of understating it.
    readonly_names = [f"org/ro{i}" for i in range(10)]
    verification = {
        "scopes": ["repo", "workflow"],
        "access": {
            "repos": ["me/writable", *readonly_names],
            "repo_details": [
                {"full_name": "me/writable", "private": True,
                 "permissions": {"push": True}},
                *[
                    {"full_name": name, "private": False,
                     "permissions": {"push": False}}
                    for name in readonly_names
                ],
            ],
        },
    }

    def _fail(*_a, **_k):
        raise AssertionError("classic must not probe")

    result = cap.detect_capability(
        "https://api", "t", verification, request_status=_fail
    )
    assert result["kind"] == "classic"
    assert result["readonly"] == readonly_names[: cap._DISPLAY_LIST_CAP]
    assert result["readonly_count"] == len(readonly_names)


def test_detect_classic_no_create_scope_cannot_create() -> None:
    verification = {
        "scopes": ["workflow"],  # no repo/public_repo
        "access": {"repos": [], "repo_details": []},
    }

    def _fail(*_a, **_k):
        raise AssertionError("classic must not probe")

    result = cap.detect_capability(
        "https://api", "t", verification, request_status=_fail
    )
    assert result["can_create"] is False
    assert result["can_publish"] is False


# --------------------------------------------------------------------------- #
# detect_capability — fine-grained (probes)
# --------------------------------------------------------------------------- #


def _fine_grained_verification() -> dict:
    return {
        "scopes": [],
        "access": {
            "repos": ["me/granted", "octo/public"],
            "repo_details": [
                {"full_name": "me/granted", "private": True, "permissions": {}},
                {"full_name": "octo/public", "private": False, "permissions": {}},
            ],
        },
    }


def test_detect_fine_grained_select_repositories_cannot_publish() -> None:
    """The user's real case: create 422, all public-write 403 -> can't publish."""
    seam = _status_seam({
        ("POST", _CREATE_PATH): 422,                      # can create
        ("PUT", _write_path("octo/public")): 403,         # can't push to public
        ("PUT", _write_path("me/granted")): 422,          # writable granted repo
    })
    result = cap.detect_capability(
        "https://api", "t", _fine_grained_verification(), request_status=seam
    )
    assert result["kind"] == "fine_grained"
    assert result["can_create"] is True
    assert result["can_push_new"] is False
    assert result["can_publish"] is False
    assert result["writable"] == ["me/granted"]
    assert "octo/public" in result["readonly"]
    assert result["write_probed_count"] == 1
    assert result["write_probe_total"] == 1


def test_detect_fine_grained_all_repositories_can_publish() -> None:
    """create 422 + a public-write 422 -> "all repositories" -> can publish."""
    seam = _status_seam({
        ("POST", _CREATE_PATH): 422,                      # can create
        ("PUT", _write_path("octo/public")): 422,         # CAN push to non-granted public
        ("PUT", _write_path("me/granted")): 422,
    })
    result = cap.detect_capability(
        "https://api", "t", _fine_grained_verification(), request_status=seam
    )
    assert result["can_create"] is True
    assert result["can_push_new"] is True
    assert result["can_publish"] is True


def test_detect_fine_grained_create_blocked_cannot_publish() -> None:
    seam = _status_seam({
        ("POST", _CREATE_PATH): 403,                      # can't create
        ("PUT", _write_path("octo/public")): 422,
        ("PUT", _write_path("me/granted")): 422,
    })
    result = cap.detect_capability(
        "https://api", "t", _fine_grained_verification(), request_status=seam
    )
    assert result["can_create"] is False
    assert result["can_publish"] is False


def test_detect_fine_grained_no_public_repo_push_new_unknown() -> None:
    """With no public repo to probe, push-to-new is unknown, so publish is False."""
    verification = {
        "scopes": [],
        "access": {
            "repos": ["me/granted"],
            "repo_details": [
                {"full_name": "me/granted", "private": True, "permissions": {}},
            ],
        },
    }
    seam = _status_seam({
        ("POST", _CREATE_PATH): 422,
        ("PUT", _write_path("me/granted")): 422,
    })
    result = cap.detect_capability(
        "https://api", "t", verification, request_status=seam
    )
    assert result["can_create"] is True
    assert result["can_push_new"] is None
    assert result["can_publish"] is False

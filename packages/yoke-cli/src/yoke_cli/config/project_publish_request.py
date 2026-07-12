"""Repository publish request and post-create recovery messages."""

from __future__ import annotations

from dataclasses import dataclass, field

from yoke_contracts import github_origin


_PUSH_DENIED_SIGNATURES = (
    "write access to repository not granted",
    "permission to",
    "http 403",
    "error: 403",
)


def is_push_denied(message: str) -> bool:
    lowered = message.lower()
    return any(signature in lowered for signature in _PUSH_DENIED_SIGNATURES)


@dataclass(frozen=True)
class PublishRequest:
    """Inputs for creating a GitHub repository and pushing a checkout."""

    owner: str
    name: str
    user_login: str
    token: str | None = field(repr=False)
    api_url: str = github_origin.DEFAULT_GITHUB_API_URL
    web_url: str = github_origin.DEFAULT_GITHUB_WEB_URL
    private: bool = True
    administration_allowed: bool = False
    use_machine_github: bool = False
    create_repository: bool = True
    repository_id: int | None = None
    installation_id: int | None = None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


def post_create_push_failure_message(
    full_name: str,
    error: BaseException,
    *,
    push_denied: bool,
) -> str:
    if push_denied:
        return (
            f"GitHub created {full_name}, but the GitHub App authorization "
            "couldn't push to it. The repo is empty — delete it on GitHub, "
            "then re-run and choose Clone or an existing folder."
        )
    return (
        f"GitHub created {full_name}, but the push did not finish: {error}. "
        "Fix the connection or GitHub availability, then re-run yoke onboard "
        f"to resume the push. To start over instead, delete {full_name} on "
        "GitHub first."
    )


__all__ = [
    "PublishRequest",
    "is_push_denied",
    "post_create_push_failure_message",
]

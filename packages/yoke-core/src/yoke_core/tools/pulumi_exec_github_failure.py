"""Classify GitHub provider 401s from a Pulumi child without echoing secrets."""

from __future__ import annotations

from typing import TextIO


GITHUB_PROVIDER_UNAUTHORIZED = "github_provider_unauthorized"


class CaptureTee:
    """Forward text to a destination while retaining a copy for classification."""

    def __init__(self, destination: TextIO) -> None:
        self._destination = destination
        self._chunks: list[str] = []

    def write(self, text: str) -> int:
        self._chunks.append(text)
        written = self._destination.write(text)
        return 0 if written is None else written

    def flush(self) -> None:
        self._destination.flush()

    def getvalue(self) -> str:
        return "".join(self._chunks)


def looks_like_github_provider_unauthorized(text: str) -> bool:
    lowered = text.lower()
    if "401 bad credentials" not in lowered:
        return False
    return "api.github.com" in lowered or "provider=github" in lowered


def github_provider_unauthorized_message(project: str) -> str:
    selected = str(project or "").strip() or "<project>"
    return (
        "Pulumi GitHub repository provider authority was rejected during "
        f"refresh (cause: {GITHUB_PROVIDER_UNAUTHORIZED}). "
        "The github.Provider used a credential GitHub called invalid; this is "
        "not AWS authority and not proof that the launch GITHUB_TOKEN expired. "
        "A process token can already be accepted by GitHub while the stored "
        "provider credential is not. Restore launch authority with "
        "`yoke github status` and "
        f"`yoke projects github-binding status --project {selected} --json`. "
        "If those are healthy, replace or update the stack's github.Provider "
        "so refresh reads the process GITHUB_TOKEN, then retry."
    )


def named_github_provider_failure(project: str, text: str) -> str | None:
    if not looks_like_github_provider_unauthorized(text):
        return None
    return github_provider_unauthorized_message(project)


__all__ = [
    "CaptureTee",
    "GITHUB_PROVIDER_UNAUTHORIZED",
    "github_provider_unauthorized_message",
    "looks_like_github_provider_unauthorized",
    "named_github_provider_failure",
]

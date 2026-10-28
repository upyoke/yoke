"""Presentation helpers and structural type for GitHub onboarding screens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Protocol

from yoke_cli.config.github_machine_report import repository_scope_recommendations

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_state import _View


def success_message(report: Mapping[str, Any]) -> str:
    """Summarize a completed GitHub App connection."""
    identity = report.get("identity")
    login = str(identity.get("login") if isinstance(identity, Mapping) else "").strip()
    return (
        f"Success! Yoke GitHub App connected for {login}."
        if login
        else "Success! Yoke GitHub App connected."
    )


def success_summary_lines(report: Mapping[str, Any]) -> list[str]:
    """Compact verified facts; yoke github status owns the full access inventory."""
    identity = report.get("identity")
    app = report.get("app")
    access = report.get("access")
    permissions = report.get("permissions")
    login = (
        str(identity.get("login") or "unknown")
        if isinstance(identity, Mapping)
        else "unknown"
    )
    slug = str(app.get("slug") or "Yoke") if isinstance(app, Mapping) else "Yoke"
    installation_count = (
        len(access.get("installations") or []) if isinstance(access, Mapping) else 0
    )
    repository_count = (
        int(access.get("repo_count") or 0) if isinstance(access, Mapping) else 0
    )
    ready = bool(isinstance(permissions, Mapping) and permissions.get("usable") is True)
    return [
        f"GitHub user: {login} · App: {slug}",
        f"Access: {installation_count} installations · {repository_count} repositories",
        f"Required permissions: {'ready' if ready else 'needs attention'}",
        "Credential custody: saved owner-only on this machine.",
        *repository_scope_recommendations(report),
    ]


def success_notice_lines(report: Mapping[str, Any]) -> list[str]:
    """Carry connection facts and repository advice into the next real question."""
    return [
        success_message(report),
        *success_summary_lines(report),
        "Review repository access with `yoke github status`.",
        "Use `yoke github disconnect` to remove the saved connection.",
    ]


class MachineGithubShell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _stored_github_attempted: bool
    _stored_machine_github_api_url: str | None
    _history: list[Any]

    def _carry_detail_lines(self, lines: list[str]) -> None: ...
    def _goto(self, view: _View) -> None: ...
    def _selection_view(self, key, step, title, subtitle, rows, on_select) -> _View: ...
    def _goto_input(
        self,
        key,
        step,
        title,
        subtitle,
        *,
        placeholder,
        on_done,
        password: bool = False,
        allow_placeholder: bool = True,
        initial_value: str = "",
    ) -> None: ...
    def _goto_project_mode(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    def _step_back(self) -> None: ...
    def _render_current(self) -> None: ...

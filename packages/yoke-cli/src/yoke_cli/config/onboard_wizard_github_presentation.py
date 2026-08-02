"""Presentation helpers and structural type for GitHub onboarding screens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


def bounded_summary(values: list[str], *, total: int | None = None) -> str:
    """Render a terminal-sized sample without hiding the omitted count."""
    display_limit = 4
    actual_total = max(len(values), total or 0)
    if not values:
        return "none"
    visible = ", ".join(values[:display_limit])
    omitted = actual_total - min(len(values), display_limit)
    return f"{visible}, and {omitted} more" if omitted > 0 else visible


def success_message(report: Mapping[str, Any]) -> str:
    """Summarize a completed GitHub App connection."""
    identity = report.get("identity")
    login = str(identity.get("login") if isinstance(identity, Mapping) else "").strip()
    return (
        f"Success! Yoke GitHub App connected for {login}."
        if login
        else "Success! Yoke GitHub App connected."
    )


def success_details(report: Mapping[str, Any]) -> list[str]:
    """Build detailed verified-connection presentation lines."""
    details: list[str] = []
    identity = report.get("identity")
    if isinstance(identity, Mapping) and identity.get("login"):
        details.append(f"GitHub username: {identity['login']}")
    app = report.get("app")
    if isinstance(app, Mapping) and app.get("slug"):
        details.append(f"GitHub App: {app['slug']}")
    access = report.get("access")
    if isinstance(access, Mapping):
        installations = [
            item
            for item in access.get("installations") or []
            if isinstance(item, Mapping)
        ]
        labels = []
        for item in installations:
            account = str(item.get("account_login") or "").strip()
            if account:
                selection = str(item.get("repository_selection") or "selected")
                state = (
                    "suspended"
                    if item.get("suspended")
                    else f"{selection} repositories"
                )
                labels.append(f"{account} ({state})")
        details.append("Installed for: " + bounded_summary(labels))
        repositories = [str(item) for item in access.get("repos") or [] if str(item)]
        total = access.get("repo_count")
        details.append(
            f"Repositories available: {total if isinstance(total, int) else len(repositories)} — "
            f"{bounded_summary(repositories, total=total if isinstance(total, int) else None)}"
        )
    permissions = report.get("permissions")
    if isinstance(permissions, Mapping) and permissions.get("usable") is True:
        details.append("Required GitHub App permissions: ready.")
    details.append("Saved on this machine. Use `yoke github disconnect` to remove it.")
    return details


class MachineGithubShell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _stored_github_attempted: bool
    _stored_machine_github_api_url: str | None
    _history: list[Any]

    def _goto(self, view: _View) -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> _View: ...
    def _goto_input(
        self,
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
    async def action_back(self) -> None: ...
    def _render_current(self) -> None: ...

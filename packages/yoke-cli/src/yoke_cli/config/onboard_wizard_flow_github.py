"""Machine GitHub-token step for the ``yoke onboard`` wizard."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from yoke_cli.config import github_credentials
from yoke_cli.config import github_machine_verify
from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_machine_github
from yoke_cli.config.onboard_wizard_step_ids import STEP_GITHUB


def verify_machine_github_token(api_url: str, token: str) -> dict[str, Any]:
    """Network seam for the machine GitHub token check."""
    return github_machine_verify.verify(api_url, token)


def _wizard_steps():
    from yoke_cli.config import onboard_wizard_steps as steps

    return steps


def _success_message(verification: Mapping[str, Any]) -> str:
    identity = verification.get("identity")
    access = verification.get("access")
    permissions = verification.get("permissions")
    login = str(identity.get("login") or "") if isinstance(identity, Mapping) else ""
    owners: list[str] = []
    if isinstance(access, Mapping):
        owners = [str(owner) for owner in access.get("owners") or [] if str(owner)]
    who = login or (owners[0] if owners else "your GitHub account")
    if (
        isinstance(permissions, Mapping)
        and permissions.get("mode") == "fine_grained_non_mutating"
    ):
        return f"Success! GitHub fine-grained token connected for {who}."
    return f"Success! GitHub token connected for {who}."


def _detail_lines(verification: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    identity = verification.get("identity")
    if isinstance(identity, Mapping) and identity.get("login"):
        lines.append(f"GitHub username: {identity['login']}")
    access = verification.get("access")
    if isinstance(access, Mapping):
        owners = [str(owner) for owner in access.get("owners") or [] if str(owner)]
        repos = [str(repo) for repo in access.get("repos") or [] if str(repo)]
        if owners:
            lines.append(f"Owner of: {_bounded_join(owners, 4)}")
        lines.append(_visible_repos_line(repos, verification.get("capability")))
    capability = verification.get("capability")
    if isinstance(capability, Mapping):
        lines.extend(_capability_lines(capability))
    return lines


def _visible_repos_line(repos: list[str], capability: Any) -> str:
    line = f"Repos this token can see: {_bounded_join(repos, 4)}"
    if isinstance(capability, Mapping):
        private = capability.get("see_private")
        public = capability.get("see_public")
        if isinstance(private, int) and isinstance(public, int):
            line += f" ({private} private, {public} public)"
    return line


def _capability_lines(capability: Mapping[str, Any]) -> list[str]:
    # One line: where can this token push? Existing-repo write access and
    # new-repo publish-ability are the same question to the user, so they read as
    # one clause. The "create the repo on GitHub first" remedy is deferred to the
    # publish step (_cannot_publish_reason), shown only when the user actually
    # tries to publish a new project — no point teaching it here.
    return [_push_capability_line(capability)]


def _push_capability_line(capability: Mapping[str, Any]) -> str:
    existing = _push_existing_summary(capability)
    can_publish = capability.get("can_publish")
    if existing is None:
        if can_publish is True:
            return "Can push to new repos you create." + _push_sample_note(capability)
        if can_publish is False:
            return (
                "Can't push to any of the repos checked with this token."
                + _push_sample_note(capability)
            )
        return "Push access: couldn't check."
    if can_publish is True:
        line = f"Can push to {existing}, and to new repos."
    elif can_publish is False:
        line = f"Can push to {existing}, but not to new repos."
    else:
        line = f"Can push to {existing}."
    return line + _push_sample_note(capability)


def _push_sample_note(capability: Mapping[str, Any]) -> str:
    """Note how many repos were actually write-probed, when it was a sample.

    Each private repo needs its own write-probe API call (GitHub's per-repo
    permissions lie for fine-grained tokens), so the connect screen only checks a
    bounded number. Say so rather than imply the push list is complete.
    """
    probed = capability.get("write_probed_count")
    total = capability.get("write_probe_total")
    if isinstance(probed, int) and isinstance(total, int) and total > probed:
        return f" (checked {probed} of {total} repos)"
    return ""


def _push_existing_summary(capability: Mapping[str, Any]) -> str | None:
    """The repos the token can push to today, or None if it can push to none."""
    if capability.get("kind") == "classic":
        # A classic repo/public_repo token carries the user's own access: it can
        # push to every visible repo except the few it's only a reader on.
        if capability.get("create_private") is False:
            return "public repos you can see"
        see_total = (capability.get("see_private") or 0) + (capability.get("see_public") or 0)
        readonly = [str(repo) for repo in capability.get("readonly") or [] if str(repo)]
        if not readonly:
            return f"all {see_total} repos you can see"
        # ``readonly`` is a display sample capped upstream (github_token_capability
        # keeps at most _DISPLAY_LIST_CAP); count the "and N more" remainder from
        # ``readonly_count`` — else the "except" list understates the reader-only
        # repos and the summary over-promises push access.
        readonly_total = capability.get("readonly_count")
        if not isinstance(readonly_total, int) or readonly_total < len(readonly):
            readonly_total = len(readonly)
        return (
            f"all {see_total} you can see except "
            f"{_bounded_join_with_total(readonly, 4, readonly_total)}"
        )
    writable = [str(repo) for repo in capability.get("writable") or [] if str(repo)]
    if not writable:
        return None
    # ``writable`` is a display sample capped upstream (github_token_capability
    # keeps at most _DISPLAY_LIST_CAP); the true count lives in ``writable_count``,
    # so the remainder must be counted from it — else a token writable to 50 repos
    # wrongly reads "and 4 more".
    total = capability.get("writable_count")
    if not isinstance(total, int) or total < len(writable):
        total = len(writable)
    return _bounded_join_with_total(writable, 4, total)


def _bounded_join(items: list[str], limit: int) -> str:
    """Join the first ``limit`` items, summarizing the rest as "and N more".

    The connect screen lists owners and visible repos; a broad token can see
    dozens, which overflow the fixed-width terminal line. Capping at ``limit``
    with an explicit remainder count keeps every line on one row and still
    conveys the true scale (no silent truncation, and the same cap everywhere).
    """
    if not items:
        return "none"
    if len(items) <= limit:
        return ", ".join(items)
    return f"{', '.join(items[:limit])}, and {len(items) - limit} more"


def _bounded_join_with_total(items: list[str], limit: int, total: int) -> str:
    """Like :func:`_bounded_join`, but count the remainder from ``total``.

    For a list capped to a display sample upstream (the pushable-repo list),
    ``len(items)`` understates the real size — the "and N more" tail has to be
    computed from the true ``total`` or it lies about how many were dropped.
    """
    if not items:
        return "none"
    if total <= limit:
        return ", ".join(items[:total])
    return f"{', '.join(items[:limit])}, and {total - limit} more"


if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _stored_github_attempted: bool
    _stored_machine_github_api_url: str | None
    _stored_machine_github_token_file: str | None

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password: bool = False,
                    allow_placeholder: bool = True,
                    initial_value: str = "") -> None: ...
    def _goto_project_mode(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...


class MachineGithubFlow:
    """Machine GitHub token routing and verification screens."""

    def _goto_machine_github(self: _Shell) -> None:
        if (
            self._stored_machine_github_token_file
            and not self._stored_github_attempted
            and self.result.machine_github_verification is None
        ):
            self._stored_github_attempted = True
            self.result.machine_github_choice = onboard_machine_github.CHOICE_CONNECT
            self._verify_machine_github_token_value(
                token=None,
                token_file=self._stored_machine_github_token_file,
                token_source_kind="token_file",
                retry_source=onboard_machine_github.CHOICE_TOKEN_FILE,
            )
            return
        steps = _wizard_steps()
        self._goto(self._selection_view(
            STEP_GITHUB,
            onboard_github_copy.MACHINE_TOKEN_TITLE,
            onboard_github_copy.MACHINE_TOKEN_SUBTITLE,
            steps.MACHINE_GITHUB_ROWS, self._on_machine_github,
        ))

    def _on_machine_github(self: _Shell, choice: str) -> None:
        if choice == onboard_machine_github.CHOICE_TOKEN_FILE:
            self.result.machine_github_choice = onboard_machine_github.CHOICE_CONNECT
            self._goto_input(
                STEP_GITHUB, "Point at your GitHub token file.",
                "Yoke reads the PAT from this file and saves it owner-only on Apply.",
                placeholder="~/.yoke/secrets/github.token",
                allow_placeholder=False,
                on_done=self._after_machine_pat_file,
            )
            return
        self.result.machine_github_choice = choice
        if choice != onboard_machine_github.CHOICE_CONNECT:
            self._goto_project_mode()
            return
        self._goto_input(
            STEP_GITHUB, "Paste your GitHub token (PAT).",
            "Never shown on screen. Saved to ~/.yoke/secrets, owner-only.",
            placeholder="paste GitHub token", password=True,
            allow_placeholder=False,
            on_done=self._after_machine_pat,
        )

    def _after_machine_pat(self: _Shell, value: str) -> None:
        self._verify_machine_github_token_value(
            token=value,
            token_file=None,
            token_source_kind="prompt",
            retry_source=onboard_machine_github.CHOICE_CONNECT,
        )

    def _after_machine_pat_file(self: _Shell, value: str) -> None:
        self._verify_machine_github_token_value(
            token=None,
            token_file=value,
            token_source_kind="token_file",
            retry_source=onboard_machine_github.CHOICE_TOKEN_FILE,
        )

    def _verify_machine_github_token_value(
        self: _Shell,
        *,
        token: str | None,
        token_file: str | None,
        token_source_kind: str,
        retry_source: str,
    ) -> None:
        api_url = self._stored_machine_github_api_url or "https://api.github.com"

        def _work() -> tuple[dict[str, Any], str]:
            secret = _read_machine_github_token(token=token, token_file=token_file)
            return verify_machine_github_token(api_url, secret), secret

        def _success(result: Any) -> None:
            verification, secret = result
            self.result.machine_github_token = secret
            self.result.machine_github_token_file = token_file
            self.result.machine_github_api_url = api_url
            self.result.machine_github_token_source_kind = token_source_kind
            self.result.machine_github_verification = verification
            # A genuine machine connection is never a publish-only PAT: clear the
            # provenance flag so a later publish decline can't drop this token.
            self._publish_pat_only = False
            self._goto_machine_github_success(verification)

        def _error(exc: BaseException) -> None:
            self._goto_machine_github_error(str(exc), retry_source)

        self._run_checking(
            step=STEP_GITHUB,
            title="Checking GitHub token.",
            message="Verifying this PAT with GitHub.",
            work=_work,
            on_success=_success,
            on_error=_error,
            group="onboard-github-token",
        )

    def _goto_machine_github_success(
        self: _Shell,
        verification: dict[str, Any],
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        steps = _wizard_steps()
        details = _detail_lines(verification)
        if (
            self._stored_github_attempted
            and self.result.machine_github_token_file
            and self.result.machine_github_token_file
            == self._stored_machine_github_token_file
        ):
            details = [
                "Using existing GitHub token file from machine config.",
                *details,
            ]
        self._goto(_View(
            STEP_GITHUB,
            lambda: steps.verification_body(
                "GitHub token connected.",
                _success_message(verification),
                details,
                steps.VERIFY_OK_ROWS,
                ok=True,
            ),
            lambda _choice: self._goto_project_mode(),
        ))

    def _goto_machine_github_error(
        self: _Shell,
        message: str,
        retry_source: str = onboard_machine_github.CHOICE_CONNECT,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        steps = _wizard_steps()
        self._goto(_View(
            STEP_GITHUB,
            lambda: steps.verification_body(
                "GitHub token could not be verified.",
                message,
                ["Check the token value and GitHub PAT permissions."],
                steps.VERIFY_RETRY_ROWS,
                ok=False,
            ),
            lambda choice: self._on_machine_github_error(choice, retry_source),
        ))

    def _on_machine_github_error(self: _Shell, choice: str, retry_source: str) -> None:
        if choice == "retry":
            self._on_machine_github(retry_source)
            return
        self._goto_machine_github()


def _read_machine_github_token(*, token: str | None, token_file: str | None) -> str:
    if token_file is not None:
        return github_credentials.read_token_file(Path(token_file).expanduser())
    secret = (token or "").strip()
    if not secret:
        raise github_credentials.GitHubCredentialError("GitHub token is empty")
    return secret


__all__ = ["MachineGithubFlow", "verify_machine_github_token"]

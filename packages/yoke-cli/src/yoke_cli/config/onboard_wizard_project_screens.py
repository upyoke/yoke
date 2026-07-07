"""Project-source presentation helpers for the ``yoke onboard`` wizard.

Body builders and option rows for the project-step screens that branch off the
source-select: the "Also publish to GitHub?" follow-up, the GitHub owner picker,
and the clone-outcome / keep-upstream choices. They sit alongside the core step
builders in :mod:`onboard_wizard_steps` and reuse its ``selection_body``
primitive; splitting them out keeps each module under the authored-file line
budget. These are presentation-only — the decision graph lives in
:mod:`onboard_wizard_flow` and :mod:`onboard_wizard_flow_clone`.
"""

from __future__ import annotations

from textual.widgets import Static

from yoke_cli.config.onboard_wizard_steps import selection_body
from yoke_cli.config.onboard_wizard_widgets import SelectionRow
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_JUST_CLONE,
    CLONE_OUTCOME_MAKE_IT_MINE,
)

# "Also publish to GitHub?" — the publish step's yes/no, shared by the
# existing-folder and create-new paths. Auto-skipped upstream when a remote
# already exists.
PUBLISH_YES = "publish"
PUBLISH_NO = "keep-local"
PUBLISH_ROWS = [
    SelectionRow(PUBLISH_YES, "Yes — publish to GitHub", "create + connect the repo"),
    SelectionRow(PUBLISH_NO, "No — keep it local", "you can publish later"),
]

# "Is the repo public or private?" — shown after the clone folder. Public routes
# to the paste-URL input (the original clone path); private lists the repos the
# connected GitHub token can reach so the user picks instead of pasting.
CLONE_VISIBILITY_PUBLIC = "public"
CLONE_VISIBILITY_PRIVATE = "private"
CLONE_VISIBILITY_ROWS = [
    SelectionRow(CLONE_VISIBILITY_PUBLIC, "Public", "paste its git URL"),
    SelectionRow(CLONE_VISIBILITY_PRIVATE, "Private", "pick from your GitHub repos"),
]

# "Make the new repo public or private?" — shown after "Duplicate it" (the
# make-it-mine outcome). Sets the visibility of the new remote repo the duplicate
# is pushed to. Default is Private (first row), the safe default for a freshly
# created copy. The source is always kept as a pull-only ``upstream`` remote, so a
# private copy can still pull updates from a public original.
NEW_REPO_PRIVATE = "private"
NEW_REPO_PUBLIC = "public"
NEW_REPO_VISIBILITY_ROWS = [
    SelectionRow(NEW_REPO_PRIVATE, "Private",
                 "only you and people you add can see it"),
    SelectionRow(NEW_REPO_PUBLIC, "Public", "anyone can see it"),
]

# Clone-outcome rows (clone path only). The default selection is "Clone it"
# (first row) — it has no side effects, so it is the safe default in both
# variants.
#
# The hint set adapts to whether the connected token can push to the source
# repo. When the token CAN push, "Clone it" pushes straight back and the
# read-only-specific "Fork it" row is irrelevant; when it CANNOT, "Clone it" is
# read-only and the fork row offers a writable path with PRs back. Both variants
# only show "Fork it" when the keep_fork condition holds (github.com remote +
# connected token); see ``clone_outcome_rows``.
_CLONE_IT_WRITABLE = SelectionRow(
    CLONE_OUTCOME_JUST_CLONE, "Clone it", "push straight back to {repo}")
_CLONE_IT_READONLY = SelectionRow(
    CLONE_OUTCOME_JUST_CLONE, "Clone it", "push nowhere — read-only access to {repo}")
_DUPLICATE_IT = SelectionRow(
    CLONE_OUTCOME_MAKE_IT_MINE, "Duplicate it",
    "push to a new remote repo we'll create")
_FORK_IT = SelectionRow(
    CLONE_OUTCOME_FORK, "Fork it",
    "push to a new fork we'll create — open PRs back to {repo}")
# Writable: the token owns / can push to the source, so "Clone it" pushes back
# and there is no read-only fork affordance.
CLONE_OUTCOME_ROWS_WRITABLE = [_CLONE_IT_WRITABLE, _DUPLICATE_IT]
# Read-only: "Clone it" is read-only, and "Fork it" is offered as the writable
# path with PRs back (subject to the keep_fork condition).
CLONE_OUTCOME_ROWS_READONLY = [_CLONE_IT_READONLY, _DUPLICATE_IT, _FORK_IT]


def default_repo(remote_url: str | None) -> str | None:
    if not remote_url:
        return None
    cleaned = remote_url.removesuffix(".git")
    if cleaned.startswith("git@github.com:"):
        return cleaned.split(":", 1)[1]
    marker = "github.com/"
    if marker in cleaned:
        return cleaned.split(marker, 1)[1].strip("/")
    return None


def clone_outcome_rows(
    remote_url: str | None,
    *,
    has_token: bool = True,
    push_access: bool | None = None,
) -> list[SelectionRow]:
    """Clone-outcome rows with the source repo interpolated into the hints.

    ``push_access`` is the result of the non-mutating write probe against the
    source repo: True means the token can push to it, so the writable variant
    (Clone it pushes back; no read-only fork) is shown. Anything else (False or
    unknown/None) shows the read-only variant — the safe default, since "Clone
    it" has no side effects when in doubt.

    The "Fork it" row only appears in the read-only variant, and only when both
    a github.com remote (forking parses the source owner/repo and calls the
    GitHub forks API, which a non-github host like gitlab.com cannot satisfy)
    AND a connected token (the fork call authenticates with it) are present.
    Drop it if either is missing so the review never shows an outcome that 403s
    at apply. Clone-it and duplicate-it work for any remote, so they always
    appear. Falls back to "the source" when the remote URL is not a
    recognizable github.com owner/repo.
    """
    parsed = default_repo(remote_url)
    repo = parsed or "the source"
    rows = CLONE_OUTCOME_ROWS_WRITABLE if push_access is True else CLONE_OUTCOME_ROWS_READONLY
    keep_fork = bool(parsed) and has_token
    if not keep_fork:
        rows = [row for row in rows if row.value != CLONE_OUTCOME_FORK]
    return [
        SelectionRow(row.value, row.label, row.hint.format(repo=repo))
        for row in rows
    ]


def clone_outcome_body(
    remote_url: str | None,
    *,
    has_token: bool = True,
    push_access: bool | None = None,
) -> list[Static]:
    repo = default_repo(remote_url) or "the source"
    return selection_body(
        f"How do you want to copy {repo}?",
        None,
        clone_outcome_rows(remote_url, has_token=has_token, push_access=push_access),
    )


def owner_rows(owners: list) -> list[SelectionRow]:
    """Build the owner-picker rows from a list of github_publish.RepoOwner.

    The authenticated user reads "your account"; orgs read "organization". The
    row value is the owner login so the flow can resolve the chosen owner back
    to its kind for the user-vs-org create endpoint.
    """
    rows: list[SelectionRow] = []
    for owner in owners:
        hint = "your account" if owner.kind == "user" else "organization"
        rows.append(SelectionRow(owner.login, owner.login, hint))
    return rows


def repo_rows(repos: list) -> list[SelectionRow]:
    """Build the private-repo picker rows from a list of github_publish.RepoRef.

    The row value is the repo's clone URL so the flow can record it directly as
    ``project_remote_url`` on pick; the label is the ``owner/repo`` full name.
    """
    return [
        SelectionRow(repo.clone_url, repo.full_name, "private")
        for repo in repos
    ]


def publish_prompt_body() -> list[Static]:
    return selection_body(
        "Also publish to GitHub?",
        "Yoke creates the repo with your token and connects it as your remote.",
        PUBLISH_ROWS,
    )


def clone_visibility_body() -> list[Static]:
    return selection_body(
        "Is the repo public or private?",
        "Public repos clone from a URL; private ones come from your GitHub account.",
        CLONE_VISIBILITY_ROWS,
    )


def new_repo_visibility_body() -> list[Static]:
    return selection_body(
        "Make the new repo public or private?",
        None,
        NEW_REPO_VISIBILITY_ROWS,
    )


def owner_picker_body(owners: list) -> list[Static]:
    return selection_body(
        "Where on GitHub?",
        "Accounts your token can create repos under.",
        owner_rows(owners),
    )


def repo_picker_body(repos: list) -> list[Static]:
    return selection_body(
        "Which private repo?",
        "Private repos your GitHub token can reach.",
        repo_rows(repos),
    )


# Resume vs Start-over choice shown when the chosen clone folder already holds a
# matching clone of this source — a prior partial onboarding the user can pick up
# or wipe and redo.
RESUME_ROWS = [
    SelectionRow("resume", "Resume where it failed",
                 "keep the clone, finish the rest"),
    SelectionRow("start-over", "Start over",
                 "remove the folder and re-clone"),
]


def resume_or_start_over_body(checkout: str) -> list[Static]:
    return selection_body(
        "That folder is a partial setup.",
        f"{checkout} is already a clone of this repo from an earlier run. "
        "Resume from there, or start over.",
        RESUME_ROWS,
    )


__all__ = [
    "CLONE_OUTCOME_ROWS_READONLY",
    "CLONE_OUTCOME_ROWS_WRITABLE",
    "CLONE_VISIBILITY_PRIVATE",
    "CLONE_VISIBILITY_PUBLIC",
    "CLONE_VISIBILITY_ROWS",
    "NEW_REPO_PRIVATE",
    "NEW_REPO_PUBLIC",
    "NEW_REPO_VISIBILITY_ROWS",
    "PUBLISH_NO",
    "PUBLISH_ROWS",
    "PUBLISH_YES",
    "RESUME_ROWS",
    "clone_outcome_body",
    "clone_outcome_rows",
    "clone_visibility_body",
    "default_repo",
    "new_repo_visibility_body",
    "owner_picker_body",
    "owner_rows",
    "publish_prompt_body",
    "repo_picker_body",
    "repo_rows",
    "resume_or_start_over_body",
]

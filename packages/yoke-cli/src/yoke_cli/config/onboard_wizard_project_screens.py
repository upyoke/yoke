"""Project-source presentation helpers for the ``yoke setup`` wizard.

Body builders and option rows for the project-step screens that branch off the
source-select: the "Also publish to GitHub?" follow-up, the GitHub owner picker,
and the clone-outcome / keep-upstream choices, as the prompts those screens
declare. These are presentation-only — the decision graph lives in
:mod:`onboard_wizard_flow` and :mod:`onboard_wizard_flow_clone`.
"""

from __future__ import annotations

from textual.widgets import Static

from yoke_contracts import github_origin
from yoke_cli.config import onboard_github_copy
from yoke_cli.config.onboard_wizard_step_ids import STEP_PROJECT
from yoke_cli.config.onboard_wizard_searchable_picker import SearchableSelectionList
from yoke_cli.config.setup_prompt import SelectionRow, SetupPrompt
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_JUST_CLONE,
    CLONE_OUTCOME_SOURCE,
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
# to the paste-URL input; private lists repos reachable through connected GitHub
# authorization so the user picks instead of pasting.
CLONE_VISIBILITY_PUBLIC = "public"
CLONE_VISIBILITY_PRIVATE = "private"
CLONE_VISIBILITY_ROWS = [
    SelectionRow(
        CLONE_VISIBILITY_PUBLIC,
        "Public",
        onboard_github_copy.CLONE_VISIBILITY_PUBLIC_DESC,
    ),
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
    SelectionRow(NEW_REPO_PRIVATE, "Private", "only you and people you add can see it"),
    SelectionRow(NEW_REPO_PUBLIC, "Public", "anyone can see it"),
]

# Destination choices apply equally to new clones and adopted folders.
_CLONE_IT_WRITABLE = SelectionRow(
    CLONE_OUTCOME_SOURCE, "Use source for pushes", "push to {repo}; access confirmed by GitHub"
)
_CLONE_IT_READONLY = SelectionRow(
    CLONE_OUTCOME_JUST_CLONE, "Read-only source", "fetch from {repo}; Yoke pushes disabled"
)
_DUPLICATE_IT = SelectionRow(
    CLONE_OUTCOME_MAKE_IT_MINE, "Duplicate it", "push to a new remote repo we'll create"
)
_FORK_IT = SelectionRow(
    CLONE_OUTCOME_FORK,
    "Fork it",
    "push to a new fork we'll create — open PRs back to {repo}",
)
CLONE_OUTCOME_ROWS_WRITABLE = [_CLONE_IT_WRITABLE, _CLONE_IT_READONLY, _DUPLICATE_IT]
CLONE_OUTCOME_ROWS_READONLY = [_CLONE_IT_READONLY, _DUPLICATE_IT, _FORK_IT]


def default_repo(
    remote_url: str | None,
    *,
    web_url: str | None = None,
) -> str | None:
    if not remote_url:
        return None
    try:
        return github_origin.normalize_github_repository(
            remote_url,
            web_url=web_url or github_origin.DEFAULT_GITHUB_WEB_URL,
        )
    except github_origin.GitHubApiOriginError:
        return None


def clone_outcome_rows(
    remote_url: str | None,
    *,
    has_token: bool = True,
    push_access: bool | None = None,
    web_url: str | None = None,
) -> list[SelectionRow]:
    """Offer explicit destination policy; absent authorization proves no access."""
    parsed = default_repo(remote_url, web_url=web_url)
    repo = parsed or "the source"
    rows = (
        CLONE_OUTCOME_ROWS_WRITABLE
        if push_access is True
        else CLONE_OUTCOME_ROWS_READONLY
    )
    if push_access is None:
        rows = [*rows, SelectionRow(
            CLONE_OUTCOME_SOURCE, "Use source for pushes",
            "push to {repo} with your Git credentials; write access unverified",
        )]
    keep_fork = bool(parsed) and has_token
    if not keep_fork:
        rows = [row for row in rows if row.value != CLONE_OUTCOME_FORK]
    return [
        SelectionRow(row.value, row.label, row.hint.format(repo=repo)) for row in rows
    ]


def clone_outcome_prompt(
    remote_url: str | None,
    *,
    has_token: bool = True,
    push_access: bool | None = None,
    web_url: str | None = None,
) -> SetupPrompt:
    repo = default_repo(remote_url, web_url=web_url) or "the source"
    return SetupPrompt(
        key="project.clone_outcome",
        step=STEP_PROJECT,
        title=f"Where should Yoke publish work from {repo}?",
        message=("Read-only keeps fetching available and blocks publication-required "
                 "item work until you choose a writable destination."),
        choices=tuple(clone_outcome_rows(
            remote_url,
            has_token=has_token,
            push_access=push_access,
            web_url=web_url,
        )),
        guidance="Ask the person to select the publication destination; access may be unverified.",
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
    return [SelectionRow(repo.clone_url, repo.full_name, "private") for repo in repos]


NEW_REPO_VISIBILITY_PROMPT = SetupPrompt(
    key="project.new_repo_visibility",
    step=STEP_PROJECT,
    title="Make the new repo public or private?",
    choices=tuple(NEW_REPO_VISIBILITY_ROWS),
)


def owner_picker_prompt(owners: list) -> SetupPrompt:
    return SetupPrompt(
        key="project.publish_owner",
        step=STEP_PROJECT,
        title="Where on GitHub?",
        subtitle="Type to filter accounts and organizations, or use Up/Down immediately.",
        choices=tuple(owner_rows(owners)),
    )


def repo_picker_prompt(repos: list) -> SetupPrompt:
    return SetupPrompt(
        key="project.private_repo",
        step=STEP_PROJECT,
        title="Which private repo?",
        subtitle="Type an owner or repository name to filter, or use Up/Down immediately.",
        choices=tuple(repo_rows(repos)),
    )


def searchable_picker_body(prompt: SetupPrompt) -> list[Static]:
    return [
        Static(prompt.title, classes="onboard-title"),
        Static(prompt.subtitle or "", classes="onboard-subtitle"),
        Static("", classes="onboard-spacer"),
        SearchableSelectionList(list(prompt.choices)),
    ]


# A matching existing clone is safe to resume but remains user-owned here. The
# durable post-failure report is the only surface allowed to offer deletion.
RESUME_ROWS = [
    SelectionRow("resume", "Resume where it failed", "keep the clone, finish the rest"),
    SelectionRow(
        "choose-folder", "Choose another folder", "leave this clone untouched"
    ),
]


def resume_existing_clone_prompt(checkout: str) -> SetupPrompt:
    return SetupPrompt(
        key="project.clone_resume",
        step=STEP_PROJECT,
        title="That folder already has this repo.",
        subtitle=f"{checkout} is the exact root of a matching clone. Resume from "
        "it, or choose another folder; Yoke will not delete this folder.",
        choices=tuple(RESUME_ROWS),
    )


__all__ = [
    "CLONE_OUTCOME_ROWS_READONLY",
    "CLONE_OUTCOME_ROWS_WRITABLE",
    "CLONE_VISIBILITY_PRIVATE",
    "CLONE_VISIBILITY_PUBLIC",
    "CLONE_VISIBILITY_ROWS",
    "NEW_REPO_PRIVATE",
    "NEW_REPO_PUBLIC",
    "NEW_REPO_VISIBILITY_PROMPT",
    "NEW_REPO_VISIBILITY_ROWS",
    "PUBLISH_NO",
    "PUBLISH_ROWS",
    "PUBLISH_YES",
    "RESUME_ROWS",
    "clone_outcome_prompt",
    "clone_outcome_rows",
    "default_repo",
    "owner_picker_prompt",
    "owner_rows",
    "repo_picker_prompt",
    "repo_rows",
    "resume_existing_clone_prompt",
    "searchable_picker_body",
]

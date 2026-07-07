"""Shared user-facing copy for GitHub credential screens in onboarding.

Two distinct GitHub credential concepts must read consistently wherever they
surface — the wizard screens, the Finish review, and the ``yoke onboard`` /
``yoke project`` CLI help:

* The **machine token** (PAT) is stored locally on this machine in
  ``~/.yoke/secrets`` and used locally to clone, create, fork, and publish
  repos. Machine-token copy always says *local machine* / ``~/.yoke/secrets``.
* The **project token** is stored by Yoke in the Yoke core database so it can
  sync and manage Issues, PRs, CI, and Actions. Project-token copy always says
  *Yoke core database* / Issues, PRs, CI, Actions.

Centralizing the promise strings keeps the wording identical across every
surface instead of drifting between hand-edited literals.
"""

from __future__ import annotations

# ── Machine token (PAT): stored locally on this machine ─────────────────────
MACHINE_TOKEN_TITLE = "Save a local GitHub credential?"
MACHINE_TOKEN_SUBTITLE = (
    "Saved only on this machine in ~/.yoke/secrets. "
    "Used locally to clone, create, fork, and publish repos."
)
# Finish-review line for the machine GitHub connection.
MACHINE_TOKEN_REVIEW = "Save a local GitHub credential for repo operations"

# ── Project token: stored in the Yoke core database ────────────────────────
# The canonical project-token promise. Used as-is on the project GitHub prompt
# subtitle and embedded into the PAT-paste subtitle and CLI help below so the
# wording never diverges between surfaces.
PROJECT_TOKEN_PROMISE = (
    "Yoke stores your project's GitHub token in the Yoke core database to "
    "sync and manage Issues, PRs, CI, and Actions."
)

PROJECT_GITHUB_PROMPT_TITLE = "How should Yoke manage this project on GitHub?"
PROJECT_GITHUB_PROMPT_SUBTITLE = PROJECT_TOKEN_PROMISE

PROJECT_TOKEN_PASTE_TITLE = "Paste this project's GitHub token (PAT)."
PROJECT_TOKEN_PASTE_SUBTITLE = (
    "Never shown on screen. Yoke stores it in the Yoke core database to sync "
    "and manage Issues, PRs, CI, and Actions."
)

# Finish-review line for storing the project token in the core database.
PROJECT_TOKEN_REVIEW = (
    "Store this project's GitHub token in the Yoke core database for Issues, "
    "PRs, CI, and Actions"
)

# Project-token rows on the "manage this project on GitHub?" picker.
PROJECT_GITHUB_REUSE_LABEL = "Reuse this machine's token"
PROJECT_GITHUB_REUSE_DESC = "copy into the Yoke core database for this project"
PROJECT_GITHUB_STORE_LABEL = "Supply a token for this project"
PROJECT_GITHUB_STORE_DESC = "store in the Yoke core database for this project"
PROJECT_GITHUB_SKIP_LABEL = "Skip GitHub for this project"
PROJECT_GITHUB_SKIP_DESC = "no GitHub automation"

# CLI help for the project-token --github-adoption store/different choices.
PROJECT_TOKEN_ADOPTION_HELP = (
    "store-token/different-token securely stores the project GitHub token in "
    "the Yoke core database so Yoke can sync and manage Issues, PRs, CI, and "
    "Actions. GitHub App auth is planned as a future replacement."
)


__all__ = [
    "MACHINE_TOKEN_TITLE",
    "MACHINE_TOKEN_SUBTITLE",
    "MACHINE_TOKEN_REVIEW",
    "PROJECT_TOKEN_PROMISE",
    "PROJECT_GITHUB_PROMPT_TITLE",
    "PROJECT_GITHUB_PROMPT_SUBTITLE",
    "PROJECT_TOKEN_PASTE_TITLE",
    "PROJECT_TOKEN_PASTE_SUBTITLE",
    "PROJECT_TOKEN_REVIEW",
    "PROJECT_GITHUB_REUSE_LABEL",
    "PROJECT_GITHUB_REUSE_DESC",
    "PROJECT_GITHUB_STORE_LABEL",
    "PROJECT_GITHUB_STORE_DESC",
    "PROJECT_GITHUB_SKIP_LABEL",
    "PROJECT_GITHUB_SKIP_DESC",
    "PROJECT_TOKEN_ADOPTION_HELP",
]

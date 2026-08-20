"""Compare the declared merge-queue ruleset against the live one.

The declaration in the project checkout is authoritative and
``github.merge_queue.apply`` is its only writer, but nothing forces the
two together: between a declaration landing and an operator running the
apply, the live ruleset can require fewer checks than the repository
believes it requires, and every merge in that window is gated on the
weaker set without anyone being told.

Two readers need the same comparison — the Doctor check that reports the
drift and the queue landing that refuses to merge through it — so the
read lives here once. It needs only repository read access, which is
what makes it usable on the merge path: the apply itself demands
Administration write, a permission a merging agent has no reason to hold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
    GITHUB_METADATA_READ_PERMISSION_LEVELS,
)
from yoke_core.domain import github_merge_queue_rest as mq_rest
from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestTransportError,
)
from yoke_core.domain.merge_queue_declaration import (
    DECLARATION_RELATIVE_PATH,
    diff_declared_against_live,
)

MERGE_QUEUE_RULE_TYPE = "merge_queue"
DRIFT_SKIP_DECLARATION_MISSING = "declaration_missing"
DRIFT_SKIP_DECLARATION_UNREADABLE = "declaration_unreadable"
DRIFT_SKIP_GITHUB_AUTH_UNRESOLVED = "github_auth_unresolved"
DRIFT_SKIP_GITHUB_UNREACHABLE = "github_unreachable"


@dataclass(frozen=True)
class LiveDriftReport:
    """What the declared ruleset and the live one disagree about."""

    drift: tuple[str, ...] = field(default=())
    # Why a comparison could not be completed. Kept apart from `drift`
    # because an unreadable repository is not evidence of disagreement,
    # and callers that block on drift must not block on an outage.
    unreadable: tuple[str, ...] = field(default=())
    skip_reason: str = ""
    skip_detail: str = ""

    @property
    def drifted(self) -> bool:
        return bool(self.drift)

    @property
    def skipped(self) -> bool:
        return bool(self.skip_reason)

    def refusal(self, project: str) -> str:
        """Why the landing stopped, and the one command that clears it."""
        return (
            f"merge-queue ruleset has drifted from {DECLARATION_RELATIVE_PATH}"
            ": " + "; ".join(self.drift) + ". Apply the declaration with "
            f"`yoke github merge-queue apply --project {project or '<project>'}`"
            ", then retry the merge."
        )


def live_branch_rules(
    owner: str, repo: str, branch: str, *, token: str,
) -> tuple[Optional[list], Optional[str]]:
    """Return the live branch rules, or why they could not be read."""
    try:
        return list(
            mq_rest.fetch_branch_rules(owner, repo, branch, token=token)
        ), None
    except RestNotFoundError:
        # A branch with no ruleset reads as no rules, not as an outage.
        return [], None
    except RestTransportError as exc:
        return None, f"branch rules unreadable for {owner}/{repo}: {exc}"


def _live_bypass_actors(
    owner: str, repo: str, rules: Sequence[Any], *, token: str,
) -> tuple[Any, bool]:
    """Return (actors, comparable) for the ruleset backing the queue rule."""
    ruleset_id = None
    for rule in rules:
        if isinstance(rule, dict) and rule.get("type") == MERGE_QUEUE_RULE_TYPE:
            ruleset_id = rule.get("ruleset_id")
            break
    if not isinstance(ruleset_id, int):
        return None, False
    try:
        detail = mq_rest.get_ruleset(owner, repo, ruleset_id, token=token)
    except RestTransportError:
        return None, False
    return detail.get("bypass_actors"), True


def compare_declared_against_live(
    declared: Any,
    *,
    owner: str,
    repo: str,
    rules: Sequence[Any],
    token: str,
) -> LiveDriftReport:
    """Diff one parsed declaration against already-read live branch rules."""
    try:
        repo_row = mq_rest.fetch_repository(owner, repo, token=token)
    except RestTransportError as exc:
        return LiveDriftReport(
            unreadable=(f"repository settings unreadable: {exc}",),
        )
    live_auto = repo_row.get("allow_auto_merge")
    if not isinstance(live_auto, bool):
        live_auto = None
    bypass, compare_bypass = _live_bypass_actors(
        owner, repo, rules, token=token,
    )
    return LiveDriftReport(
        drift=tuple(
            diff_declared_against_live(
                declared,
                live_branch_rules=list(rules),
                live_allow_auto_merge=live_auto,
                live_bypass_actors=bypass,
                compare_bypass=compare_bypass,
            )
        ),
    )


def enforcement_drift(declared: Any, *, rules: Sequence[Any]) -> tuple[str, ...]:
    """Drift in what the queue actually gates on: queue params and checks.

    Deliberately blind to ``allow_auto_merge`` and ``bypass_actors``.
    Both are real settings and the Doctor check reports them, but neither
    decides whether a red check can merge, and both read as drift on a
    token that cannot see them — which on the merge path is a
    repository-wide freeze rather than a warning. Observed live: a
    hosted-runtime read reported "live allow_auto_merge could not be
    read" and an empty bypass list against a repository whose enforcement
    surface matched exactly.
    """
    return tuple(
        diff_declared_against_live(
            declared,
            live_branch_rules=list(rules),
            # The declared value echoed back, so an unread repository
            # setting cannot masquerade as a disagreement.
            live_allow_auto_merge=bool(
                declared["repository"]["allow_auto_merge"]
            ),
            compare_bypass=False,
        )
    )


def drift_blocking_landing(
    project: str, *, checkout: str, branch: str,
) -> LiveDriftReport:
    """Drift that must stop a landing on ``branch``, read from ``checkout``.

    Every failure short of an actual disagreement reports as unreadable
    rather than as drift. A landing blocked because GitHub was briefly
    unreachable would trade a silent-weak-ruleset window for a merge
    freeze, and the freeze is the worse of the two.
    """
    from yoke_core.domain import gh_rest_transport
    from yoke_core.domain.merge_queue_declaration import (
        MergeQueueDeclarationError,
        declaration_path,
        load_declaration,
    )
    from yoke_core.domain.project_github_auth import (
        ProjectGithubAuthError,
        resolve_project_github_auth,
    )

    path = declaration_path(Path(checkout))
    if not path.is_file():
        return LiveDriftReport(
            skip_reason=DRIFT_SKIP_DECLARATION_MISSING,
            skip_detail=f"no declaration at {DECLARATION_RELATIVE_PATH}",
        )
    try:
        declared = load_declaration(path)
    except MergeQueueDeclarationError as exc:
        detail = f"declaration unreadable: {exc}"
        return LiveDriftReport(
            unreadable=(detail,),
            skip_reason=DRIFT_SKIP_DECLARATION_UNREADABLE,
            skip_detail=detail,
        )

    try:
        auth = resolve_project_github_auth(
            project,
            required_permissions={
                **GITHUB_METADATA_READ_PERMISSION_LEVELS,
                **GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
            },
        )
    except ProjectGithubAuthError as exc:
        detail = f"ruleset drift unverified: {exc.code}: {exc}"
        return LiveDriftReport(
            unreadable=(detail,),
            skip_reason=DRIFT_SKIP_GITHUB_AUTH_UNRESOLVED,
            skip_detail=detail,
        )

    owner, repo = gh_rest_transport.split_repo(auth.repo)
    rules, rules_error = live_branch_rules(
        owner, repo, branch, token=auth.token,
    )
    if rules is None:
        detail = str(rules_error)
        return LiveDriftReport(
            unreadable=(detail,),
            skip_reason=DRIFT_SKIP_GITHUB_UNREACHABLE,
            skip_detail=detail,
        )
    return LiveDriftReport(drift=enforcement_drift(declared, rules=rules))


__all__ = [
    "DRIFT_SKIP_DECLARATION_MISSING",
    "DRIFT_SKIP_DECLARATION_UNREADABLE",
    "DRIFT_SKIP_GITHUB_AUTH_UNRESOLVED",
    "DRIFT_SKIP_GITHUB_UNREACHABLE",
    "MERGE_QUEUE_RULE_TYPE",
    "LiveDriftReport",
    "drift_blocking_landing",
    "enforcement_drift",
    "compare_declared_against_live",
    "live_branch_rules",
]

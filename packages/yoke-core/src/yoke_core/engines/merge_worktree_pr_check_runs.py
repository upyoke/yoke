"""The checks behind a merge-queue landing, read from their two sources.

A landing waits on two different check sets, and each has its own reader.
While the pull request is waiting to enter the queue, the gate is the
pull request's own required checks: GitHub creates the queue entry only
once they pass, so a required check that has already concluded red means
the entry can never happen. Those come from the pull request's
``statusCheckRollup``, which is the only read that says which checks are
*required* and where each one's run can be read.

Once a train is building, the commit under validation is the train's, not
the pull request's, and nothing on it is required for the pull request.
That set is the plain per-commit check-run listing.

Landing status used to be a separate REST read. The GraphQL document that
already fetched the rollup now returns the merged/closed/head/arming
fields the report needs, so one pull request is one upstream call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CHECKS_READ_PERMISSION_LEVELS as CHECKS_READ,
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS as PR_READ,
)

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    graphql_with_auth,
    resolve_auth_detail,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


#: One document per distinct pull request: landing status plus the rollup
#: that names required checks. The rollup answers from the head commit and
#: carries the two facts a per-commit listing cannot: whether each check
#: gates the queue entry, and the run a holder has to open to read it.
_PR_LANDING_AND_CHECKS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      merged
      closed
      state
      autoMergeRequest { enabledAt }
      mergeStateStatus
      headRefOid
      mergedAt
      mergeCommit { oid }
      commits(last: 1) {
        nodes {
          commit {
            statusCheckRollup {
              contexts(last: 100) {
                nodes {
                  __typename
                  ... on CheckRun {
                    name
                    status
                    conclusion
                    detailsUrl
                    startedAt
                    isRequired(pullRequestNumber: $number)
                  }
                  ... on StatusContext {
                    context
                    state
                    targetUrl
                    createdAt
                    isRequired(pullRequestNumber: $number)
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

#: Commit statuses report one state rather than a status/conclusion pair.
_SETTLED_STATUS_STATES = frozenset({"success", "failure", "error"})
_CLOSED_PR_STATES = frozenset({"CLOSED", "MERGED"})


@dataclass(frozen=True)
class LandingCheck:
    """One check a landing waits on, or has already read a verdict from."""

    name: str
    status: str
    conclusion: str = ""
    required: bool = False
    url: str = ""

    def describe(self) -> str:
        """The check and the run behind it, so a refusal can be acted on."""
        verdict = self.conclusion or self.status or "unreported"
        return f"{self.name}={verdict}" + (f" ({self.url})" if self.url else "")


@dataclass(frozen=True)
class PrLandingProjection:
    """Landing status and required checks from one GraphQL pull-request read."""

    state: Optional[PrLandingState] = None
    required_checks: Optional[tuple[LandingCheck, ...]] = None
    state_error: Optional[str] = None
    checks_error: Optional[str] = None


def check_payload(check: LandingCheck) -> dict[str, Any]:
    """The transport-safe projection of one check, shared by every reader."""
    return {
        "name": check.name,
        "status": check.status,
        "conclusion": check.conclusion,
        "required": check.required,
        "url": check.url,
    }


def read_landing_checks(
    ctx: MergeContext,
    head_sha: str,
) -> tuple[Optional[tuple[LandingCheck, ...]], Optional[str]]:
    """Per-check breakdown for the SHA the train is validating."""
    if not head_sha:
        return (), None
    auth, auth_err = resolve_auth_detail(ctx, CHECKS_READ)
    if auth_err or auth is None:
        return None, auth_err
    owner, repo = split_repo(auth.repo)
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/commits/{head_sha}/check-runs",
            ),
            token=auth.token,
        )
    except RestTransportError as exc:
        return None, f"check-runs read failed: {exc}"
    payload = response.body if isinstance(response.body, dict) else None
    raw_runs = payload.get("check_runs") if payload is not None else None
    if not isinstance(raw_runs, list):
        return None, "check-runs response omitted check_runs"
    checks: list[LandingCheck] = []
    for raw in raw_runs:
        if not isinstance(raw, dict):
            return None, "check-runs response contained a malformed run"
        checks.append(
            LandingCheck(
                name=str(raw.get("name") or "unnamed check").strip(),
                status=str(raw.get("status") or "").strip().lower(),
                conclusion=str(raw.get("conclusion") or "").strip().lower(),
            )
        )
    return tuple(checks), None


def _rollup_context(node: Any) -> Optional[tuple[LandingCheck, str]]:
    """One required rollup node and when it started, or ``None``.

    The timestamp is what orders same-named entries; it is read from the
    node rather than taken from list position, because the rollup's order
    is not documented as chronological and a superseded attempt that
    happens to sort last would be reported as the live one.
    """
    if not isinstance(node, dict) or not node.get("isRequired"):
        return None
    if node.get("__typename") == "StatusContext":
        state = str(node.get("state") or "").strip().lower()
        return (
            LandingCheck(
                name=str(node.get("context") or "unnamed check").strip(),
                status="completed" if state in _SETTLED_STATUS_STATES else state,
                conclusion=state if state in _SETTLED_STATUS_STATES else "",
                required=True,
                url=str(node.get("targetUrl") or "").strip(),
            ),
            str(node.get("createdAt") or ""),
        )
    return (
        LandingCheck(
            name=str(node.get("name") or "unnamed check").strip(),
            status=str(node.get("status") or "").strip().lower(),
            conclusion=str(node.get("conclusion") or "").strip().lower(),
            required=True,
            url=str(node.get("detailsUrl") or "").strip(),
        ),
        str(node.get("startedAt") or ""),
    )


def _parse_required_checks(pull_request: dict[str, Any]) -> tuple[LandingCheck, ...]:
    """Latest required rollup run of each name, or empty when none exist."""
    nodes = ((pull_request.get("commits") or {}).get("nodes")) or []
    head = (nodes[-1] or {}).get("commit") if nodes else None
    rollup = (head or {}).get("statusCheckRollup") if isinstance(head, dict) else None
    contexts = ((rollup or {}).get("contexts") or {}).get("nodes") or []
    latest: dict[str, tuple[str, LandingCheck]] = {}
    for node in contexts:
        resolved = _rollup_context(node)
        if resolved is None:
            continue
        check, started = resolved
        previous = latest.get(check.name)
        if previous is None or started >= previous[0]:
            latest[check.name] = (started, check)
    return tuple(check for _started, check in latest.values())


def _parse_landing_state(pull_request: dict[str, Any]) -> PrLandingState:
    """Map GraphQL pull-request fields onto the REST landing-state shape."""
    merge_commit = pull_request.get("mergeCommit")
    merge_oid = ""
    if isinstance(merge_commit, dict):
        merge_oid = str(merge_commit.get("oid") or "").strip()
    state = str(pull_request.get("state") or "").strip().upper()
    return PrLandingState(
        merged=bool(pull_request.get("merged")),
        closed=bool(pull_request.get("closed")) or state in _CLOSED_PR_STATES,
        auto_merge_active=pull_request.get("autoMergeRequest") is not None,
        merge_state_status=str(
            pull_request.get("mergeStateStatus") or ""
        ).strip().lower(),
        head_sha=str(pull_request.get("headRefOid") or "").strip(),
        merged_at=str(pull_request.get("mergedAt") or "").strip(),
        merge_commit_sha=merge_oid,
    )


def _unreadable(reason: str) -> PrLandingProjection:
    return PrLandingProjection(state_error=reason, checks_error=reason)


def read_pr_landing_and_required_checks(
    ctx: MergeContext,
    pr_num: str,
) -> PrLandingProjection:
    """Landing status and required checks for ``pr_num`` in one GraphQL read.

    ``(None, reason)`` on either half is unreadable, which proves nothing
    and must not be read as a green or landed result. A readable pull
    request with no required checks answers that half with an empty tuple.
    A GraphQL error list still fails the whole document: partial payloads
    are not interpreted as success.
    """
    auth, auth_err = resolve_auth_detail(ctx, PR_READ)
    if auth_err or auth is None:
        return _unreadable(auth_err or "github auth unavailable")
    owner, name = split_repo(auth.repo)
    try:
        number = int(str(pr_num).strip())
    except ValueError:
        return _unreadable(f"pull request identifier {pr_num!r} is not a number")
    data, err = graphql_with_auth(
        auth,
        query=_PR_LANDING_AND_CHECKS_QUERY,
        variables={"owner": owner, "name": name, "number": number},
        required_permissions=PR_READ,
    )
    if err:
        return _unreadable(f"pull-request landing read failed: {err}")
    pull_request = ((data or {}).get("repository") or {}).get("pullRequest")
    if not isinstance(pull_request, dict):
        return _unreadable(
            f"repository {owner}/{name} returned no pull request {pr_num}; "
            "its landing status and required checks could not be read"
        )
    return PrLandingProjection(
        state=_parse_landing_state(pull_request),
        required_checks=_parse_required_checks(pull_request),
    )


def read_required_checks(
    ctx: MergeContext,
    pr_num: str,
) -> tuple[Optional[tuple[LandingCheck, ...]], Optional[str]]:
    """The required checks gating ``pr_num``'s entry into the merge queue.

    Independent callers keep this name. The document is the combined
    projection; extra landing fields are unused here.
    """
    projection = read_pr_landing_and_required_checks(ctx, pr_num)
    return projection.required_checks, projection.checks_error


__all__ = [
    "LandingCheck",
    "PrLandingProjection",
    "check_payload",
    "read_landing_checks",
    "read_pr_landing_and_required_checks",
    "read_required_checks",
]

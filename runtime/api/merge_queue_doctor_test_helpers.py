"""Shared fixtures for merge-queue binding health-check tests.

Serves GitHub REST through ``request_with_retry`` so ``fetch_file_text``
and the workflow-trigger predicate run for real. A JSON declaration body
is a dict (the transport's ``json.loads`` result); 404 is a raised
``RestNotFoundError``.
"""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain.gh_rest_transport import RestNotFoundError, RestResponse
from yoke_core.domain.merge_queue_declaration import DECLARATION_RELATIVE_PATH
from yoke_core.engines import doctor_hc_merge_queue as hc_mod
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

_ABSENT = object()

WORKFLOW_WITH_MERGE_GROUP = (
    "# merge_group in a comment is not a trigger\n"
    "on:\n"
    "  pull_request:\n"
    "  merge_group:\n"
    "  push:\n"
    "    branches: [main]\n"
)

WORKFLOW_COMMENT_ONLY_MERGE_GROUP = (
    "# merge_group runs are the merge queue's one integration gate\n"
    "on:\n"
    "  pull_request:\n"
    "  push:\n"
    "    branches: [main]\n"
)


class FakeCursor:
    def __init__(self, value):
        self._value = value

    def fetchone(self):
        return (self._value,)


class FakeConn:
    """Serve scalar reads keyed by SQL substring."""

    def __init__(self, *, project_id=7, declares=True):
        self._project_id = project_id
        self._declares = declares

    def execute(self, sql, params=()):
        if "FROM projects" in sql and "COALESCE" in sql:
            return FakeCursor("main")
        if "FROM projects" in sql:
            return FakeCursor(self._project_id)
        if "COALESCE(settings" in sql:
            return FakeCursor('{"workflow_file": "yoke-ci.yml"}')
        if "project_capabilities" in sql:
            return FakeCursor(1 if self._declares else 0)
        raise AssertionError(f"unexpected sql: {sql}")


def auth():
    return SimpleNamespace(token="tok", repo="upyoke/yoke")


def live_rules(*, grouping="HEADGREEN"):
    return [
        {
            "type": "merge_queue",
            "parameters": {
                "merge_method": "MERGE",
                "grouping_strategy": grouping,
                "min_entries_to_merge": 1,
                "min_entries_to_merge_wait_minutes": 5,
                "max_entries_to_build": 5,
                "max_entries_to_merge": 5,
                "check_response_timeout_minutes": 60,
            },
            "ruleset_id": 99,
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": False,
                "do_not_enforce_on_create": False,
                "required_status_checks": [
                    {"context": "repo-contracts"},
                    {"context": "container"},
                ],
            },
            "ruleset_id": 99,
        },
    ]


def declared():
    return {
        "schema": 1,
        "ruleset": {
            "name": "merge-queue-main",
            "target": "branch",
            "enforcement": "active",
            "conditions": {
                "ref_name": {
                    "include": ["refs/heads/main"],
                    "exclude": [],
                }
            },
            "bypass_actors": [
                {
                    "actor_id": 5,
                    "actor_type": "RepositoryRole",
                    "bypass_mode": "always",
                }
            ],
            "rules": [
                {
                    "type": "merge_queue",
                    "parameters": {
                        "merge_method": "MERGE",
                        "grouping_strategy": "HEADGREEN",
                        "min_entries_to_merge": 1,
                        "min_entries_to_merge_wait_minutes": 5,
                        "max_entries_to_build": 5,
                        "max_entries_to_merge": 5,
                        "check_response_timeout_minutes": 60,
                    },
                },
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": False,
                        "do_not_enforce_on_create": False,
                        "required_status_checks": [
                            {"context": "repo-contracts"},
                            {"context": "container"},
                        ],
                    },
                },
            ],
        },
        "repository": {"allow_auto_merge": True},
    }


def run(
    monkeypatch,
    *,
    conn,
    rules_body,
    declaration=None,
    repo_declaration=None,
    repo_body=_ABSENT,
    workflow_text=None,
    allow_auto_merge=True,
    bypass_actors=None,
):
    if repo_body is _ABSENT and repo_declaration is not None:
        repo_body = repo_declaration
    if workflow_text is None:
        workflow_text = WORKFLOW_WITH_MERGE_GROUP
    monkeypatch.setattr(
        hc_mod, "resolve_project_github_auth",
        lambda project, db_path=None, required_permissions=None: auth(),
    )

    def fake_retry(req, *, token, **_kw):
        path = req.path
        if DECLARATION_RELATIVE_PATH in path:
            if repo_body is _ABSENT:
                raise RestNotFoundError("missing declaration", status=404)
            return RestResponse(status=200, headers={}, body=repo_body)
        if "workflows" in path:
            return RestResponse(status=200, headers={}, body=workflow_text)
        raise AssertionError(f"unexpected rest path: {path}")

    monkeypatch.setattr(hc_mod.mq_rest, "request_with_retry", fake_retry)
    monkeypatch.setattr(
        hc_mod.mq_rest, "fetch_branch_rules",
        lambda *a, **k: list(rules_body),
    )
    monkeypatch.setattr(
        hc_mod.mq_rest, "fetch_repository",
        lambda *a, **k: {"allow_auto_merge": allow_auto_merge},
    )
    monkeypatch.setattr(
        hc_mod.mq_rest, "get_ruleset",
        lambda *a, **k: {
            "id": 99,
            "bypass_actors": bypass_actors if bypass_actors is not None else [
                {
                    "actor_id": 5,
                    "actor_type": "RepositoryRole",
                    "bypass_mode": "always",
                }
            ],
        },
    )
    if declaration is None:
        monkeypatch.setattr(
            hc_mod, "_checkout_declaration",
            lambda conn, args: (
                None, "no source checkout mapped for project"
            ),
        )
    else:
        monkeypatch.setattr(
            hc_mod, "_checkout_declaration",
            lambda conn, args: (declaration, ".yoke/merge-queue.json"),
        )
    rec = RecordCollector()
    hc_mod.hc_merge_queue_binding(conn, DoctorArgs(project="yoke"), rec)
    return rec.results[-1]


__all__ = [
    "FakeConn",
    "WORKFLOW_COMMENT_ONLY_MERGE_GROUP",
    "WORKFLOW_WITH_MERGE_GROUP",
    "auth",
    "declared",
    "live_rules",
    "run",
]

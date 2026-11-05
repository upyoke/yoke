# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from copy import deepcopy

from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import parse_instant

from yoke_core.engines import merge_worktree_pr_check_runs as checks_mod

from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _ctx() -> MergeContext:
    return MergeContext(args=MergeArgs(branch="YOK-3361"), project="yoke")


def _auth():
    return SimpleNamespace(token="tok", repo="upyoke/yoke")


def _check_run(
    *, name, status, conclusion="", required=True, started="2026-09-21T00:00:00Z"
):
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "detailsUrl": f"https://example/{name}",
        "startedAt": started,
        "isRequired": required,
    }


def _pr_node(
    *,
    merged=False,
    closed=False,
    state="OPEN",
    auto_merge=False,
    merge_state="CLEAN",
    head="abc123def",
    merged_at="",
    merge_oid="",
    rollup="present",
    contexts=(),
):
    commit = {"statusCheckRollup": None}
    if rollup == "present":
        commit["statusCheckRollup"] = {"contexts": {"nodes": list(contexts)}}
    elif rollup == "missing":
        commit = {}
    node = {
        "merged": merged,
        "closed": closed,
        "state": state,
        "autoMergeRequest": {"enabledAt": "2026-09-21T00:00:00Z"}
        if auto_merge
        else None,
        "mergeQueueEntry": None,
        "mergeStateStatus": merge_state,
        "headRefOid": head,
        "mergedAt": merged_at or None,
        "mergeCommit": {"oid": merge_oid} if merge_oid else None,
        "commits": {"nodes": [{"commit": commit}]},
    }
    return {"repository": {"pullRequest": node}}


def _wire(monkeypatch, payload, err=None, *, capture=None):
    monkeypatch.setattr(
        checks_mod, "resolve_auth_detail", lambda _ctx, _perms: (_auth(), None)
    )

    def fake_graphql(_auth, *, query, variables, required_permissions):
        if capture is not None:
            capture.append({"query": query, "variables": variables})
        return payload, err

    monkeypatch.setattr(checks_mod, "graphql_with_auth", fake_graphql)

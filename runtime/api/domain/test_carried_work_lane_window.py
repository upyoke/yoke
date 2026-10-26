"""Only this release's landing window spends branch lookup requests."""

from types import SimpleNamespace

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import deployment_run_carried_work_repository as provider
from yoke_core.domain import deployment_run_carried_work_sources as sources
from yoke_core.domain.gh_rest_transport_errors import RestTransportError

BASE, HEAD = "a" * 40, "b" * 40
STAMP = parse_instant("2026-10-26T12:00:00Z")


def _resolve(monkeypatch, rows, *, missing=False):
    requests = []

    def request(request, *, token):
        requests.append(request.path)
        if missing:
            raise RestTransportError("404 not found", status=404)
        return SimpleNamespace(body={"sha": HEAD})

    monkeypatch.setattr(provider, "request_with_retry", request)
    monkeypatch.setattr(sources, "_safe_rows", lambda *args, **kwargs: rows)
    source = provider.RepositoryProviderSource("owner/repo", "token")
    monkeypatch.setattr(source, "commit_time", lambda commit: STAMP)
    monkeypatch.setattr(
        source, "carrying_commit",
        lambda commit, **kwargs: commit if commit == HEAD else "",
    )
    resolved = {}
    sources._resolve_item_metadata(
        object(), project_id=1, source=source, base=BASE, head=HEAD,
        commits=[HEAD], known_items={row[0]: str(row[0]) for row in rows},
        resolved=resolved, warnings=[],
    )
    return resolved, requests, source.warnings()


def test_historical_lanes_leave_budget_for_the_carried_lane(monkeypatch):
    historical = [
        (item, "2026-01-01T00:00:00Z", None, None, f"old-{item}", None, False)
        for item in range(1, provider.COMMIT_LOOKUP_BUDGET + 4)
    ]
    carried = (100, STAMP, None, None, "current", None, True)

    resolved, requests, warnings = _resolve(monkeypatch, [*historical, carried])

    assert requests == ["/repos/owner/repo/commits/current"]
    assert warnings == []
    assert resolved == {HEAD: {100}}


def test_historical_lanes_alone_produce_no_lookup_or_warning(monkeypatch):
    row = (1, "2026-01-01T00:00:00Z", None, None, "deleted", None, False)

    resolved, requests, warnings = _resolve(monkeypatch, [row], missing=True)

    assert requests == []
    assert warnings == []
    assert resolved == {}


def test_unresolvable_branch_inside_window_still_warns(monkeypatch):
    row = (1, STAMP, None, None, "deleted", None, True)

    _, requests, warnings = _resolve(monkeypatch, [row], missing=True)

    assert requests == ["/repos/owner/repo/commits/deleted"]
    assert [warning["reason"] for warning in warnings] == [
        "lane_branch_refs_unresolvable"
    ]


def test_recorded_sha_still_attributes_outside_landing_window(monkeypatch):
    row = (1, "2026-01-01T00:00:00Z", None, None, "deleted", HEAD, False)

    resolved, requests, warnings = _resolve(monkeypatch, [row], missing=True)

    assert resolved == {HEAD: {1}}
    assert requests == []
    assert warnings == []

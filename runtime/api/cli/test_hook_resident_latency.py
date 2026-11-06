"""Resident optimizations retain fresh identity and isolated transport ownership."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import httpx
import pytest

from yoke_cli.transport import https
from yoke_cli.transport.http_request_context import active_http_opener, use_http_opener
from yoke_contracts import fleet_watcher_observation as fleet
from yoke_contracts import session_identity as identity
from yoke_contracts.process_ancestry import ProcessAnchor
from yoke_harness.hooks import identity_anchor as hooks


@pytest.fixture(autouse=True)
def empty_caches(monkeypatch):
    monkeypatch.setattr(hooks, "_anchor_cache", hooks.OrderedDict())
    monkeypatch.setattr(fleet, "_process_list", None)


def test_no_named_anchor_does_not_fall_back_to_an_ambient_ancestor(monkeypatch):
    monkeypatch.setattr(hooks, "_caller_anchor", lambda *args, **kwargs: None)
    write = Mock()
    monkeypatch.setattr(hooks, "_record_session_anchor", write)
    hooks.record_session_anchor("session-a")
    write.assert_not_called()


def test_ancestry_cache_checks_parent_reuse_anchor_liveness_and_expiry(monkeypatch):
    clock = [10.0]
    starts = {300: "parent-start", 200: "anchor-start"}
    anchor = ProcessAnchor(200, "anchor-start", "claude")
    lookup = Mock(return_value=anchor)
    monkeypatch.setattr(hooks.os, "getppid", lambda: 300)
    monkeypatch.setattr(hooks, "process_start_time", starts.get)
    monkeypatch.setattr(hooks.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(hooks, "find_nearest_named_process_anchor", lookup)
    assert hooks._caller_anchor(("claude",)) == anchor
    assert hooks._caller_anchor(("claude",)) == anchor
    assert lookup.call_count == 1
    starts[300] = "reused-parent"
    hooks._caller_anchor(("claude",))
    assert lookup.call_count == 2
    starts[200] = "reused-anchor"
    lookup.return_value = None
    assert hooks._caller_anchor(("claude",)) is None
    assert lookup.call_count == 3
    assert hooks._caller_anchor(("claude",)) is None
    clock[0] += hooks._ANCHOR_TTL_SECONDS
    hooks._caller_anchor(("claude",))
    assert lookup.call_count == 4


def test_matching_anchor_record_is_not_rewritten_but_changed_tenancy_is_read(tmp_path):
    anchor = ProcessAnchor(200, "start", "claude")
    first = identity.record_session_anchor("a", tmp_path, anchor=anchor)
    path = tmp_path / "200.json"
    stamp = path.stat().st_mtime_ns
    assert identity.record_session_anchor("a", tmp_path, anchor=anchor) == first
    assert path.stat().st_mtime_ns == stamp
    # Another writer remains visible even while ancestry is cached.
    other = dict(first, session_id="b")
    path.write_text(json.dumps(other))
    contended = identity.record_session_anchor("a", tmp_path, anchor=anchor)
    assert contended["shared_by_multiple_sessions"] is True
    assert contended["contending_session_ids"] == ["a", "b"]


def test_anchor_transcript_and_reused_pid_are_updated(tmp_path):
    anchor = ProcessAnchor(200, "start", "claude")
    identity.record_session_anchor("a", tmp_path, anchor=anchor)
    updated = identity.record_session_anchor(
        "a", tmp_path, anchor=anchor, transcript_path="transcript.jsonl"
    )
    assert updated["transcript_path"] == "transcript.jsonl"
    reused = identity.record_session_anchor(
        "b", tmp_path, anchor=ProcessAnchor(200, "new", "claude")
    )
    assert reused["session_id"] == "b"
    assert not reused.get("shared_by_multiple_sessions")


def test_fleet_snapshot_is_shared_and_refreshes_after_two_seconds(monkeypatch):
    clock = [10.0]
    listed = Mock(return_value=("watcher-a",))
    monkeypatch.setattr(fleet.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(fleet, "list_process_cmdlines", listed)
    assert fleet._recent_process_cmdlines() == ("watcher-a",)
    listed.return_value = ("watcher-b",)
    assert fleet._recent_process_cmdlines() == ("watcher-a",)
    clock[0] += fleet._PROCESS_LIST_TTL_SECONDS
    assert fleet._recent_process_cmdlines() == ("watcher-b",)
    assert listed.call_count == 2
    clock[0] += fleet._PROCESS_LIST_TTL_SECONDS
    listed.return_value = ()
    assert fleet._recent_process_cmdlines() == ()
    listed.return_value = ("recovered",)
    assert fleet._recent_process_cmdlines() == ("recovered",)


def test_fleet_concurrent_hooks_share_one_process_listing(monkeypatch):
    barrier = threading.Barrier(4)
    listed = Mock(return_value=("watcher",))
    monkeypatch.setattr(fleet, "list_process_cmdlines", listed)
    def observe(_):
        barrier.wait(timeout=5)
        return fleet._recent_process_cmdlines()
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(observe, range(4))) == [("watcher",)] * 4
    listed.assert_called_once()


def test_function_relay_reuses_request_pool_without_redirects():
    from yoke_harness.hook_resident_http import ResidentHttpOpener

    seen = []
    def answer(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"rows": []})
    opener = ResidentHttpOpener()
    opener._client.close()
    opener._client = httpx.Client(transport=httpx.MockTransport(answer))
    request = urllib.request.Request("https://control-plane.test/v1/functions/call")
    try:
        with use_http_opener(opener):
            with https._open_function_relay(
                request, deadline=time.monotonic() + 5, timeout_s=5
            ) as response:
                assert json.loads(response.read()) == {"rows": []}
        assert active_http_opener() is None
        assert seen == ["/v1/functions/call"]
    finally:
        opener.close()


def test_http_pool_is_isolated_between_concurrent_requests_and_on_error():
    barrier = threading.Barrier(2)
    def run(value):
        with pytest.raises(RuntimeError), use_http_opener(value):
            barrier.wait(timeout=5)
            assert active_http_opener() is value
            raise RuntimeError("hook failed")
        assert active_http_opener() is None
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, [Mock(), Mock()]))


def test_resident_activates_pool_for_ancillary_function_calls(tmp_path):
    from yoke_contracts.hook_evaluator_protocol import HookEvaluatorRequest
    from yoke_harness.hook_resident import _ResidentServer

    server = object.__new__(_ResidentServer)
    server.started_at = time.monotonic()
    server.http_opener = Mock()
    server.observations = Mock(diagnostic=Mock(return_value=""))
    def evaluate(*args, **kwargs):
        assert active_http_opener() is server.http_opener
        return 0
    server.evaluate_inprocess = evaluate
    request = HookEvaluatorRequest(
        revision="test", event_name="Stop", stdin="{}", environment={},
        cwd=str(tmp_path), pid=1, ppid=1, dry_run=False,
    )
    result, _ = server.evaluate(request)
    assert result["exit_code"] == 0
    assert active_http_opener() is None


@pytest.mark.parametrize("status", [302, 401, 503])
def test_pooled_function_relay_preserves_http_error_semantics(status):
    from yoke_harness.hook_resident_http import ResidentHttpOpener

    opener = ResidentHttpOpener()
    opener._client.close()
    opener._client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, headers={"Location": "https://other.test"})
    ))
    request = urllib.request.Request("https://control-plane.test/v1/functions/call")
    try:
        with use_http_opener(opener), pytest.raises(urllib.error.HTTPError) as caught:
            https._open_function_relay(request, deadline=time.monotonic() + 5, timeout_s=5)
        assert caught.value.code == status
        caught.value.close()
    finally:
        opener.close()


def test_transcript_discovery_is_bounded_and_scoped_without_caching_contents(
    monkeypatch, tmp_path
):
    from yoke_harness.hooks import identity_codex_runtime as codex

    monkeypatch.setattr(codex, "_candidate_cache", codex.OrderedDict())
    clock = [10.0]
    monkeypatch.setattr(codex.time, "monotonic", lambda: clock[0])
    root = tmp_path / "one"
    root.mkdir()
    rollout = root / "rollout-thread.jsonl"
    assert codex.codex_transcript_candidates("thread", roots=[root]) == []
    rollout.write_text("first")
    assert codex.codex_transcript_candidates("thread", roots=[root]) == []
    clock[0] += codex._CANDIDATE_TTL_SECONDS
    assert codex.codex_transcript_candidates("thread", roots=[root]) == [rollout]
    rollout.write_text("new turn")
    found = codex.codex_transcript_candidates("thread", roots=[root])
    assert found[0].read_text() == "new turn"
    assert codex.codex_transcript_candidates("thread", roots=[tmp_path / "other"]) == []
    rollout.unlink()
    assert codex.codex_transcript_candidates("thread", roots=[root]) == []
    assert codex.codex_transcript_candidates("", roots=[root]) == []


def test_claude_keeps_ambient_anchor_while_codex_skips_its_walk(monkeypatch):
    from yoke_harness.hooks import identity_runtime

    lookup = Mock(return_value=ProcessAnchor(200, "start", "claude"))
    write = Mock()
    monkeypatch.setattr(hooks, "_caller_anchor", lookup)
    monkeypatch.setattr(hooks, "_record_session_anchor", write)
    monkeypatch.setattr(hooks, "liveness_process_names", lambda surface: ())
    monkeypatch.setattr(identity_runtime, "detect_executor", lambda: "claude-code")
    hooks.record_session_anchor("claude-session")
    lookup.assert_called_once_with((), ambient=True)
    assert write.call_args.kwargs["anchor"].pid == 200
    lookup.reset_mock()
    write.reset_mock()
    monkeypatch.setattr(identity_runtime, "detect_executor", lambda: "codex-cli")
    hooks.record_session_anchor("codex-session")
    lookup.assert_not_called()
    write.assert_not_called()


def test_ambient_anchor_cache_preserves_shared_host_boundary(monkeypatch):
    monkeypatch.setattr(hooks, "process_start_time", lambda pid: "start")
    ambient = Mock(return_value=None)
    named = Mock()
    monkeypatch.setattr(hooks, "find_nearest_harness_anchor", ambient)
    monkeypatch.setattr(hooks, "find_nearest_named_process_anchor", named)
    assert hooks._caller_anchor((), ambient=True) is None
    assert hooks._caller_anchor((), ambient=True) is None
    ambient.assert_called_once()
    named.assert_not_called()


def test_ambient_ancestry_reads_one_table_and_keeps_shared_host_boundary(monkeypatch):
    from yoke_contracts import process_ancestry as ancestry

    table = Mock(return_value={400: (300, "python"), 300: (200, "zsh"),
                               200: (100, "codex"), 100: (1, "claude")})
    individual = Mock(side_effect=AssertionError("must use the snapshot names"))
    monkeypatch.setattr(ancestry, "process_table", table)
    monkeypatch.setattr(ancestry, "process_command_name", individual)
    assert ancestry.find_nearest_harness_anchor(400) is None
    table.assert_called_once()
    individual.assert_not_called()
    table.return_value[300] = (200, "claude")
    anchor = ancestry.find_nearest_harness_anchor(400, start_time_of=lambda pid: "start")
    assert anchor == ProcessAnchor(300, "start", "claude")

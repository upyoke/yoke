"""A later relayed hook fills the version after the surface probe cache warms."""

import json
import time

from runtime.api.api_hooks_evaluate_route_test_support import (
    _request_body,
    client as client,
    hooks_db as hooks_db,
    pytestmark as pytestmark,
)
from yoke_core.domain import db_helpers
from yoke_harness import session_relay_surface_probe_cache as cache
from yoke_harness.hooks.identity_observed import client_executor_version
from yoke_harness.session_relay_surface_probes import SurfaceProbeResult


def test_later_vscode_hook_fills_null_version(client, monkeypatch, tmp_path):
    session_id = "vscode-version-heals-on-later-hook"
    surface = "claude-vscode"
    version = "2.1.331"
    monkeypatch.setattr(cache, "relay_state_dir", lambda: tmp_path / "relay")
    monkeypatch.setattr(
        cache,
        "bounded_surface_probe",
        lambda name, **_kwargs: SurfaceProbeResult(
            name, "exec", "timeout", None, 1000, "timed out", time.time(),
        ),
    )

    def relay_hook():
        return client.post(
            "/v1/hooks/evaluate",
            json=_request_body(
                event_name="UserPromptSubmit",
                entrypoint=surface,
                executor_version=client_executor_version("claude-code", surface),
                stdin=json.dumps(dict(session_id=session_id, cwd="/client/repo", project_id=1)),
            ),
        )

    def stored_identity():
        conn = db_helpers.connect()
        try:
            return conn.execute(
                "SELECT executor_surface, executor_version FROM harness_sessions "
                "WHERE session_id = %s",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()

    assert relay_hook().status_code == 200
    assert stored_identity()["executor_surface"] == surface
    assert stored_identity()["executor_version"] is None

    cache.update_surface_probe_cache((
        SurfaceProbeResult(surface, "exec", "ok", version, 20, None, time.time()),
    ))
    assert stored_identity()["executor_version"] is None
    assert relay_hook().status_code == 200
    assert stored_identity()["executor_version"] == version

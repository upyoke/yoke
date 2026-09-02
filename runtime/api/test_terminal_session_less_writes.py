"""Onboarding's writes complete in the shell a stranger actually uses.

A live install stopped at the last stage of its wizard's Apply because
``project_structure.patch.apply`` refused a process with no harness
session — the state every terminal is in before a harness has ever run
on the machine. These are the same calls from the same state, plus the
two ways an actor is named: the universe's operating human locally, and
the verified actor an https caller already carries.
"""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_core.domain import session_less_actor_binding
from yoke_core.domain.yoke_function_dispatch import dispatch


PATCH_OPS = [{
    "op": "put",
    "family": "hosting-posture",
    "attachment": "project",
    "payload": {"posture": "no-yoke-managed-host"},
}]


@pytest.fixture
def no_session(monkeypatch):
    """A process no harness ever touched: no env, no anchor, no family."""
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("YOKE_ACTOR_ID", raising=False)


def _seeded_human(path) -> int:
    conn = _conn(path)
    try:
        row = conn.execute(
            "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return int(row["id"])


def _apply_patch_spy():
    seen: list = []

    def _apply(*args, **kwargs):
        seen.append((args, kwargs))
        return {"project_id": "yoke", "applied_ops": list(PATCH_OPS)}

    return seen, _apply


def _patch_request(actor_id=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="project_structure.patch.apply",
        actor=ActorContext(actor_id=actor_id, session_id=""),
        target=TargetRef(kind="project_structure", project_id="yoke"),
        payload={"project_id": "yoke", "ops": PATCH_OPS},
    )


def test_project_structure_patch_applies_from_a_plain_terminal(
    tmp_db,  # noqa: F811 — pytest injects the re-exported fixture
    no_session,
):
    _seen, apply_patch = _apply_patch_spy()
    with mock.patch(
        "yoke_core.domain.project_structure_write.apply_patch", apply_patch,
    ):
        response = dispatch(_patch_request(), ambient_session_id="")
    assert response.success, response.error and response.error.message
    assert response.error is None


def _actor_spy():
    """Capture the actor the write itself receives."""
    seen: list[str] = []

    def _apply(project_id, ops, actor=None):
        seen.append(str(actor or ""))
        return {"project_id": project_id, "applied_ops": list(ops)}

    return seen, _apply


def test_the_terminal_write_is_attributed_to_the_operating_human(
    tmp_db,  # noqa: F811 — pytest injects the re-exported fixture
    no_session,
):
    seen, apply_patch = _actor_spy()
    with mock.patch(
        "yoke_core.domain.project_structure_write.apply_patch", apply_patch,
    ):
        response = dispatch(_patch_request(), ambient_session_id="")
    assert response.success, response.error and response.error.message
    assert seen == [str(_seeded_human(tmp_db))]


def test_an_authenticated_caller_keeps_the_actor_the_boundary_verified(
    tmp_db,  # noqa: F811 — pytest injects the re-exported fixture
    no_session,
):
    """Over https the boundary already named the actor; binding must not."""
    seen, apply_patch = _actor_spy()
    verified = str(_seeded_human(tmp_db))
    # Settle this universe's operating-actor grant first, so what the
    # assertion below measures is the binding and not the permission gate.
    session_less_actor_binding.operating_actor_id()
    with (
        mock.patch(
            "yoke_core.domain.project_structure_write.apply_patch", apply_patch,
        ),
        mock.patch.object(
            session_less_actor_binding, "operating_actor_id",
            return_value="99999",
        ),
    ):
        response = dispatch(
            _patch_request(actor_id=verified), ambient_session_id="",
        )
    assert response.success, response.error and response.error.message
    assert seen == [verified]


def test_the_wizard_stage_that_stopped_the_install_now_completes(
    tmp_db,  # noqa: F811 — pytest injects the re-exported fixture
    no_session,
):
    """`onboard_apply_hosting_posture.record` is Apply's own call site."""
    from yoke_cli.config import onboard_apply_hosting_posture
    from yoke_contracts import hosting_posture

    _seen, apply_patch = _apply_patch_spy()
    with mock.patch(
        "yoke_core.domain.project_structure_write.apply_patch", apply_patch,
    ):
        result = onboard_apply_hosting_posture.record(
            project="yoke",
            posture=hosting_posture.POSTURE_NO_YOKE_MANAGED_HOST,
        )
    assert result is not None


def test_the_install_harness_report_persists_instead_of_warning(
    tmp_db,  # noqa: F811 — pytest injects the re-exported fixture
    no_session,
):
    """Its failure was soft, so a stranger lost the report in silence."""
    request = FunctionCallRequest(
        function="harness.machine_report.upsert",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={
            "project_id": 1,
            "reports": [{"harness_id": "claude", "glue_written": True}],
        },
    )
    response = dispatch(request, ambient_session_id="")
    assert response.success, response.error and response.error.message

"""Disposable Shipping fixture guards, registered writes and population replay."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import local_shipping_seed as seed


@pytest.mark.parametrize(
    "name,config",
    [
        ("prod", {"transport": "https", "prod": False}),
        ("render-proof", {"transport": "https", "prod": False}),
        ("render-proof", {"transport": "local-postgres", "prod": True}),
        ("local", {"transport": "local-postgres", "prod": False}),
    ],
)
def test_shipping_refuses_other_authorities_before_writing(monkeypatch, name, config):
    monkeypatch.setattr(
        "yoke_core.domain.yoke_connected_env.load_active",
        lambda: SimpleNamespace(environment=name, config=config),
    )
    monkeypatch.setattr(seed, "connect", lambda: pytest.fail("opened refused database"))
    with pytest.raises(RuntimeError, match="shipping_seed_requires_render_proof"):
        seed.seed_shipping()


def test_shipping_seed_uses_real_writers_and_replays_population(test_db, monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.yoke_connected_env.load_active",
        lambda: SimpleNamespace(
            environment="render-proof",
            config={"transport": "local-postgres", "prod": False},
        ),
    )
    # Unit fixture boot is owned by test_db. The actual demo command uses full boot.
    monkeypatch.setattr(
        "yoke_core.api.server_entrypoint.ensure_core_schema", lambda: None
    )
    result = seed.seed_shipping()
    again = seed.seed_shipping()
    assert result["run_count"] == again["run_count"] == 12
    assert result["member_attachment_count"] == again["member_attachment_count"] == 204
    assert result["unique_member_count"] == 17
    assert result["shared_run_count"] == 12
    assert result["fixture_run_ids"] == again["fixture_run_ids"]
    assert result["restricted_reader_actor_id"] == again["restricted_reader_actor_id"]
    reader = result["restricted_reader_actor_id"]
    from yoke_core.domain.actor_project_visibility import actor_visible_project_ids

    visible = actor_visible_project_ids(test_db, reader)
    assert result["project_ids"][0] in visible
    assert result["project_ids"][1] not in visible
    assert result["aux_failure_case"]["functions"]

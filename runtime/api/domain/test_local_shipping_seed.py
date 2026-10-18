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


def test_existing_demo_seed_entrypoint_routes_shipping(monkeypatch):
    from yoke_core.domain.local_demo_seed import seed_demo_items

    receipt = {"ok": True, "scenario": "shipping"}
    monkeypatch.setattr(seed, "seed_shipping", lambda: receipt)
    assert seed_demo_items(scenario="shipping") is receipt


def test_shipping_requires_boot_before_fixture_writes(test_db, monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.yoke_connected_env.load_active",
        lambda: SimpleNamespace(
            environment="render-proof",
            config={"transport": "local-postgres", "prod": False},
        ),
    )
    monkeypatch.setattr(
        "yoke_core.domain.schema_common._table_exists", lambda *args: False
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_runs_schema.cmd_init",
        lambda: pytest.fail("created fixture schema before review boot"),
    )
    with pytest.raises(RuntimeError, match="shipping_seed_database_unprepared"):
        seed.seed_shipping()

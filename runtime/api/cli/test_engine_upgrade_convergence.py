"""Serving a machine-local universe with the engine that is actually running.

An upgrade replaces the code and nothing else, so the questions here are all
about what the new build does before it touches what the old one left: does it
recognize the universe as its own, does it notice the schema is behind, does it
say so once about a project checkout whose teaching is now stale — and does it
refuse loudly rather than serve a database it could not converge.
"""

from __future__ import annotations

import json

import pytest

from yoke_cli import engine_upgrade_convergence as convergence


class _Convergence:
    """Stand-in for the engine module, recording what the client asked of it."""

    def __init__(self, *, owned: bool = True, fails: BaseException | None = None):
        self.owned = owned
        self.fails = fails
        self.converge_calls = 0

    def serves_own_universe(self, dsn: str) -> bool:
        return self.owned

    def converge_serving_schema(self) -> None:
        self.converge_calls += 1
        if self.fails is not None:
            raise self.fails


@pytest.fixture()
def machine_home(tmp_path, monkeypatch):
    """Point the receipt at a throwaway machine home."""
    home = tmp_path / "yoke-home"
    home.mkdir()
    monkeypatch.setattr(convergence.machine_config, "yoke_home", lambda: home)
    return home


@pytest.fixture()
def wiring(monkeypatch):
    """Replace the engine, the ambient address, and the layer comparison."""

    def install(
        engine: _Convergence,
        *,
        identity: str = "engine 1.2.3",
        dsn: str = "postgresql://yoke@/yoke",
        stale_layer=None,
    ):
        monkeypatch.setattr(
            convergence.importlib, "import_module", lambda _name: engine
        )
        monkeypatch.setattr(convergence, "engine_identity", lambda: identity)
        monkeypatch.setattr(convergence, "_ambient_dsn", lambda: dsn)
        monkeypatch.setattr(
            convergence,
            "_pending_operating_layer_offer",
            lambda receipt, ident: stale_layer or ("", ""),
        )
        return engine

    return install


def test_first_serve_after_upgrade_converges_the_universe(machine_home, wiring):
    engine = wiring(_Convergence())

    report = convergence.converge_for_serving()

    assert report["status"] == convergence.STATUS_CONVERGED
    assert engine.converge_calls == 1


def test_second_serve_on_the_same_build_does_not_reconverge(machine_home, wiring):
    engine = wiring(_Convergence())

    convergence.converge_for_serving()
    report = convergence.converge_for_serving()

    assert report["status"] == convergence.STATUS_CURRENT
    assert engine.converge_calls == 1


def test_a_newer_build_converges_the_same_universe_again(
    machine_home, monkeypatch, wiring
):
    engine = wiring(_Convergence(), identity="engine 1.2.3")
    convergence.converge_for_serving()

    monkeypatch.setattr(convergence, "engine_identity", lambda: "engine 1.3.0")
    report = convergence.converge_for_serving()

    assert report["status"] == convergence.STATUS_CONVERGED
    assert engine.converge_calls == 2


def test_a_universe_this_machine_does_not_own_is_left_alone(machine_home, wiring):
    engine = wiring(_Convergence(owned=False))

    report = convergence.converge_for_serving()

    assert report["status"] == convergence.STATUS_FOREIGN_UNIVERSE
    assert engine.converge_calls == 0
    assert not convergence.receipt_path().exists()


def test_an_unnamed_build_converges_every_time(machine_home, wiring):
    engine = wiring(_Convergence(), identity="")

    convergence.converge_for_serving()
    convergence.converge_for_serving()

    assert engine.converge_calls == 2


def test_a_failed_converge_refuses_with_the_recovery(machine_home, wiring):
    wiring(_Convergence(fails=RuntimeError("cluster is not running")))

    with pytest.raises(convergence.LocalUniverseConvergenceError) as raised:
        convergence.converge_for_serving()

    message = str(raised.value)
    assert "cluster is not running" in message
    assert "yoke onboard --local" in message


def test_a_refusal_outside_the_exception_hierarchy_is_still_diagnosed(
    machine_home, wiring
):
    """Schema-authority refusals subclass BaseException on purpose."""

    class Refused(BaseException):
        pass

    wiring(_Convergence(fails=Refused("not the serving build")))

    with pytest.raises(convergence.LocalUniverseConvergenceError):
        convergence.converge_for_serving()


def test_an_unreadable_receipt_converges_rather_than_claiming_currency(
    machine_home, wiring
):
    engine = wiring(_Convergence())
    convergence.converge_for_serving()
    convergence.receipt_path().write_text("{ not json", encoding="utf-8")

    report = convergence.converge_for_serving()

    assert report["status"] == convergence.STATUS_CONVERGED
    assert engine.converge_calls == 2


def test_a_stale_project_layer_is_emitted_and_recorded(machine_home, wiring):
    offer = ("refresh with `yoke project install /repo`", "/repo")
    wiring(_Convergence(), stale_layer=offer)
    emitted: list[str] = []

    report = convergence.converge_for_serving(emit=emitted.append)

    assert report["operating_layer_offer"] == offer[0]
    assert emitted == [offer[0]]
    recorded = json.loads(convergence.receipt_path().read_text(encoding="utf-8"))
    assert recorded["operating_layer_notices"]["/repo"] == "engine 1.2.3"


def test_the_offer_is_suppressed_only_for_the_build_that_made_it(
    machine_home, monkeypatch, wiring
):
    receipt = {
        "schema": convergence.RECEIPT_SCHEMA,
        "operating_layer_notices": {"/repo": "engine 1.2.3"},
    }

    class _Stale:
        class receipt:  # noqa: D106 - shape-only stand-in for the comparison
            project_root = "/repo"
            source_engine_release = "1.0.0"

    monkeypatch.setattr(
        "yoke_cli.operating_layer_drift.stale_installed_layer",
        lambda _path: _Stale,
    )
    monkeypatch.setattr(
        "yoke_cli.operating_layer_drift.layer_refresh_advice",
        lambda _installed: "refresh it",
    )

    same_build = convergence._pending_operating_layer_offer(receipt, "engine 1.2.3")
    newer_build = convergence._pending_operating_layer_offer(receipt, "engine 1.3.0")

    assert same_build == ("", "")
    assert newer_build == ("refresh it", "/repo")


def test_engine_identity_names_an_installed_wheel(monkeypatch):
    monkeypatch.setattr(
        "yoke_contracts.engine_version.installed_engine_version",
        lambda: "0.1.1+launch.308",
    )

    assert convergence.engine_identity() == "engine 0.1.1+launch.308"


def test_engine_identity_names_a_source_checkout_by_its_commit(monkeypatch):
    monkeypatch.setattr(
        "yoke_contracts.engine_version.installed_engine_version", lambda: ""
    )
    monkeypatch.setattr(
        convergence, "_engine_module_origin", lambda: "/checkout/packages/x/__init__.py"
    )
    monkeypatch.setattr(
        "yoke_contracts.install_binding.source_checkout_root",
        lambda _origin: "/checkout",
    )
    monkeypatch.setattr(
        "yoke_cli.transport.source_build_skew.head_commit", lambda _root: "abc123"
    )

    assert convergence.engine_identity() == "source abc123"


def test_engine_identity_is_empty_when_neither_source_answers(monkeypatch):
    monkeypatch.setattr(
        "yoke_contracts.engine_version.installed_engine_version", lambda: ""
    )
    monkeypatch.setattr(convergence, "_engine_module_origin", lambda: "")

    assert convergence.engine_identity() == ""

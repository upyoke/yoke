"""The UI proxy reaches its control plane the way the rest of Yoke does.

Dispatching every admitted call in-process answers correctly only when
this machine holds the database. On an https connection it holds nothing,
so reads that resolve tenant-owned configuration decide against a local
view that does not exist — QA artifact storage is the one that bites, and
readable evidence came back as "not portable" on a server whose control
plane serves it happily.

Routing by connection fixes that, and carries an identity question with
it: a relayed call must let the server bind the authenticated actor and
must never carry one this process or its caller supplied.
"""

from __future__ import annotations

import pytest

from yoke_core.ui import function_proxy, proxy_transport


class _Recorder:
    """Stands in for whichever route the proxy chose."""

    def __init__(self, result=None):
        self.calls = []
        self._result = result or {}

    def relay(self, **kwargs):
        self.calls.append(("relay", kwargs))
        return _Response(self._result)

    def dispatch(self, request, **kwargs):
        self.calls.append(("dispatch", request, kwargs))
        return _Response(self._result)


class _Response:
    def __init__(self, result):
        self._result = result

    def model_dump(self, mode="json"):
        return {"success": True, "result": self._result}


@pytest.fixture()
def relayed(monkeypatch):
    monkeypatch.setattr(proxy_transport, "relays_to_server", lambda: True)
    recorder = _Recorder({"disposition": "ready", "download_url": "https://x/y"})
    monkeypatch.setattr(proxy_transport, "relay_call", recorder.relay)
    import yoke_core.domain.yoke_function_dispatch as dispatch_module

    monkeypatch.setattr(dispatch_module, "dispatch", recorder.dispatch)
    return recorder


@pytest.fixture()
def local(monkeypatch):
    monkeypatch.setattr(proxy_transport, "relays_to_server", lambda: False)
    recorder = _Recorder({"rows": []})

    def _refuse_relay(**kwargs):
        raise AssertionError("a local connection must not relay")

    monkeypatch.setattr(proxy_transport, "relay_call", _refuse_relay)
    import yoke_core.domain.yoke_function_dispatch as dispatch_module

    monkeypatch.setattr(dispatch_module, "dispatch", recorder.dispatch)
    monkeypatch.setattr(
        "yoke_core.ui.local_operator_actor.resolve_local_operator_actor",
        lambda: 2,
    )
    return recorder


ARTIFACT_ENVELOPE = {
    "function": "qa.artifact.read",
    "target": {"kind": "qa_requirement", "qa_requirement_id": 27265},
    "payload": {"artifact_id": 18718},
}


def test_an_artifact_read_goes_to_the_server_over_https(relayed):
    """The failure this prevents: evidence the control plane serves fine
    reported as "not portable" because a local process with no local view
    of the artifact store answered for it."""
    payload, status = function_proxy.proxy_function_call(dict(ARTIFACT_ENVELOPE))

    assert status == 200
    assert payload["result"]["disposition"] == "ready"
    route, kwargs = relayed.calls[0]
    assert route == "relay"
    assert kwargs["function_id"] == "qa.artifact.read"
    assert kwargs["payload"] == {"artifact_id": 18718}
    assert kwargs["target"].qa_requirement_id == 27265


def test_a_local_connection_still_dispatches_in_process(local):
    payload, status = function_proxy.proxy_function_call({
        "function": "items.list.run", "payload": {},
    })

    assert status == 200
    route, request, kwargs = local.calls[0]
    assert route == "dispatch"
    assert request.function == "items.list.run"
    # The browser has no harness session, and ambient resolution stays
    # pinned off so the SERVER process's own ancestry is never read as one.
    assert kwargs["ambient_session_id"] == ""


def test_the_local_operator_still_fills_an_actor_bound_read(local):
    function_proxy.proxy_function_call({"function": "inbox.list", "payload": {}})

    _, request, _ = local.calls[0]
    assert request.actor.actor_id == "2"


@pytest.mark.parametrize(
    "function_id",
    ["items.delete", "qa.case.run", "lifecycle.transition", ""],
)
def test_a_function_off_the_roster_is_refused_on_either_transport(
    function_id, relayed,
):
    """The closed roster is the security boundary and the transport must
    not become a way around it."""
    payload, status = function_proxy.proxy_function_call({
        "function": function_id, "payload": {},
    })

    assert status == 403
    assert payload["error"]["code"] == "function_not_allowed"
    assert relayed.calls == []


def test_a_caller_supplied_actor_never_travels_to_the_server(relayed):
    """A loopback session token stands for a machine, not a person. An
    actor named in the envelope is a claim, and the relay's own credential
    is the only identity the server may act on."""
    function_proxy.proxy_function_call({
        **ARTIFACT_ENVELOPE,
        "actor": {"actor_id": "999", "session_id": "forged-session"},
    })

    _, kwargs = relayed.calls[0]
    assert "actor" not in kwargs
    # The request id is a uuid4 this process mints, and a random hex string
    # carries a short forged id like "999" often enough to fail a scan of
    # the whole call for a reason that has nothing to do with identity.
    carried = {key: value for key, value in kwargs.items() if key != "request_id"}
    assert "999" not in repr(carried)
    assert "forged-session" not in repr(carried)


def test_a_caller_supplied_actor_is_dropped_in_process_too(local):
    function_proxy.proxy_function_call({
        "function": "items.list.run",
        "payload": {},
        "actor": {"actor_id": "999", "session_id": "forged-session"},
    })

    _, request, _ = local.calls[0]
    assert request.actor.actor_id is None
    assert request.actor.session_id == ""


def test_an_unbound_process_keeps_dispatching_in_process(monkeypatch):
    """Relaying needs positive evidence. A test run and a local universe
    are both unbound, and neither may start relaying because a config
    file was absent — the status quo is the in-process route."""
    from yoke_core.domain import yoke_connected_env

    monkeypatch.setattr(yoke_connected_env, "load_active", lambda *a, **k: None)
    assert proxy_transport.relays_to_server() is False


def test_an_unreadable_binding_keeps_dispatching_in_process(monkeypatch):
    from yoke_core.domain import yoke_connected_env

    def _unreadable(*args, **kwargs):
        raise RuntimeError("binding unreadable")

    monkeypatch.setattr(yoke_connected_env, "load_active", _unreadable)
    assert proxy_transport.relays_to_server() is False


def _binding(backend: str):
    class _Env:
        pass

    env = _Env()
    env.backend = backend
    return env


def test_a_local_postgres_binding_dispatches_in_process(monkeypatch):
    from yoke_core.domain import db_backend, yoke_connected_env

    monkeypatch.setattr(
        yoke_connected_env, "load_active",
        lambda *a, **k: _binding(db_backend.POSTGRES),
    )
    assert proxy_transport.relays_to_server() is False


def test_an_https_binding_relays(monkeypatch):
    from yoke_core.domain import yoke_connected_env

    monkeypatch.setattr(
        yoke_connected_env, "load_active", lambda *a, **k: _binding("https"),
    )
    assert proxy_transport.relays_to_server() is True

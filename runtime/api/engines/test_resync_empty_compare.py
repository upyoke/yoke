"""An empty comparison subject set needs no rendered-backlog prefetch."""

from yoke_core.engines.resync_detect_compare import stage2_compare


def test_empty_pairing_never_fetches_unused_backlog(monkeypatch):
    from yoke_core.api import service_client_structured_api_adapter as adapter

    def refuse(**kwargs):
        raise AssertionError("Empty pairing must not request comparison data")

    monkeypatch.setattr(adapter, "call_dispatcher", refuse)
    assert stage2_compare([], {}, {}, "") == []

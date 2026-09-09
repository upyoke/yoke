"""Shared fixtures for Yoke CLI adapter tests.

Adapters are DB-free pre-dispatch under the relay contract: raw item
refs ride the envelope target (``TargetRef.public_ref``) and resolve
server-side in the dispatcher. CLI tests stub ``dispatch`` and assert
the captured envelope, so no item-ref parser stub is needed here.
"""

from __future__ import annotations

import pytest

from yoke_cli.transport.https import relay_https


@pytest.fixture(autouse=True)
def _default_onboard_rich_glyphs(monkeypatch):
    """Keep wizard rendering tests independent of the runner's ambient TERM."""
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "0")


@pytest.fixture(autouse=True)
def _skip_https_connection_backoff(monkeypatch):
    """Exercise retry attempts without spending the production wait budget."""
    defaults = relay_https.__kwdefaults__
    assert defaults is not None
    monkeypatch.setitem(defaults, "sleep", lambda _seconds: None)


@pytest.fixture(autouse=True)
def _clear_inherited_launch_context(monkeypatch):
    """Keep hook-payload tests independent of the runner's ambient launch.

    A relay-launched worker inherits the launch context its own native was
    started with, and a hook correctly projects that live attestation into
    the payload it composes. Running these tests inside such a worker would
    otherwise fail an exact-payload comparison for a reason that has nothing
    to do with the code under test. Only the test environment is cleared; a
    test that needs a launch context sets its own.
    """
    from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV

    monkeypatch.delenv(LAUNCH_CONTEXT_ENV, raising=False)

"""The tree-binding check hosted at the pytest startup layer.

An entry-point guard only covers the entries it was installed in. These
tests hold the startup check to the property that motivates it: a raw
``python3 -m pytest`` — no wrapper, no QA case — is judged too, while the
runs that already judged their tree pay nothing extra.
"""

from __future__ import annotations

import contextlib
import importlib.util
from pathlib import Path

import pytest

from yoke_core.domain import verification_tree_binding
from yoke_core.domain import verification_tree_binding_pytest_startup as startup

LANE = "/repo/.worktrees/lane"
OTHER_TREE = "/repo"
SESSION = "session-abc"

REPO_ROOT = Path(__file__).resolve().parents[3]


def _claims(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session: str = SESSION,
    worktrees: tuple[str, ...] = (LANE,),
) -> list[str]:
    """Substitute session identity and the claim lookup.

    Returns the list the lookup appends to, so a test can assert the
    control plane was never consulted.
    """
    consulted: list[str] = []

    def _lookup(session_id: str):
        consulted.append(session_id)
        return verification_tree_binding.ClaimLookup(worktrees=worktrees)

    monkeypatch.setattr(
        verification_tree_binding, "ambient_session_id", lambda: session
    )
    monkeypatch.setattr(
        verification_tree_binding, "resolve_claim_worktrees", _lookup
    )
    return consulted


def test_raw_run_outside_the_claimed_lane_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _claims(monkeypatch)
    env: dict[str, str] = {}

    verdict = startup.pytest_startup_verdict(
        OTHER_TREE, argv=["pytest", "-n", "4", "runtime/api"], env=env
    )

    assert verdict.notice is None
    assert verdict.refusal is not None
    # The operator's next move is in the message or it is nowhere.
    assert LANE in verdict.refusal
    assert OTHER_TREE in verdict.refusal
    assert verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG in verdict.refusal
    # A refused run stays unmarked: nothing downstream may inherit a pass.
    assert startup.BINDING_EVALUATED_ENV not in env


def test_run_inside_the_claimed_lane_proceeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _claims(monkeypatch)
    env: dict[str, str] = {}

    verdict = startup.pytest_startup_verdict(
        f"{LANE}/runtime", argv=["pytest"], env=env
    )

    assert verdict.refusal is None
    assert verdict.notice is None
    assert env[startup.BINDING_EVALUATED_ENV] == "1"


def test_session_holding_no_lane_is_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Main-checkout source-dev keeps working exactly as before."""
    _claims(monkeypatch, worktrees=())

    verdict = startup.pytest_startup_verdict(
        OTHER_TREE, argv=["pytest"], env={}
    )

    assert verdict.refusal is None
    assert verdict.notice is None


def test_override_flag_in_argv_turns_the_refusal_into_a_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _claims(monkeypatch)

    verdict = startup.pytest_startup_verdict(
        OTHER_TREE,
        argv=["pytest", verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG],
        env={},
    )

    assert verdict.refusal is None
    assert verdict.notice is not None
    # Both trees named, so a deliberate cross-tree green stays attributable.
    assert LANE in verdict.notice
    assert OTHER_TREE in verdict.notice


def test_marked_environment_skips_the_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrapper or QA run that already judged pays nothing here.

    The assertion is on the lookup itself, not just the verdict: the
    check runs on every pytest start, including once per xdist worker,
    so a repeated control-plane round trip would be the cost that gets
    it removed.
    """
    consulted = _claims(monkeypatch)
    env = {startup.BINDING_EVALUATED_ENV: "1"}

    verdict = startup.pytest_startup_verdict(
        OTHER_TREE, argv=["pytest"], env=env
    )

    assert verdict.refusal is None
    assert verdict.notice is None
    assert consulted == []


def test_unreachable_control_plane_proceeds_but_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verification_tree_binding, "ambient_session_id", lambda: SESSION
    )
    monkeypatch.setattr(
        verification_tree_binding,
        "resolve_claim_worktrees",
        lambda _session: verification_tree_binding.ClaimLookup(
            reachable=False, detail="connection refused"
        ),
    )
    env: dict[str, str] = {}

    verdict = startup.pytest_startup_verdict(
        OTHER_TREE, argv=["pytest"], env=env
    )

    assert verdict.refusal is None
    assert verdict.notice is not None
    assert "connection refused" in verdict.notice
    # One notice per run, not one per worker.
    assert env[startup.BINDING_EVALUATED_ENV] == "1"


def test_marker_handed_to_a_child_is_a_copy() -> None:
    source = {"PATH": "/usr/bin"}

    marked = startup.with_binding_evaluated(source)

    assert marked[startup.BINDING_EVALUATED_ENV] == "1"
    assert marked["PATH"] == "/usr/bin"
    assert startup.BINDING_EVALUATED_ENV not in source


def _load_repo_root_conftest():
    """Execute the repo root conftest as its own module object.

    Loading it by path rather than importing the already-loaded conftest
    is what makes this a wiring test: the guard runs at module exec, so
    only a real execution proves the conftest calls it.
    """
    spec = importlib.util.spec_from_file_location(
        "repo_root_conftest_wiring_probe", REPO_ROOT / "conftest.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CaptureManager:
    """Stands in for pytest's capture manager, counting suspensions."""

    def __init__(self) -> None:
        self.suspensions = 0

    @contextlib.contextmanager
    def global_and_fixture_disabled(self):
        self.suspensions += 1
        yield


class _Config:
    """Stands in for the pytest config the conftest hook receives."""

    def __init__(self, capture: object) -> None:
        self._capture = capture
        self.pluginmanager = self

    def getplugin(self, name: str) -> object:
        assert name == "capturemanager"
        return self._capture


def test_repo_root_conftest_stops_collection_on_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The check is wired into the layer that cannot be bypassed."""
    refusal = f"pytest TREE-BINDING REFUSAL: cd {LANE}"
    monkeypatch.setattr(
        startup,
        "pytest_startup_verdict",
        lambda _tree: verification_tree_binding.TreeBindingVerdict(
            refusal=refusal
        ),
    )

    with pytest.raises(SystemExit) as raised:
        _load_repo_root_conftest()

    assert (
        raised.value.code
        == startup.TREE_BINDING_REFUSED_EXIT_STATUS
    )
    # A traceback here would bury the one line the operator must read.
    assert capsys.readouterr().err.strip() == refusal


def test_repo_root_conftest_says_a_notice_past_output_capture(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A cross-tree or unverified run must not read like a clean one.

    pytest's global capture is already installed when a conftest is
    imported, so the notice is only visible if it is written with
    capture suspended -- which is why the suspension itself is asserted
    rather than just the text.
    """
    notice = "pytest: --allow-tree-mismatch — verifying the other tree."
    monkeypatch.setattr(
        startup,
        "pytest_startup_verdict",
        lambda _tree: verification_tree_binding.TreeBindingVerdict(
            notice=notice
        ),
    )
    conftest = _load_repo_root_conftest()
    capture = _CaptureManager()

    conftest.pytest_configure(_Config(capture))

    assert capture.suspensions == 1
    assert capsys.readouterr().err.strip() == notice


def test_repo_root_conftest_stays_silent_without_a_notice(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ordinary bound run adds no line to every pytest start."""
    monkeypatch.setattr(
        startup,
        "pytest_startup_verdict",
        lambda _tree: verification_tree_binding.TreeBindingVerdict(),
    )
    conftest = _load_repo_root_conftest()
    capture = _CaptureManager()

    conftest.pytest_configure(_Config(capture))

    assert capture.suspensions == 0
    assert capsys.readouterr().err == ""

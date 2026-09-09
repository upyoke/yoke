"""Reading material no registered project owns is not a checkout mix-up.

An operator hands an agent a reference document, an installed harness config,
a launcher on ``PATH``. Those live outside every recorded project checkout, so
a read-shaped call naming one has nothing to do with the wrong-checkout defect
this guard exists to catch, and it now passes.

The boundary is narrow on purpose, and each half is proved here. Project code
stays governed — a recorded repo root, another project's checkout, a worktree
lane under one — regardless of how read-shaped the call is. So is tool state:
a dot-directory in the home holds harness configuration, credentials, and
per-session scratch, and which of those may be read stays the curated
sanctioned-installed-read decision rather than becoming a side effect of this
one. And a write never inherits a read's exemption: an output redirect, a
mutating verb, or a mutation chained onto a read all still refuse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_session_cwd, lint_session_cwd_validate


ITEM_ID = 4181
SESSION = "sid-external-read"


@pytest.fixture(autouse=True)
def _tmp_paths_are_not_free(monkeypatch):
    """Keep ``/tmp`` free but drop ``/var/folders``.

    Every path in this file is built under pytest's ``tmp_path``, which lives
    under ``/var/folders`` on macOS — on the free-path allowlist, so without
    this the whole file would pass while proving nothing.
    """
    monkeypatch.setattr(
        lint_session_cwd_validate,
        "FREE_PATH_PREFIXES",
        ("/tmp", "/private/tmp", "/dev"),
    )


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A synthetic operator home, so no test reads the real one."""
    home_path = tmp_path / "operator-home"
    home_path.mkdir()
    monkeypatch.setenv("HOME", str(home_path))
    return home_path


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


@pytest.fixture
def lane(conn, repo):
    """A session holding one implementation lane in a recorded checkout."""
    register_machine_checkout(Path(repo).parent / "machine-config", Path(repo), 1)
    seed_item(conn, item_id=ITEM_ID, branch=f"YOK-{ITEM_ID}", repo_path=repo)
    seed_item_claim(conn, SESSION, item_id=ITEM_ID)
    lane_path = repo / ".worktrees" / f"YOK-{ITEM_ID}"
    lane_path.mkdir(parents=True)
    return lane_path


@pytest.fixture
def external(home):
    """Reference material in the operator's home, outside every checkout."""
    root = home / "Downloads" / "reference"
    root.mkdir(parents=True)
    reference = root / "synthesis.md"
    reference.write_text("reference notes\n")
    return reference


def _bash(command: str, cwd) -> dict:
    return {
        "session_id": SESSION,
        "cwd": str(cwd),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def _read_tool(file_path, cwd) -> dict:
    return {
        "session_id": SESSION,
        "cwd": str(cwd),
        "tool_name": "Read",
        "tool_input": {"file_path": str(file_path)},
    }


# ---------------------------------------------------------------------------
# Read-only external reference inputs are permitted
# ---------------------------------------------------------------------------


class TestExternalReferenceReadsAllow:
    def test_read_tool_on_an_external_reference_file(self, conn, lane, external):
        verdict = lint_session_cwd.evaluate_pre_tool_use(_read_tool(external, lane))

        assert verdict.allow is True

    def test_shell_read_of_an_external_reference_file(self, conn, lane, external):
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _bash(f"cat {external}", lane)
        )

        assert verdict.allow is True

    @pytest.mark.parametrize(
        "relative", [".cursor/hooks.json", ".local/bin", ".yoke/relay-instances"]
    )
    def test_installed_tool_surfaces_read_through_the_curated_allowlist(
        self, conn, lane, home, relative,
    ):
        # Tool state is excluded from the external-reference branch above, so
        # the reported read-only inspections of installed surfaces are covered
        # by the sanctioned-installed-read allowlist instead.
        installed = home / relative
        installed.parent.mkdir(parents=True, exist_ok=True)

        verdict = lint_session_cwd.evaluate_pre_tool_use(_read_tool(installed, lane))

        assert verdict.allow is True

    def test_listing_an_external_launcher_directory(self, conn, lane, home):
        bindir = home / ".local" / "bin"
        bindir.mkdir(parents=True)

        verdict = lint_session_cwd.evaluate_pre_tool_use(_bash(f"ls {bindir}", lane))

        assert verdict.allow is True

    def test_grepping_an_external_reference_tree(self, conn, lane, external):
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _bash(f"rg -n notes {external.parent}", lane)
        )

        assert verdict.allow is True


# ---------------------------------------------------------------------------
# Project code stays governed — reading it is not "external"
# ---------------------------------------------------------------------------


class TestProjectCodeIsNeverExternal:
    def test_a_path_outside_the_operator_home_still_refuses(self, conn, lane):
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _read_tool("/__foreign_target__/file", lane)
        )

        assert verdict.allow is False

    def test_a_payload_that_names_no_tool_still_refuses(self, conn, lane, external):
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": SESSION,
            "cwd": str(lane),
            "tool_input": {"file_path": str(external)},
        })

        assert verdict.allow is False

    @pytest.mark.parametrize(
        "relative",
        [
            ".yoke/tmp/1/sessions/other/raw.log",
            ".yoke/secrets/capability-secrets/yoke/aws-admin/credentials",
            ".codex/auth.json",
            ".codex/config.toml",
        ],
    )
    def test_home_dot_directories_stay_governed(self, conn, lane, home, relative):
        # Tool state — per-session scratch, credentials, harness config — is
        # not reference material. Which of it may be read stays the curated
        # sanctioned-installed-read decision, not a side effect of this one.
        target = home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("tool state\n")

        verdict = lint_session_cwd.evaluate_pre_tool_use(_read_tool(target, lane))

        assert verdict.allow is False

    def test_read_of_another_items_live_lane_still_refuses(
        self, conn, lane, repo,
    ):
        seed_item(conn, item_id=ITEM_ID + 1, branch="YOK-other", repo_path=repo)
        seed_item_claim(conn, "sid-neighbour", item_id=ITEM_ID + 1)
        neighbour = repo / ".worktrees" / "YOK-other"
        neighbour.mkdir(parents=True)

        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _read_tool(neighbour / "module.py", lane)
        )

        assert verdict.allow is False
        assert verdict.failure_class == "foreign_lane"

    def test_read_of_an_unclaimed_sibling_lane_still_refuses(
        self, conn, lane, repo,
    ):
        sibling = repo / ".worktrees" / "YOK-unclaimed"
        sibling.mkdir(parents=True)

        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _read_tool(sibling / "module.py", lane)
        )

        assert verdict.allow is False

    def test_read_of_the_projects_own_checkout_still_allows(self, conn, lane, repo):
        # Control-plane reads were already permitted; the external-reference
        # branch must not be read as having introduced a new ban here.
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _read_tool(repo / "module.py", lane)
        )

        assert verdict.allow is True


# ---------------------------------------------------------------------------
# A write never inherits a read's exemption
# ---------------------------------------------------------------------------


class TestWriteShapesStillRefuse:
    def test_write_tool_to_an_external_path_refuses(self, conn, lane, external):
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": SESSION,
            "cwd": str(lane),
            "tool_name": "Write",
            "tool_input": {"file_path": str(external), "content": "x"},
        })

        assert verdict.allow is False

    def test_output_redirect_onto_an_external_path_refuses(
        self, conn, lane, external,
    ):
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _bash(f"cat {external} > {external.parent}/copy.md", lane)
        )

        assert verdict.allow is False

    def test_a_mutation_chained_onto_a_read_refuses(self, conn, lane, external):
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _bash(f"cat {external} && cp {external} {external.parent}/copy.md", lane)
        )

        assert verdict.allow is False

    def test_a_mutating_verb_on_an_external_path_refuses(
        self, conn, lane, external,
    ):
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _bash(f"touch {external.parent}/created.md", lane)
        )

        assert verdict.allow is False

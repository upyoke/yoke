"""Read-shaped calls pass anywhere; mutations retain lane authority."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import (
    lint_session_cwd,
    lint_lane_main_write,
    lint_session_cwd_path_authority,
)


ITEM_ID = 4181
SESSION = "sid-external-read"


@pytest.fixture(autouse=True)
def _tmp_paths_are_not_free(monkeypatch):
    """Empty the free-path allowlist for this file.

    Every path here is built under pytest's ``tmp_path``, and where that lands
    is the operating system's choice: ``/var/folders`` on macOS, ``/tmp`` on
    Linux. Both are on the production allowlist, so naming either one to keep
    would leave the other incidentally free — and a free target allows before
    any of the authority under test is consulted, turning every refusal
    assertion here green while proving nothing.
    """
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.setattr(
        lint_session_cwd_path_authority, "_STATIC_FREE_PATH_PREFIXES", ()
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
        verdict = lint_session_cwd.evaluate_pre_tool_use(_bash(f"cat {external}", lane))

        assert verdict.allow is True

    @pytest.mark.parametrize(
        "relative", [".cursor/hooks.json", ".local/bin", ".yoke/relay-instances"]
    )
    def test_installed_tool_surfaces_are_readable(
        self,
        conn,
        lane,
        home,
        relative,
    ):
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
# Read paths include dot folders and other checkouts
# ---------------------------------------------------------------------------


class TestReadsAcrossRoots:
    def test_a_path_outside_the_operator_home_allows(self, conn, lane):
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _read_tool("/__foreign_target__/file", lane)
        )

        assert verdict.allow is True

    def test_a_payload_that_names_no_tool_still_refuses(self, conn, lane, external):
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            {
                "session_id": SESSION,
                "cwd": str(lane),
                "tool_input": {"file_path": str(external)},
            }
        )

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
    def test_home_dot_directories_allow(self, conn, lane, home, relative):
        target = home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("tool state\n")

        verdict = lint_session_cwd.evaluate_pre_tool_use(_read_tool(target, lane))

        assert verdict.allow is True

    def test_read_of_another_items_live_lane_allows(
        self,
        conn,
        lane,
        repo,
    ):
        seed_item(conn, item_id=ITEM_ID + 1, branch="YOK-other", repo_path=repo)
        seed_item_claim(conn, "sid-neighbour", item_id=ITEM_ID + 1)
        neighbour = repo / ".worktrees" / "YOK-other"
        neighbour.mkdir(parents=True)

        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _read_tool(neighbour / "module.py", lane)
        )

        assert verdict.allow is True

    def test_read_of_an_unclaimed_sibling_lane_allows(
        self,
        conn,
        lane,
        repo,
    ):
        sibling = repo / ".worktrees" / "YOK-unclaimed"
        sibling.mkdir(parents=True)

        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _read_tool(sibling / "module.py", lane)
        )

        assert verdict.allow is True

    def test_read_of_the_projects_own_checkout_still_allows(self, conn, lane, repo):
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _read_tool(repo / "module.py", lane)
        )

        assert verdict.allow is True


# ---------------------------------------------------------------------------
# A write never inherits a read's exemption
# ---------------------------------------------------------------------------


class TestWriteShapesStillRefuse:
    def test_write_tool_to_an_external_path_refuses(self, conn, lane, external):
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            {
                "session_id": SESSION,
                "cwd": str(lane),
                "tool_name": "Write",
                "tool_input": {"file_path": str(external), "content": "x"},
            }
        )

        assert verdict.allow is False

    def test_output_redirect_onto_an_external_path_refuses(
        self,
        conn,
        lane,
        external,
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
        self,
        conn,
        lane,
        external,
    ):
        verdict = lint_session_cwd.evaluate_pre_tool_use(
            _bash(f"touch {external.parent}/created.md", lane)
        )

        assert verdict.allow is False


@pytest.mark.parametrize(
    "command",
    [
        "ls /Applications | grep chrome", "cat /usr/share/example",
        "cat ~/.config/example", "cat ~/.codex/auth.json",
        "rg pattern {target}", "git -C {target} diff",
        "git -C {target} remote get-url origin",
        "git -C {target} config --get user.email",
        "git -C {target} branch --contains HEAD",
        "git -C {target} branch -r --merged main",
        "find {target} -exec grep -l x {{}} +",
    ],
)
def test_claimed_session_reads_any_root(conn, lane, repo, command):
    for target in (repo, repo / ".worktrees/unclaimed", Path("/other/checkout")):
        payload = _bash(command.format(target=target), lane)
        verdict = lint_session_cwd.evaluate_pre_tool_use(payload)
        assert verdict.allow is True, verdict.reason
    in_main = _bash(command.format(target=repo), repo)
    assert lint_session_cwd.evaluate_pre_tool_use(in_main).allow is True
    assert lint_lane_main_write.evaluate_pre_tool_use(in_main).allow is True


def test_yoke_call_without_operands_allows_from_any_cwd(conn, lane, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    payload = _bash("yoke items get X", outside)
    assert lint_session_cwd.evaluate_pre_tool_use(payload).allow is True


@pytest.mark.parametrize(
    "command",
    [
        "find {target} -delete", "find {target} -exec touch f ;",
        "find {target} -execdir touch f ;", "find {target} -ok touch f ;",
        "find {target} -fprint {target}/out", "find {target} -fls {target}/out",
        "git -C {target} diff --output={target}/out",
        "git -C {target} branch topic", "git -C {target} config k v",
        "git -C {target} remote add origin url", "git -C {target} checkout topic",
        "git -C {target} branch -D x", "find {target} -exec rm {{}} +",
        "rg --pre cat pattern {target}", "rg --pre=cat pattern {target}",
        "cat {target}/f > {target}/out", "touch {target}/f",
    ],
)
def test_mutating_commands_outside_lane_refuse(conn, lane, repo, external, command):
    seed_item(conn, item_id=ITEM_ID + 1, branch="YOK-other", repo_path=repo)
    seed_item_claim(conn, "sid-neighbour", item_id=ITEM_ID + 1)
    for target in (external.parent, repo, repo / ".worktrees/YOK-other"):
        payload = _bash(command.format(target=target), lane)
        verdict = lint_session_cwd.evaluate_pre_tool_use(payload)
        source_verdict = lint_lane_main_write.evaluate_pre_tool_use(payload)
        assert not (verdict.allow and source_verdict.allow), (command, target)

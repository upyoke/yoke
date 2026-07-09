"""Regression coverage for ``lint_session_cwd`` path-authority false positives.

These cases come from an audit of recurring ouroboros field-notes where the
PreToolUse path-authority guard extracted non-path tokens as write targets
(or blocked an executed tool binary) and denied a legitimate command. Each
test names the field-note that motivated it.

Two layers are covered:

* **Extraction** (:func:`extract_command_targets`) — pure-function tests that
  the token walk no longer surfaces grep/sed pattern operands, ``$``-bearing
  tokens, a bare ``/``, or a per-segment command name as a target. Companion
  *safety* tests prove a genuine out-of-claim write target is still surfaced
  (the fixes only narrow false positives — they never hide a real write).
* **Authorisation** (:func:`validate_targets`) — a claimed session may invoke
  a standard tool binary (``/opt/homebrew/bin/aws``) while writes outside its
  claim stay denied, and a session with no claims still passes unconditionally.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_command_targets,
)
from yoke_core.domain.lint_session_cwd_validate import (
    TOOL_DIR_PREFIXES,
    validate_targets,
)


# A representative claimed-worktree path used as the leading ``cd`` target in
# compound commands; it is the claim, so it must be the only surfaced target.
WT = "/Users/dev/yoke/.worktrees/YOK-1886"
# Another project's worktree — a genuine out-of-claim write target that must
# never be silently dropped by the false-positive fixes.
OTHER = "/Users/x/.worktrees/OTHER/file.py"


# ---------------------------------------------------------------------------
# Extraction: grep / rg pattern operands are not path targets (8820, 8881)
# ---------------------------------------------------------------------------


def test_grep_leading_slash_pattern_bare_not_extracted():
    """field-note 8881: a leading-slash grep exclusion pattern is a regex
    operand, not an absolute write target."""
    assert extract_command_targets("grep -v /fixtures runtime") == []


def test_grep_E_regex_operand_not_extracted():
    assert extract_command_targets("grep -E /foo/ file") == []


def test_grep_pattern_in_pipe_not_extracted():
    """field-note 8820: the grep clause of a pipe must not surface its
    pattern; the leading ``cd`` claim is the only real target."""
    cmd = f'cd {WT} && grep -rn TOKEN runtime | grep -v /fixtures'
    assert extract_command_targets(cmd) == [WT]


def test_rg_pattern_operand_not_extracted():
    assert extract_command_targets("rg /usr/lib src") == []


# ---------------------------------------------------------------------------
# Extraction: sed script operands are not path targets (8765)
# ---------------------------------------------------------------------------


def test_sed_range_script_in_compound_not_extracted():
    """field-note 8765: a sed range address parses as path-like but is a
    script, not a target."""
    cmd = f"cd {WT} && sed -n '/AC-11/,/AC-12/p' spec.md"
    assert extract_command_targets(cmd) == [WT]


def test_sed_single_address_script_not_extracted():
    assert extract_command_targets("sed -n '/AC-11/p' spec.md") == []


def test_sed_still_surfaces_its_file_argument():
    """The sed *file* positional is a real read target and must still be
    surfaced — only the inline script is skipped (matches the existing
    ``/^``-anchor behaviour)."""
    cmd = "sed -n '/AC-11/p' /tmp/spec.md"
    assert extract_command_targets(cmd) == ["/tmp/spec.md"]


# ---------------------------------------------------------------------------
# Extraction: unexpanded shell variables (8847)
# ---------------------------------------------------------------------------


def test_shell_variable_only_token_not_extracted():
    """field-note 8847: ``$_sock`` is unexpanded; the lint cannot resolve it."""
    assert extract_command_targets('rm -f "$_sock"') == []


def test_shell_variable_inside_absolute_path_not_extracted():
    cmd = f'cd {WT} && rm -f "/some/other/$VAR/sock"'
    assert extract_command_targets(cmd) == [WT]


# ---------------------------------------------------------------------------
# Extraction: bare filesystem root from a tokenized ``/`` operator (8791)
# ---------------------------------------------------------------------------


def test_bare_slash_operator_not_extracted():
    """field-note 8791: a lone ``/`` (e.g. ``project_tree / "templates"``
    tokenized from a patch body) is not a write target."""
    assert extract_command_targets("echo project_tree / templates") == []


def test_bare_slash_in_compound_not_extracted():
    cmd = f"cd {WT} && echo project_tree / templates"
    assert extract_command_targets(cmd) == [WT]


# ---------------------------------------------------------------------------
# Extraction: a tool binary invoked as a per-segment command name (8769+)
# ---------------------------------------------------------------------------


def test_tool_binary_command_name_after_cd_not_extracted():
    """field-notes 8771/8779/8781: a Homebrew binary executed after ``cd`` is
    the segment's command name, not a positional of ``cd``."""
    cmd = f"cd {WT} && /opt/homebrew/bin/pulumi up"
    assert extract_command_targets(cmd) == [WT]


def test_tool_binary_as_ls_positional_still_extracted_for_auth_layer():
    """``ls /opt/homebrew/bin/aws`` legitimately surfaces the binary as a
    positional; the *authorisation* layer (not extraction) allows it."""
    assert extract_command_targets("ls /opt/homebrew/bin/aws") == [
        "/opt/homebrew/bin/aws"
    ]


# ---------------------------------------------------------------------------
# Extraction SAFETY: real out-of-claim writes are still surfaced (no hole)
# ---------------------------------------------------------------------------


def test_secondary_cp_write_target_still_surfaced():
    """A write command after ``&&`` must still surface its out-of-claim
    target — the segment fixes must not hide a real write."""
    cmd = f"cd {WT} && cp evil {OTHER}"
    assert extract_command_targets(cmd) == [WT, OTHER]


def test_secondary_sed_in_place_write_target_still_surfaced():
    """``sed -i`` writes its file argument; the script-skip must not drop the
    out-of-claim file."""
    cmd = f"cd {WT} && sed -i 's/x/y/' {OTHER}"
    assert extract_command_targets(cmd) == [WT, OTHER]


def test_secondary_tee_redirect_write_target_still_surfaced():
    cmd = f"cd {WT} && cat src | tee {OTHER}"
    assert extract_command_targets(cmd) == [WT, OTHER]


def test_redirect_into_out_of_claim_path_still_surfaced():
    cmd = f"cd {WT} && echo data > {OTHER}"
    assert extract_command_targets(cmd) == [WT, OTHER]


# ---------------------------------------------------------------------------
# Authorisation: tool-dir allowlist + out-of-claim regression (8769+)
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "YOK-100").mkdir(parents=True)
    with test_database() as c:
        register_machine_checkout(tmp_path / "machine-config", repo, 1)
        seed_item(c, item_id=100, branch="YOK-100")
        seed_item_claim(c, "s1", item_id=100)
        yield c


class TestToolDirAllowlist:
    @pytest.mark.parametrize("target", [
        "/opt/homebrew/bin/pulumi",
        "/opt/homebrew/Cellar/pulumi/3.1/bin/pulumi",
        "/usr/local/bin/node",
        "/usr/bin/python3",
        "/bin/ls",
    ])
    def test_tool_binary_allowed_for_claimed_session(self, conn, target):
        verdict = validate_targets(conn, session_id="s1", targets=[target])
        assert verdict.allow, f"expected {target} authorised via tool-dir allowlist"

    def test_tool_dir_prefixes_static_contents(self):
        # Guard the allowlist against accidental narrowing.
        assert "/opt/homebrew/bin" in TOOL_DIR_PREFIXES
        assert "/opt/homebrew/Cellar" in TOOL_DIR_PREFIXES
        assert "/usr/bin" in TOOL_DIR_PREFIXES


class TestOutOfClaimStillDenied:
    """The tool-dir allowlist must not weaken claim enforcement."""

    @pytest.mark.parametrize("target", [
        "/etc/passwd",
        "/opt/other-repo/.worktrees/YOK-OTHER/file.py",
        "/Users/someone/.worktrees/OTHER/secret.py",
        # A path that merely *starts* like a tool dir but is not under one.
        "/opt/homebrew-not-really/bin/evil",
    ])
    def test_out_of_claim_write_denied(self, conn, target):
        verdict = validate_targets(conn, session_id="s1", targets=[target])
        assert not verdict.allow
        assert target in verdict.offending_target

    def test_no_claims_session_allows_unconditionally(self, conn):
        # The critical invariant: a session holding no claims is unconstrained.
        verdict = validate_targets(
            conn, session_id="session-with-no-claims", targets=["/anything/at/all"]
        )
        assert verdict.allow

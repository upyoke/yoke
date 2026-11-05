"""Git flag validation without lane or database setup.

The database-backed neighbour inspection tests retain representative allow,
write and nested-command checks; this matrix covers every flag spelling.
"""

import pytest

from yoke_core.domain.lint_lane_main_write_classify import is_write_operation


@pytest.mark.parametrize(
    "command, allow",
    [(f"git {form}", False) for form in (
        "branch -v newbr", "branch -vv newbr", "branch --verbose newbr",
        "config --unset-a k", "config --remove-s sec", "config --rem sec",
        "branch --unset-u", "branch --set-upstream-t=x", "branch -ux",
    )]
    + [(r"find . -exec git config --unset-a k \;", False)]
    + [(c, True) for c in (
        "git branch -v", "git branch -vv", "git remote get-url origin",
        "git config --get user.email", "git branch --contains HEAD",
        "find . -exec grep -l x {} +",
    )],
)
def test_git_flag_forms(command, allow):
    assert is_write_operation("Bash", {"tool_input": {"command": command}}) is not allow

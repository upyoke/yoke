"""Literal heredoc input cannot impersonate shell commands or hide writes."""

import pytest

from yoke_core.domain.path_claim_bash_parser import Mutation, extract_mutations
from yoke_core.domain.shell_expansion_scan import strip_literal_heredocs


@pytest.mark.parametrize("marker", ["'EOF'", '"EOF"'])
@pytest.mark.parametrize(
    "reader", ["cat", "python3 -", "yoke items progress-log append ITEM --stdin"]
)
def test_literal_prose_and_python_do_not_become_shell(marker, reader):
    command = (
        f"{reader} <<{marker}\n"
        "It's text with [a-z]+|regex && eval and $(rm hidden.py)\n"
        'print("unbalanced shell apostrophe: don\'t")\n'
        "EOF\n"
    )
    assert extract_mutations(command) == []


@pytest.mark.parametrize("operator", [">", ">>"])
@pytest.mark.parametrize("placement", ["before", "after"])
def test_literal_body_preserves_output_redirect(operator, placement):
    redirect = f"{operator} owned.txt"
    header = (
        f"cat {redirect} <<'EOF'"
        if placement == "before"
        else f"cat <<'EOF' {redirect}"
    )
    mutations = extract_mutations(f"{header}\nIt's | prose > fake.txt\nEOF")
    assert [(m.verb, m.target_path) for m in mutations] == [("redirect", "owned.txt")]


def test_literal_tee_preserves_its_real_target():
    mutations = extract_mutations("tee owned.txt <<'EOF'\nIt's | prose\nEOF")
    assert [(m.verb, m.target_path) for m in mutations] == [("tee", "owned.txt")]


def test_commands_before_on_opener_and_after_literal_body_remain_visible():
    command = (
        "touch before.txt\ncat <<'EOF' > owned.txt; touch inline.txt\n"
        "It's | prose\nEOF\nrm after.txt"
    )
    assert [(m.verb, m.target_path) for m in extract_mutations(command)] == [
        ("touch", "before.txt"),
        ("redirect", "owned.txt"),
        ("touch", "inline.txt"),
        ("rm", "after.txt"),
    ]


def test_multiple_literal_inputs_and_tab_stripped_delimiter():
    command = "cat <<'ONE' <<-\"TWO\" > owned.txt\nIt's | one\nONE\n\tIt's & two\n\tTWO\nrm after.txt"
    assert [(m.verb, m.target_path) for m in extract_mutations(command)] == [
        ("redirect", "owned.txt"),
        ("rm", "after.txt"),
    ]


def test_expanding_heredoc_is_preserved_and_redirect_is_detected():
    command = "cat <<EOF > owned.txt\nbody\nEOF"
    assert strip_literal_heredocs(command) == command
    assert any(m.target_path == "owned.txt" for m in extract_mutations(command))
    assert any(
        m.verb == "ambiguous"
        for m in extract_mutations("cat <<EOF > owned.txt\n$(rm hidden.txt)\nEOF")
    )


def test_literal_heredoc_spelling_inside_argv_is_unchanged():
    command = "rg \"cat <<'EOF'\" file.py"
    assert strip_literal_heredocs(command) == command


@pytest.mark.parametrize("marker", ["'E'OF", '"E"OF', "E'OF'"])
def test_partial_delimiter_match_does_not_consume_following_commands(marker):
    command = f"cat <<{marker}\ninput\nEOF\nrm owned.txt"
    assert strip_literal_heredocs(command) == command


def test_unterminated_literal_body_stays_input():
    assert extract_mutations("cat <<'EOF' > owned.txt\nIt's | prose") == [
        Mutation("redirect", "owned.txt")
    ]


def test_commented_opener_cannot_hide_a_live_mutation():
    command = "# cat <<'EOF'\nrm owned.txt\nEOF"
    assert strip_literal_heredocs(command) == command
    assert Mutation("rm", "owned.txt") in extract_mutations(command)


def test_literal_suppression_spelling_does_not_hide_a_real_write():
    command = "cat <<'EOF'\n# lint:no-worktree-path-check\nEOF\nrm owned.txt"
    assert extract_mutations(command) == [Mutation("rm", "owned.txt")]


@pytest.mark.parametrize("delimiter", ["'EOF'", "EOF"])
def test_guard_checks_real_redirect_coverage(tmp_path, delimiter):
    from yoke_core.domain.path_claim_bash_guard import evaluate_payload

    claim = {
        "id": 1,
        "owner_kind": "item",
        "owner_item_id": 1,
        "integration_target": "main",
        "state": "active",
        "covered_paths": ("owned.txt",),
        "worktree_path": str(tmp_path),
    }
    for target, outcome in (("owned.txt", "allow"), ("outside.txt", "deny")):
        verdict = evaluate_payload(
            {
                "tool_name": "Bash",
                "cwd": str(tmp_path),
                "session_id": "test-session",
                "tool_input": {
                    "command": f"cat <<{delimiter} > {target}\nIt's | text\nEOF"
                },
            },
            claim=claim,
        )
        assert verdict.outcome == outcome

"""Bash parser fail-closed / fail-open coverage."""

from __future__ import annotations

from yoke_core.domain.path_claim_bash_parser import (
    SUPPRESSION_TOKEN,
    extract_mutations,
)


class TestSimpleVerbs:
    def test_rm_single_file(self):
        muts = extract_mutations("rm runtime/api/foo.py")
        assert (muts[0].verb, muts[0].target_path) == (
            "rm",
            "runtime/api/foo.py",
        )

    def test_rm_multi_target(self):
        muts = extract_mutations("rm runtime/api/a.py runtime/api/b.py")
        paths = [m.target_path for m in muts if m.verb == "rm"]
        assert paths == ["runtime/api/a.py", "runtime/api/b.py"]

    def test_mv_destination_only(self):
        muts = extract_mutations("mv old/a.py new/b.py")
        # Only the destination is the recorded target.
        mv_targets = [m.target_path for m in muts if m.verb == "mv"]
        assert mv_targets == ["new/b.py"]

    def test_cp_destination_only(self):
        muts = extract_mutations("cp src/a.py dst/b.py")
        cp_targets = [m.target_path for m in muts if m.verb == "cp"]
        assert cp_targets == ["dst/b.py"]

    def test_truncate_target(self):
        muts = extract_mutations("truncate -s 0 logs/foo.log")
        assert any(
            m.verb == "truncate" and m.target_path == "logs/foo.log"
            for m in muts
        )

    def test_tee_target(self):
        muts = extract_mutations("tee out/foo.txt")
        assert any(
            m.verb == "tee" and m.target_path == "out/foo.txt" for m in muts
        )


class TestRedirects:
    def test_simple_redirect(self):
        muts = extract_mutations("echo hi > out/foo.txt")
        verbs = [(m.verb, m.target_path) for m in muts]
        assert ("redirect", "out/foo.txt") in verbs

    def test_append_redirect(self):
        muts = extract_mutations("echo hi >> out/foo.txt")
        verbs = [(m.verb, m.target_path) for m in muts]
        assert ("redirect", "out/foo.txt") in verbs

    def test_redirect_to_tmp_allowed(self):
        muts = extract_mutations("echo hi > /tmp/foo.txt")
        # /tmp is an explicit allow case.
        assert all(m.target_path != "/tmp/foo.txt" for m in muts)


class TestGitVerbs:
    def test_git_rm(self):
        muts = extract_mutations("git rm runtime/api/foo.py")
        assert any(
            m.verb == "git rm" and m.target_path == "runtime/api/foo.py"
            for m in muts
        )

    def test_git_restore(self):
        muts = extract_mutations("git restore runtime/api/foo.py")
        assert any(
            m.verb == "git restore" and m.target_path == "runtime/api/foo.py"
            for m in muts
        )

    def test_git_checkout_dashdash(self):
        muts = extract_mutations("git checkout -- runtime/api/foo.py")
        assert any(
            m.verb == "git checkout" and m.target_path == "runtime/api/foo.py"
            for m in muts
        )

    def test_bare_git_status_allowed(self):
        muts = extract_mutations("git status")
        assert muts == []

    def test_bare_git_log_allowed(self):
        muts = extract_mutations("git log --oneline -5")
        assert muts == []

    def test_bare_git_diff_main_allowed(self):
        muts = extract_mutations("git diff main")
        assert muts == []

    def test_git_diff_path_and_show_are_read_only(self):
        assert extract_mutations("git diff -- runtime/api/foo.py") == []
        assert extract_mutations("git show HEAD:runtime/api/foo.py") == []

    def test_git_global_c_read_only_allowed_but_checkout_blocks(self):
        assert extract_mutations("git -C /repo show HEAD:runtime/api/foo.py") == []
        muts = extract_mutations("git -C /repo checkout -- runtime/api/foo.py")
        assert any(
            m.verb == "git checkout" and m.target_path == "runtime/api/foo.py"
            for m in muts
        )


class TestFindDelete:
    def test_find_with_delete(self):
        muts = extract_mutations("find runtime/api -name '*.pyc' -delete")
        assert any(
            m.verb == "find -delete" and m.target_path == "runtime/api"
            for m in muts
        )

    def test_find_without_delete_allowed(self):
        muts = extract_mutations("find runtime/api -name '*.py'")
        assert muts == []


class TestReadOnlyVerbs:
    def test_cat_head_tail_allow_file_visibility(self):
        for cmd in (
            "cat runtime/api/foo.py",
            "head -50 runtime/api/foo.py",
            "tail -100 runtime/api/foo.py",
        ):
            assert extract_mutations(cmd) == []

    def test_grep_pattern_with_escaped_alternation_is_not_a_path(self):
        muts = extract_mutations(
            'grep -n "claim_work\\|cmd_claim\\|current_item" '
            "runtime/harness/harness_sessions.py"
        )
        assert muts == []

    def test_rg_sed_ls_and_diff_are_read_only_visibility(self):
        for cmd in (
            "rg claim_work runtime/harness",
            "sed -n '1,80p' runtime/api/foo.py",
            "ls runtime/api/",
            "diff a/foo.py b/foo.py",
        ):
            assert extract_mutations(cmd) == []


class TestAllowCases:
    def test_python_runtime_api_invocation(self):
        muts = extract_mutations(
            "python3 -m yoke_core.domain.worktree_preflight --help"
        )
        # Not a path-relevant verb — allow.
        assert muts == []

    def test_refine_style_file_existence_check_is_visibility(self):
        muts = extract_mutations("test -f runtime/api/domain/path_claim_bash_parser.py")
        assert muts == []

    def test_tmp_path_skip(self):
        muts = extract_mutations("rm /tmp/scratch")
        # /tmp paths are dropped.
        assert all(m.target_path != "/tmp/scratch" for m in muts)

    def test_mktemp_variable_read_is_tmp_skip(self):
        muts = extract_mutations(
            '_ac_output_file=$(mktemp /tmp/advance-ac-check.XXXXXX); '
            'cat "$_ac_output_file"'
        )
        assert all(m.target_path != "$_ac_output_file" for m in muts)

    def test_mktemp_variable_redirect_is_tmp_skip(self):
        muts = extract_mutations(
            '_tmp=$(mktemp "${TMPDIR:-/tmp}/yoke-test.XXXXXX"); '
            'python3 -m pytest >"$_tmp" 2>&1; tail -80 "$_tmp"'
        )
        assert all(m.target_path != "$_tmp" for m in muts)


class TestFailClosed:
    def test_eval_is_ambiguous(self):
        muts = extract_mutations("eval 'rm -rf /tmp/foo'")
        assert any(m.verb == "ambiguous" for m in muts)

    def test_bash_dash_c_is_ambiguous(self):
        muts = extract_mutations("bash -c 'rm runtime/api/foo.py'")
        assert any(m.verb == "ambiguous" for m in muts)

    def test_heredoc_with_repo_tree_redirect_emits_real_mutation(self):
        # S3 / Class B: heredoc with parseable ``>`` redirect to a
        # repo-tree path emits a real redirect Mutation, not ambiguous.
        muts = extract_mutations("cat <<EOF > out.txt\nhi\nEOF")
        assert any(m.verb == "redirect" and m.target_path == "out.txt"
                   for m in muts)
        assert all(m.verb != "ambiguous" for m in muts)


class TestHeredocQuoteAwareness:
    """Quoted/escaped ``<<`` literals stay allowed. Real heredocs are
    handled per S3: zero-mutation heredocs fall through (allow);
    heredocs with a parseable redirect emit a real ``Mutation``."""

    def test_double_quoted_heredoc_literal_is_allowed(self):
        muts = extract_mutations(
            'git -C /repo grep -n "python3 - <<" .agents/skills/yoke/advance/'
        )
        assert all(m.verb != "ambiguous" for m in muts)

    def test_single_quoted_heredoc_literal_is_allowed(self):
        muts = extract_mutations(
            "grep -n 'python3 - <<PY' /repo/.agents/skills/foo.md"
        )
        assert all(m.verb != "ambiguous" for m in muts)

    def test_escaped_heredoc_token_is_allowed(self):
        muts = extract_mutations(r"echo not-a-heredoc \<\< marker")
        assert all(m.verb != "ambiguous" for m in muts)

    def test_python_heredoc_no_redirect_is_allowed(self):
        # S3: ``python3 - <<PY ... PY`` has no write verb and no
        # redirect. Falls through to allow.
        muts = extract_mutations("python3 - <<PY\nprint('hi')\nPY")
        assert all(m.verb != "ambiguous" for m in muts)
        assert all(m.verb != "redirect" for m in muts)

    def test_heredoc_dash_form_with_tmp_redirect_is_allowed(self):
        # S3: ``cat <<-EOF > /tmp/x`` → redirect to free path; no
        # mutation emitted because ``/tmp/`` is in the allow set.
        muts = extract_mutations("cat <<-EOF > /tmp/x\nbody\nEOF")
        assert all(m.verb != "ambiguous" for m in muts)
        assert all(m.target_path != "/tmp/x" for m in muts)

    def test_here_string_no_write_verb_is_allowed(self):
        # ``<<<`` is a here-string; no write verb / redirect means the
        # construct itself is allowed under S3.
        muts = extract_mutations("python3 -m runtime.api.foo <<< $payload")
        assert all(m.verb != "ambiguous" for m in muts)

    def test_compound_heredoc_no_mutation_is_allowed(self):
        # S3: ``grep ... && cat <<EOF ... EOF`` — first segment is
        # read-only, second is a heredoc with no write verb / redirect.
        muts = extract_mutations(
            'grep "marker - <<" file && cat <<EOF\nbody\nEOF'
        )
        assert all(m.verb != "ambiguous" for m in muts)


class TestSuppressionToken:
    def test_token_short_circuits(self):
        muts = extract_mutations(
            f"rm runtime/api/foo.py {SUPPRESSION_TOKEN}"
        )
        # Suppression sentinel is the only entry — no real mutations.
        assert len(muts) == 1
        assert muts[0].verb == "suppressed"
        assert muts[0].target_path == SUPPRESSION_TOKEN


class TestReadOnlyWorktreeInspection:
    """Read-only inspection stays visible without path-claim widening."""

    def test_worktree_read_shapes_allowed(self):
        for cmd in (
            "ls -la /Users/dev/yoke/.worktrees/YOK-1599",
            "ls .worktrees/YOK-9001",
            "cat /Users/dev/yoke/.worktrees/YOK-9001/foo.py",
            "grep -n needle .worktrees/YOK-9001/runtime/api/foo.py",
            "diff .worktrees/YOK-9001/a.py .worktrees/YOK-9002/a.py",
        ):
            assert extract_mutations(cmd) == []

    def test_rm_inside_worktree_still_denied(self):
        # Mutating verb is NOT carved out — destructive ops on .worktrees
        # still need claim coverage.
        muts = extract_mutations("rm .worktrees/YOK-9001/foo.py")
        assert any(
            m.verb == "rm" and m.target_path == ".worktrees/YOK-9001/foo.py"
            for m in muts
        )

    def test_redirect_into_worktree_still_denied(self):
        # Redirects are mutating and must remain denied.
        muts = extract_mutations(
            "echo hi > .worktrees/YOK-9001/foo.py"
        )
        assert any(
            m.verb == "redirect"
            and m.target_path == ".worktrees/YOK-9001/foo.py"
            for m in muts
        )

    def test_non_worktrees_read_paths_are_also_visible(self):
        assert extract_mutations("ls runtime/api/my.worktrees.txt") == []
        assert extract_mutations("ls worktrees/foo") == []


class TestYokeAdvancePreflightShapes:
    """Regression coverage for the screenshot-derived advance preflight
    Bash shapes that previously tripped the guard.
    """

    def test_quoted_pipe_in_db_router_query_not_a_pipeline(self):
        # Phase 2 collision-detection query: the quoted ``|`` is the
        # output separator, not a real pipeline boundary. The splitter
        # must keep it as one segment so the parser does not synthesize
        # an ``ambiguous`` mutation.
        cmd = (
            'python3 -m yoke_core.cli.db_router query -separator "|" '
            '"SELECT id, title FROM items WHERE id <> 9001"'
        )
        muts = extract_mutations(cmd)
        # python3 / db_router is not a path-relevant verb and the carve-
        # out keeps the segment whole — no ambiguous synthesis, no
        # path mutations.
        assert all(m.verb != "ambiguous" for m in muts)

    def test_ls_advance_phase2_existing_worktree_check_allowed(self):
        # Phase 2 backward-compatibility check inspects the repo
        # ``.worktrees/`` directory before deciding to create or reuse a
        # worktree. Read-only orientation must not require claim widening.
        muts = extract_mutations(
            "ls -la /Users/dev/yoke/.worktrees/"
        )
        assert muts == []

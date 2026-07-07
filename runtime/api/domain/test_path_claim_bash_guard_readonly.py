"""Regression-only tests: the downstream path-claim Bash guard must
not re-deny commands that the static-cwd carveout has already allowed
as safe read-only inspection.

The carveout fires *first* in the PreToolUse pipeline (see
``yoke_contracts.hook_runner.hook_ordering`` —
``lint_session_cwd`` runs before ``path_claim_bash_guard``). When a
worktree-scope-mismatched command is allowed by the carveout's
read-only inspection or watch_pytest wrapper shape, the path-claim
Bash mutation guard MUST also classify it as no-mutation so the
combined pipeline does not reach ``out-of-claim`` / ``wrong-cwd``
deny just because the carveout allowed.

The verbs covered (grep, rg, sed -n, cat, ls, wc, head, tail, diff)
already return ``[]`` from
:func:`yoke_core.domain.path_claim_bash_parser.extract_mutations`
because the parser intentionally treats them as orientation /
inspection. These regressions lock that behaviour in so a future
parser tweak that adds path-coverage enforcement to read-only verbs
does not silently break the carveout's contract.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.path_claim_bash_parser import extract_mutations


ITEM_ID = 9001
WT = f"/repo/.worktrees/YOK-{ITEM_ID}"
TMP_RAW = "/tmp/yoke-pytest.raw"


class TestReadOnlyVerbsHaveNoMutations:
    @pytest.mark.parametrize("cmd", [
        f"grep -n 'pat' {WT}/file.py",
        f"rg -n 'pat' {WT}",
        f"sed -n '1,80p' {WT}/file.py",
        f"cat {WT}/file.py",
        f"ls {WT}",
        f"wc -l {WT}/file.py",
        f"head -50 {WT}/file.py",
        f"tail -80 {WT}/file.py",
        f"diff {WT}/a.py {WT}/b.py",
        f"grep -n 'FAILED' {TMP_RAW}",
        f"tail -10 {TMP_RAW}",
        f"head -50 {TMP_RAW}",
        f"sed -n '1,80p' {TMP_RAW}",
        f"cat {TMP_RAW}",
        f"wc -l {TMP_RAW}",
        f'grep -n "execution_lane\\|class SessionOffer" {WT}/file.py | head -50',
    ])
    def test_read_only_verb_emits_no_mutation(self, cmd):
        assert extract_mutations(cmd) == []


class TestMutatingShapesStillFlagged:
    @pytest.mark.parametrize("cmd,expected_verb", [
        (f"rm {WT}/file.py", "rm"),
        (f"cp src {WT}/file.py", "cp"),
        (f"mv src {WT}/file.py", "mv"),
        (f"tee {WT}/log < src", "tee"),
        (f"cat src > {WT}/file.py", "redirect"),
    ])
    def test_mutating_shapes_emit_mutation(self, cmd, expected_verb):
        muts = extract_mutations(cmd)
        assert muts, f"expected at least one mutation for: {cmd}"
        assert any(m.verb == expected_verb for m in muts)


class TestReadOnlyPipeWithMutatingTailIsFlagged:
    def test_pipe_to_tee_is_flagged(self):
        muts = extract_mutations(f"cat {WT}/file.py | tee /not/tmp/log")
        assert muts
        assert any(m.verb == "tee" for m in muts)


class TestS3CompoundShapeFallThrough:
    """S3 / Class B: heredoc-bearing commands.

    Compound shells with a clean ``>`` redirect emit a real redirect
    Mutation so the guard's existing target coverage handles
    ``/tmp/`` (free), claim-covered (allowed), and repo-tree-without-claim
    (denied with target-coverage evidence rather than ambiguous).
    Heredocs with no write verb and no redirect (commit-message-only,
    ``python3 <<'PY' ... PY`` runs) fall through with zero mutations.
    """

    def test_cat_redirect_to_tmp_heredoc_is_free_path(self):
        muts = extract_mutations(
            "cat > /tmp/yoke-review.task005.md <<'EOF'\n"
            "review body\nEOF"
        )
        # /tmp is a free-path target; the parser filters it out.
        assert all(m.verb != "ambiguous" for m in muts)
        assert all(m.target_path != "/tmp/yoke-review.task005.md"
                   for m in muts)

    def test_git_commit_with_heredoc_body_is_allowed(self):
        muts = extract_mutations(
            "git -C /repo commit -m \"$(cat <<'EOF'\n"
            "commit message body\nEOF\n)\""
        )
        # No file mutations, no ambiguous denial.
        assert all(m.verb not in ("ambiguous", "redirect", "rm",
                                  "mv", "cp", "tee")
                   for m in muts)

    def test_python_heredoc_no_writes_is_allowed(self):
        muts = extract_mutations(
            "python3 <<'PY'\nprint('hi')\nPY"
        )
        assert all(m.verb != "ambiguous" for m in muts)
        assert all(m.verb != "redirect" for m in muts)

    def test_cat_redirect_to_claimed_path_emits_real_mutation(self):
        # Repo-tree redirect: the parser emits a real redirect Mutation
        # so the guard's target-coverage check decides (under coverage,
        # the worktree-relative path will pass; outside coverage it
        # denies cleanly with a target-coverage error rather than
        # ambiguous).
        muts = extract_mutations(
            f"cat > {WT}/runtime/api/domain/spec.py <<'EOF'\n"
            "content\nEOF"
        )
        assert any(
            m.verb == "redirect"
            and m.target_path == f"{WT}/runtime/api/domain/spec.py"
            for m in muts
        )
        assert all(m.verb != "ambiguous" for m in muts)

    def test_cat_redirect_to_unclaimed_repo_path_is_redirect_not_ambiguous(self):
        # Repo-tree path outside any claim is a clean target-coverage
        # denial — emitted as redirect Mutation; the consuming guard
        # surfaces target-coverage evidence rather than ambiguous.
        muts = extract_mutations(
            "cat > runtime/api/unclaimed.py <<'EOF'\n"
            "content\nEOF"
        )
        assert any(
            m.verb == "redirect"
            and m.target_path == "runtime/api/unclaimed.py"
            for m in muts
        )
        assert all(m.verb != "ambiguous" for m in muts)

    def test_eval_is_still_ambiguous(self):
        muts = extract_mutations("eval 'rm -rf /'")
        assert any(m.verb == "ambiguous" for m in muts)


class TestHeredocLiteralInSubstitution:
    """Bug 4: ``git commit -m "$(cat <<'EOF' ... EOF)"`` is a literal
    message construct and must pass the path-claim guard."""

    def test_ac11_cat_heredoc_in_commit_message_substitution(self):
        muts = extract_mutations(
            f"git -C {WT} commit -m \"$(cat <<'EOF'\n"
            "Commit body\nCo-Authored-By: ...\n"
            "EOF\n)\""
        )
        assert all(m.verb != "ambiguous" for m in muts)
        assert all(m.verb not in ("redirect", "rm", "mv") for m in muts)

    def test_ac14_negative_substitution_with_rm_body_is_ambiguous(self):
        muts = extract_mutations('git commit -m "$(rm -rf /tmp/foo)"')
        assert any(m.verb == "ambiguous" for m in muts)

    def test_ac14c_negative_sh_c_inline_is_ambiguous(self):
        muts = extract_mutations(
            f"grep -rln pattern {WT} | sh -c 'rm $1'"
        )
        assert any(m.verb == "ambiguous" for m in muts)


class TestMktempBoundRedirectTarget:
    """Bug 5: ``var=$(mktemp [args])`` followed by redirect to
    ``"$var"`` is a free-path target."""

    def test_ac12a_explicit_tmp_template_filtered(self):
        muts = extract_mutations(
            f"_msg=$(mktemp /tmp/yoke-commit-msg.XXXXXX) && "
            f"cat > \"$_msg\" <<'EOF'\nbody\nEOF\n"
            f"git -C {WT} commit -F \"$_msg\""
        )
        assert all(m.verb != "redirect" or m.target_path != '"$_msg"'
                   for m in muts)
        assert all(m.verb != "redirect" or m.target_path != "$_msg"
                   for m in muts)

    def test_ac12b_bare_mktemp_filtered(self):
        muts = extract_mutations(
            f"_task_diff_file=$(mktemp) && "
            f"git -C {WT} diff abc..HEAD > \"$_task_diff_file\""
        )
        assert all(
            not (m.verb == "redirect" and "task_diff_file" in m.target_path)
            for m in muts
        )

    def test_ac13_negative_non_mktemp_var_redirect_still_denies(self):
        muts = extract_mutations(
            '_x=/etc/hosts && echo bad > "$_x"'
        )
        # A literal $_x variable not bound to mktemp must surface as a
        # redirect with the target intact so the guard's coverage check
        # can deny.
        assert any(m.verb == "redirect" for m in muts)


class TestQuotedArgOpacity:
    """Bug 6: regex patterns inside grep quoted argument bodies must
    not be misclassified as ambiguous shell tokens."""

    def test_ac14b_grep_regex_with_alt_and_classes_passes(self):
        muts = extract_mutations(
            f"grep -rln \"def.*done_transition\\|status\\s*=\\s*"
            f"['\\\"]done['\\\"]\" {WT}/runtime/api/engines/"
            f"done_transition*.py 2>/dev/null | head -30"
        )
        assert all(m.verb != "ambiguous" for m in muts)

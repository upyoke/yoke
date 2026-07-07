"""Tests for canonical ``--stdin`` and downstream-read shapes on write adapters.

These cases live in their own module so the parent
:mod:`test_lint_shell_quoted_function_payload` stays under the
350-line authored-file cap. Coverage focuses on the two designed-in
shapes the host lint accepts for registry-covered write adapters:

* upstream ``cat <free-path-file> | python3 -m … --stdin`` (clean
  file-to-stdin source — no shell-variable capture, no transform in
  flight),
* downstream read-only wrapping such as ``2>&1 | tail -N`` or
  ``| jq -r …`` after a mutation (output handling that runs after the
  write already landed).

Negative cases assert the deny path still fires for shell-variable
capture + pipe-back, in-repo cat sources, and heredoc payloads — those
remain the kind of choreography the lint exists to refuse.
"""

from __future__ import annotations

import unittest

from yoke_core.domain import lint_shell_quoted_function_payload as lint


class TestWriteAdapterCanonicalStdinShapes(unittest.TestCase):
    """Write adapters accept the canonical ``cat <free-path-file> |``
    upstream and read-pipe / free-path-redirect downstream wrapping."""

    def test_cat_free_path_to_stdin_allowed(self) -> None:
        cmd = (
            "cat /tmp/yok1685-spec.md | python3 -m yoke_core.cli.db_router "
            "items update YOK-1685 spec --stdin"
        )
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_cat_tmp_to_stdin_with_tail_trim_allowed(self) -> None:
        cmd = (
            "cat /tmp/yok1685-spec.md | python3 -m yoke_core.cli.db_router "
            "items update YOK-1685 spec --stdin 2>&1 | tail -20"
        )
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_cat_var_folders_to_stdin_allowed(self) -> None:
        # /var/folders/... is the macOS TMPDIR root and a free-path
        # prefix the path-claim guard already trusts.
        cmd = (
            "cat /var/folders/xx/yy/T/spec.md | python3 -m yoke_core.cli."
            "db_router items update YOK-9 spec --stdin"
        )
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_write_adapter_with_tail_only_allowed(self) -> None:
        # Downstream output trimming on a write adapter (no upstream
        # pipe). This is the same shape used to inspect a write's
        # response JSON after the mutation already landed.
        cmd = (
            "python3 -m yoke_core.api.service_client claim-work --item "
            "YOK-1685 --reason 'talmud edit' 2>&1 | tail -20"
        )
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_write_adapter_with_jq_filter_allowed(self) -> None:
        # `<` redirect is not in the choreography token set, so this
        # already worked; assert the shape stays allowed alongside the
        # new ``--stdin`` upstream allowance.
        cmd = (
            "python3 -m yoke_core.cli.db_router items update YOK-7 spec "
            "--stdin < /tmp/foo.md | jq -r .result.new_hash"
        )
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_cat_in_repo_path_to_stdin_still_denied(self) -> None:
        # In-repo paths are NOT free-path; the strip allowance only
        # applies to /tmp/... etc. An in-repo cat-pipe is still
        # treated as upstream choreography because it may carry
        # project state we want function-call dispatch for.
        cmd = (
            "cat ./runtime/api/local-file | python3 -m yoke_core.cli."
            "db_router items update YOK-3 spec --stdin"
        )
        self.assertIsNotNone(lint.evaluate_command(cmd))

    def test_shell_variable_capture_pipe_back_still_denied(self) -> None:
        # The actual bad pattern: read field, capture into a shell
        # variable, transform, pipe back. Must still deny.
        cmd = (
            'OLD=$(python3 -m yoke_core.cli.db_router items get YOK-9 spec)'
            '; echo "$OLD\\nappended" | python3 -m yoke_core.cli.db_router '
            'items update YOK-9 spec --stdin'
        )
        self.assertIsNotNone(lint.evaluate_command(cmd))

    def test_heredoc_payload_still_denied(self) -> None:
        # Heredoc to --stdin keeps denying — the heredoc body can
        # interpolate shell vars, so it is not the clean file-to-stdin
        # shape this hotfix recognises.
        cmd = (
            "python3 -m yoke_core.cli.db_router items update 1234 spec "
            "--stdin <<'EOF'\nbody\nEOF"
        )
        self.assertIsNotNone(lint.evaluate_command(cmd))


if __name__ == "__main__":  # pragma: no cover - direct run convenience
    unittest.main()

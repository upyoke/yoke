"""Doc regressions for the file-backed PM/Designer input contract in shepherd."""

from __future__ import annotations

import re

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


def _prompt_block(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


class TestShepherdFileBackedInputContract:
    """PM/Designer dispatches must use a file-backed input contract, never inline embedding.

    Failure shape this gate exists to prevent: the dispatch prompt embeds a large
    inherited spec inline, the embedding layer silently truncates above some
    budget, and the read-only PM/PD authors from the truncated partial copy —
    silently dropping operator-authored content. The contract eliminates the
    failure mode by construction: the orchestrator writes the inherited content
    to a stable per-dispatch file and the dispatch prompt names that absolute
    path as the single canonical input.
    """

    @property
    def text(self) -> str:
        return _read(SKILLS / "shepherd" / "design-checks.md")

    def test_pm_orchestrator_writes_input_to_stable_file(self) -> None:
        text = self.text
        # The PM input file lives under a helper-resolved scratch root,
        # keyed on item id + session id + attempt for unique-per-dispatch
        # provenance. The path is resolved via the `yoke scratch
        # dispatch-inputs` subcommand rather than inline path-build so the
        # scratch root override (YOKE_SCRATCH_ROOT / machine config) flows
        # through one resolver.
        assert "_pm_input_path=" in text
        assert 'yoke scratch dispatch-inputs "YOK-${_num}" "${_session_id}" "${_attempt}"' in text
        assert 'printf \'%s\' "$_pre_pm_spec" >"$_pm_input_path"' in text

    def test_pm_prompt_names_input_path_and_requires_read(self) -> None:
        block = _prompt_block(
            self.text,
            " Write a structured spec for backlog epic YOK-{N}.",
            "Capture the PM's output as `_worker_output`.",
        )
        # The prompt must direct the PM to Read the named input file and not
        # rely on any inline content.
        assert "{_pre_pm_context_block if non-empty}" in block
        assert "MUST Read" in block
        assert "do not rely on any inline copy" in block
        assert "Do not attempt to run DB or" in block
        assert "python3 -m yoke_core.cli.db_router" not in block

    def test_pm_context_block_advertises_file_path_to_agent(self) -> None:
        text = self.text
        # The dispatch prompt's context block (substituted at runtime) must
        # advertise the absolute path and the MUST-Read contract, with a
        # fail-closed branch when the path is unreadable.
        assert "Your input ${_pre_pm_source} for YOK-${_num} is at ${_pm_input_path}" in text
        assert "If the path is unreadable" in text
        assert "stop from that premise" in text

    def test_pm_guard_skips_write_after_destructive_rewrite(self) -> None:
        # FR-A2b byte-loss guard remains in place — preserved alongside the
        # file-backed contract; the two are complementary.
        text = self.text
        assert "_pm_destructive_rewrite=1" in text
        assert 'if [ "${_pm_destructive_rewrite:-0}" != "1" ]; then' in text

    def test_designer_orchestrator_writes_input_to_stable_file(self) -> None:
        text = self.text
        assert "_pd_input_path=" in text
        assert 'printf \'%s\' "$_pre_designer_spec" >"$_pd_input_path"' in text

    def test_designer_prompt_names_input_path_and_requires_read(self) -> None:
        block = _prompt_block(
            self.text,
            " Create a UX/design spec for YOK-{N}.",
            "Write the Designer's output to the `items.design_spec` structured field.",
        )
        assert "{_pre_designer_context_block if non-empty}" in block
        assert "MUST Read" in block
        assert "do not rely on any inline copy" in block
        assert "Do not attempt to run DB or" in block
        assert "python3 -m yoke_core.cli.db_router" not in block

    def test_designer_context_block_advertises_file_path_to_agent(self) -> None:
        text = self.text
        assert "Your input ${_pre_designer_source} for YOK-${_num} is at ${_pd_input_path}" in text
        assert "If the path is unreadable" in text

    def test_doc_does_not_re_introduce_inline_data_fences(self) -> None:
        """Regression: re-introducing the `<pre_pm_spec ...>` or
        `<pre_designer_spec ...>` data fence (the inline-embed shape) is exactly
        the failure mode the file-backed contract eliminates. Treat any future
        reappearance as a regression.
        """
        text = self.text
        for fence_open in ("<pre_pm_spec source=", "<pre_designer_spec source="):
            assert fence_open not in text, (
                f"Regression: {fence_open!r} reintroduces the inline data-fence "
                "embed pattern that silent-truncation made unsafe. Use the "
                "file-backed input contract instead (write to a per-dispatch "
                "input file and name the path in the dispatch prompt)."
            )
        for legacy_prose in ("embedded below inside explicit data fences", "embedded it below"):
            assert legacy_prose not in text, (
                f"Regression: prose {legacy_prose!r} describes the retired "
                "inline-embed shape. The dispatch must name a file path, not "
                "claim 'embedded below'."
            )

    def test_doc_still_carries_read_only_tool_contract(self) -> None:
        """PM and PD remain `Read, Grep, Glob` only; the file-backed contract
        works inside that grant (the orchestrator owns the DB read and the file
        write, both agents Read the resulting path)."""
        text = self.text
        assert re.search(r"Read, Grep, Glob.*no Bash, no DB packet", text)


class TestPMAgentBodyTeachesFileBackedContract:
    """The PM and PD agent bodies must teach the path-Read contract so that the
    runtime instruction lives in the agent's persona, not just the dispatch
    prompt. This is defense in depth: even if a future skill caller forgets to
    repeat the contract, the agent body still trains the agent to Read the
    named input path before authoring.
    """

    def _agent_body(self, name: str) -> str:
        return _read(REPO / "runtime" / "agents" / f"{name}.md")

    def test_pm_body_names_input_file_contract(self) -> None:
        body = self._agent_body("product-manager")
        assert "Input File Contract" in body
        # Helper-resolved shape: the agent body must name the
        # ``yoke scratch dispatch-inputs`` resolver subcommand (the
        # registered ``scratch.dispatch_inputs`` function id surfaced
        # through the unified CLI) so the override flows through one
        # path.
        assert "yoke scratch dispatch-inputs" in body
        assert "machine-config `temp_root`" in body
        assert "MUST Read" in body
        lowered = body.lower()
        assert "do not rely on any inline copy" in lowered or "never trust an inline copy" in lowered
        assert "stop from that premise" in body

    def test_pd_body_names_input_file_contract(self) -> None:
        body = self._agent_body("product-designer")
        assert "Input File Contract" in body
        # Helper-resolved shape (see PM test above for the rationale).
        assert "yoke scratch dispatch-inputs" in body
        assert "machine-config `temp_root`" in body
        assert "MUST Read" in body
        lowered = body.lower()
        assert "do not rely on any inline copy" in lowered or "never trust an inline copy" in lowered
        assert "stop from that premise" in body


class TestLargeSpecPreservationByConstruction:
    """AC-6 (file-backed contract preserves all `##` headings of a large
    inherited spec): the original failure mode was silent inline truncation in
    the dispatch-prompt embedding pipeline. The fix is structural — the
    inherited content is written to a file and the dispatch prompt names the
    path, so there is no inline content to truncate. A doc-regression check
    proves the construction: the file-write step uses the full ``_pre_pm_spec``
    variable, and the prompt-template substitution surface (``{_pre_pm_context_block ...}``)
    no longer carries the inherited content inline.
    """

    @property
    def text(self) -> str:
        return _read(SKILLS / "shepherd" / "design-checks.md")

    def test_pm_file_write_uses_full_pre_pm_spec(self) -> None:
        # The write step pipes the variable directly; no head/cut/truncation.
        text = self.text
        assert 'printf \'%s\' "$_pre_pm_spec" >"$_pm_input_path"' in text
        for truncator in (' | head ', ' | head\n', ' | head -', ' | cut ', ' | sed '):
            assert truncator not in text or "_pre_pm_spec" not in text.split(truncator, 1)[0][-200:]

    def test_pd_file_write_uses_full_pre_designer_spec(self) -> None:
        text = self.text
        assert 'printf \'%s\' "$_pre_designer_spec" >"$_pd_input_path"' in text

    def test_pm_prompt_does_not_inline_spec_variable(self) -> None:
        """The PM prompt template must not interpolate ``$_pre_pm_spec`` or
        ``${_pre_pm_spec}`` directly; the file-backed path is the only surface
        that carries the inherited content into the dispatch."""
        block = _prompt_block(
            self.text,
            " Write a structured spec for backlog epic YOK-{N}.",
            "Capture the PM's output as `_worker_output`.",
        )
        assert "$_pre_pm_spec" not in block
        assert "${_pre_pm_spec}" not in block

    def test_pd_prompt_does_not_inline_spec_variable(self) -> None:
        block = _prompt_block(
            self.text,
            " Create a UX/design spec for YOK-{N}.",
            "Write the Designer's output to the `items.design_spec` structured field.",
        )
        assert "$_pre_designer_spec" not in block
        assert "${_pre_designer_spec}" not in block

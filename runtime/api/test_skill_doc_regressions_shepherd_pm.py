"""Doc regressions for the file-backed PM/Designer input contract in shepherd."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


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
        assert (
            'yoke scratch dispatch-inputs "$_item_ref" "$_session_id" "$_attempt"'
            in text
        )
        assert "PREFIX-${_num}" not in text
        assert 'printf \'%s\' "$_pre_pm_spec" >"$_pm_input_path"' in text

    def test_pm_dispatch_names_the_input_file(self) -> None:
        assert "dispatches product-manager with that file" in self.text

    def test_pm_guard_skips_write_after_destructive_rewrite(self) -> None:
        # The byte-loss guard complements the file-backed contract.
        text = self.text
        assert "_pm_destructive_rewrite=1" in text
        assert "NOT_READY, no write" in text

    def test_designer_orchestrator_writes_input_to_stable_file(self) -> None:
        assert (
            "printf '%s' \"$_pre_designer_spec\" "
            '>"${_pm_input_dir}/product-designer-spec.md"'
        ) in self.text

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
        for legacy_prose in (
            "embedded below inside explicit data fences",
            "embedded it below",
        ):
            assert legacy_prose not in text, (
                f"Regression: prose {legacy_prose!r} describes the retired "
                "inline-embed shape. The dispatch must name a file path, not "
                "claim 'embedded below'."
            )


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
        assert "Tools: `Read, Grep, Glob`; no Bash" in body
        # Parent-dispatch tests above cover scratch resolution. The role's
        # action is the first Read of its absolute inherited-content path.
        assert "absolute input-spec path as your first action" in " ".join(body.split())
        assert "Missing/empty/unreadable/bad-encoding input" in body
        assert "MUST Read" in body
        lowered = body.lower()
        assert (
            "do not rely on any inline copy" in lowered
            or "never trust an inline copy" in lowered
        )
        assert "stop from that premise" in " ".join(body.split())

    def test_pd_body_names_input_file_contract(self) -> None:
        body = self._agent_body("product-designer")
        assert "Input File Contract" in body
        assert "Tools: `Read, Grep, Glob`; no Bash" in body
        assert "absolute input-spec path as your first action" in " ".join(body.split())
        assert "Missing/empty/unreadable/bad-encoding input" in body
        assert "MUST Read" in body
        lowered = body.lower()
        assert (
            "do not rely on any inline copy" in lowered
            or "never trust an inline copy" in lowered
        )
        assert "stop from that premise" in " ".join(body.split())


class TestLargeSpecPreservationByConstruction:
    """Structural fix (file-backed contract preserves all `##` headings of a large
    inherited spec): the original failure mode was silent inline truncation in
    the dispatch-prompt embedding pipeline. The fix is structural — the
    inherited content is written to a file and the dispatch prompt names the
    path, so there is no inline content to truncate. A doc-regression check
    proves the construction: the file-write step uses the full ``_pre_pm_spec``
    variable, and no other line carries the inherited content inline.
    """

    @property
    def text(self) -> str:
        return _read(SKILLS / "shepherd" / "design-checks.md")

    def test_pm_file_write_uses_full_pre_pm_spec(self) -> None:
        # The write step pipes the variable directly; no head/cut/truncation.
        text = self.text
        assert 'printf \'%s\' "$_pre_pm_spec" >"$_pm_input_path"' in text
        for truncator in (" | head ", " | head\n", " | head -", " | cut ", " | sed "):
            assert (
                truncator not in text
                or "_pre_pm_spec" not in text.split(truncator, 1)[0][-200:]
            )

    def test_pd_file_write_uses_full_pre_designer_spec(self) -> None:
        assert "printf '%s' \"$_pre_designer_spec\" >" in self.text

    def test_inherited_spec_reaches_agents_only_through_the_file_write(self) -> None:
        """The inherited spec variables appear only in their file-write lines,
        so no dispatch prompt can carry the content inline."""
        for variable in ("_pre_pm_spec", "_pre_designer_spec"):
            lines = [line for line in self.text.splitlines() if variable in line]
            assert len(lines) == 1, (variable, lines)
            assert lines[0].startswith("printf '%s' "), lines[0]

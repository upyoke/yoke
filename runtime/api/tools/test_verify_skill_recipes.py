"""Tests for the verify_skill_recipes smoke harness."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from yoke_core.tools import verify_skill_recipes as vsr


class TestExtractRecipes:
    def test_no_fenced_block_returns_empty(self) -> None:
        recipes = vsr.extract_recipes("plain prose with no code")
        assert recipes == []

    def test_single_bash_block_with_yoke_line(self) -> None:
        text = textwrap.dedent(
            """\
            Some prose.

            ```bash
            yoke items get 1
            ```
            """
        )
        recipes = vsr.extract_recipes(text)
        assert len(recipes) == 1
        line_no, recipe, expect, is_template = recipes[0]
        assert recipe == "yoke items get 1"
        assert expect is None
        assert is_template is False

    def test_ignores_non_yoke_lines(self) -> None:
        text = textwrap.dedent(
            """\
            ```bash
            # comment line
            git status
            python3 -m yoke_core.cli.db_router items get YOK-1
            yoke items get 1
            ```
            """
        )
        recipes = vsr.extract_recipes(text)
        assert len(recipes) == 1
        assert recipes[0][1] == "yoke items get 1"

    def test_expect_error_annotation_captured(self) -> None:
        text = textwrap.dedent(
            """\
            ```bash
            yoke items get 99999 # expect_error: not_found
            ```
            """
        )
        recipes = vsr.extract_recipes(text)
        assert len(recipes) == 1
        line_no, recipe, expect, is_template = recipes[0]
        assert recipe == "yoke items get 99999"
        assert expect == "not_found"

    def test_placeholder_recipe_flagged_as_template(self) -> None:
        text = "```bash\nyoke items get YOK-{N} spec\n```\n"
        recipes = vsr.extract_recipes(text)
        assert len(recipes) == 1
        _line, _recipe, _expect, is_template = recipes[0]
        assert is_template is True

    def test_line_continuation_joined(self) -> None:
        text = textwrap.dedent(
            """\
            ```bash
            yoke claims work acquire \\
                --item YOK-1 --reason kickoff
            ```
            """
        )
        recipes = vsr.extract_recipes(text)
        assert len(recipes) == 1
        _line, recipe, _expect, _is_template = recipes[0]
        assert "--item YOK-1" in recipe
        assert "--reason kickoff" in recipe
        assert "\\" not in recipe

    def test_multiple_fenced_blocks(self) -> None:
        text = textwrap.dedent(
            """\
            ```bash
            yoke items get 1
            ```

            More prose.

            ```sh
            yoke items get 2
            ```
            """
        )
        recipes = vsr.extract_recipes(text)
        assert [r[1] for r in recipes] == [
            "yoke items get 1", "yoke items get 2",
        ]


class TestSmokeDispatch:
    def test_valid_recipe_passes(self) -> None:
        ok, function_id, error = vsr.smoke_dispatch("yoke items get 1")
        assert ok is True
        assert function_id == "items.get.run"
        assert error is None

    def test_unknown_subcommand_fails(self) -> None:
        ok, function_id, error = vsr.smoke_dispatch("yoke nope nope")
        assert ok is False
        assert function_id is None
        assert "unknown yoke subcommand" in (error or "")

    def test_tool_shaped_recipe_passes_without_dispatch_capture(self) -> None:
        ok, function_id, error = vsr.smoke_dispatch(
            "yoke board art variant create --ascii"
        )
        assert ok is True
        assert function_id is None
        assert error is None

    def test_global_env_recipe_resolves_before_dispatch(self) -> None:
        ok, function_id, error = vsr.smoke_dispatch("yoke --env stage items get 1")
        assert ok is True
        assert function_id == "items.get.run"
        assert error is None

    def test_strategy_ops_adapter_uses_stubbed_dispatch(
        self, tmp_path: Path,
    ) -> None:
        plan_path = tmp_path / "MASTER-PLAN.md"
        plan_path.write_text("# MASTER PLAN\n", encoding="utf-8")
        ok, function_id, error = vsr.smoke_dispatch(
            f"yoke strategy master-plan-check --plan-path {plan_path}"
        )
        assert ok is True
        assert function_id == "strategy.master_plan_check.run"
        assert error is None

    def test_top_level_version_passes_without_dispatch_capture(self) -> None:
        ok, function_id, error = vsr.smoke_dispatch("yoke --version")
        assert ok is True
        assert function_id is None
        assert error is None

    def test_bad_argv_fails(self) -> None:
        ok, function_id, error = vsr.smoke_dispatch("yoke items get")
        assert ok is False
        # Missing item id -> argparse error -> SystemExit / cli_main rc=2.
        assert error is not None

    def test_non_yoke_prefix_rejected(self) -> None:
        ok, function_id, error = vsr.smoke_dispatch(
            "python3 -m yoke_core.cli.db_router items get YOK-1"
        )
        assert ok is False
        assert function_id is None

    def test_expected_error_passes(self) -> None:
        ok, function_id, error = vsr.smoke_dispatch(
            "yoke items get 1",
            expected_error="not_found",
        )
        assert ok is True
        assert function_id == "items.get.run"
        assert error is None


class TestVerifySkillRoot:
    def test_empty_directory_returns_no_verdicts(self, tmp_path: Path) -> None:
        skill_root = tmp_path / "skills"
        skill_root.mkdir()
        verdicts = vsr.verify_skill_root(skill_root)
        assert verdicts == []

    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            vsr.verify_skill_root(tmp_path / "does-not-exist")

    def test_collects_recipes_from_md_files(self, tmp_path: Path) -> None:
        skill_root = tmp_path / "skills"
        skill_root.mkdir()
        md = skill_root / "demo.md"
        md.write_text(
            textwrap.dedent(
                """\
                # Demo

                ```bash
                yoke items get 1
                ```
                """
            ),
            encoding="utf-8",
        )
        verdicts = vsr.verify_skill_root(skill_root)
        assert len(verdicts) == 1
        v = verdicts[0]
        assert v.ok is True
        assert v.function_id == "items.get.run"
        assert v.recipe == "yoke items get 1"

    def test_expect_error_accepts_matching_dispatch_error(self, tmp_path: Path) -> None:
        skill_root = tmp_path / "skills"
        skill_root.mkdir()
        md = skill_root / "demo.md"
        md.write_text(
            "```bash\nyoke items get 1 # expect_error: not_found\n```\n",
            encoding="utf-8",
        )
        verdicts = vsr.verify_skill_root(skill_root)
        assert len(verdicts) == 1
        assert verdicts[0].ok is True
        assert verdicts[0].expect_error == "not_found"


def test_quick_per_directory_samples_before_dispatch(tmp_path: Path) -> None:
    skill_root = tmp_path.joinpath("skills")
    skill_root.mkdir()
    recipes = "\n".join(f"yoke items get {i}" for i in range(1, 6))
    skill_root.joinpath("many.md").write_text(
        f"```bash\n{recipes}\n```\n", encoding="utf-8",
    )
    verdicts = vsr.verify_skill_root(skill_root, quick_per_directory=3)
    assert len(verdicts) == 3
    assert [v.recipe for v in verdicts] == [
        "yoke items get 1",
        "yoke items get 2",
        "yoke items get 3",
    ]


def test_parse_only_checks_templated_recipes_without_template_skip(
    tmp_path: Path,
) -> None:
    skill_root = tmp_path.joinpath("skills")
    skill_root.mkdir()
    skill_root.joinpath("templated.md").write_text(
        "```bash\nyoke items get YOK-{N}\n```\n", encoding="utf-8",
    )

    verdicts = vsr.verify_skill_root(skill_root, parse_only=True)

    assert len(verdicts) == 1
    assert verdicts[0].ok is True
    assert verdicts[0].parse_only is True
    assert verdicts[0].template_skipped is False


def test_parse_only_reports_shell_parse_errors(tmp_path: Path) -> None:
    skill_root = tmp_path.joinpath("skills")
    skill_root.mkdir()
    skill_root.joinpath("bad.md").write_text(
        "```bash\nyoke items get \"unterminated\n```\n", encoding="utf-8",
    )

    verdicts = vsr.verify_skill_root(skill_root, parse_only=True)

    assert len(verdicts) == 1
    assert verdicts[0].ok is False
    assert "shlex parse error" in (verdicts[0].error or "")


class TestMainCli:
    def test_main_exits_zero_when_no_recipes(self, tmp_path: Path) -> None:
        skill_root = tmp_path / "skills"
        skill_root.mkdir()
        out_path = tmp_path / "summary.txt"
        rc = vsr.main([
            "--skill-root", str(skill_root),
            "--output", str(out_path),
        ])
        assert rc == 0
        text = out_path.read_text(encoding="utf-8")
        assert "0 recipes inspected" in text

    def test_main_exits_one_on_failure(self, tmp_path: Path) -> None:
        skill_root = tmp_path / "skills"
        skill_root.mkdir()
        (skill_root / "demo.md").write_text(
            "```bash\nyoke nope nope\n```\n", encoding="utf-8",
        )
        rc = vsr.main(["--skill-root", str(skill_root)])
        assert rc == 1

    def test_main_exits_two_on_missing_root(self, tmp_path: Path) -> None:
        rc = vsr.main(["--skill-root", str(tmp_path / "nope")])
        assert rc == 2

    def test_json_output_is_parsable(self, tmp_path: Path) -> None:
        skill_root = tmp_path / "skills"
        skill_root.mkdir()
        (skill_root / "demo.md").write_text(
            "```bash\nyoke items get 1\n```\n", encoding="utf-8",
        )
        out_path = tmp_path / "verdicts.json"
        rc = vsr.main([
            "--skill-root", str(skill_root),
            "--output", str(out_path), "--json",
        ])
        assert rc == 0
        import json
        body = json.loads(out_path.read_text(encoding="utf-8"))
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["ok"] is True

    def test_parse_only_cli_does_not_dispatch_unknown_subcommand(
        self, tmp_path: Path
    ) -> None:
        skill_root = tmp_path / "skills"
        skill_root.mkdir()
        (skill_root / "demo.md").write_text(
            "```bash\nyoke nope nope\n```\n", encoding="utf-8",
        )
        rc = vsr.main(["--skill-root", str(skill_root), "--parse-only"])
        assert rc == 0


class TestNoResidualQaRequirementsAutoRecipes:
    """AC-5: zero ``python3 -c "from yoke_core.domain.qa_requirements_auto"``
    recipes survive in live ``.agents/`` content after the function-call +
    CLI adapter wrap.
    """

    def _live_skills_root(self) -> Path:
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / ".agents" / "skills" / "yoke"
            if candidate.is_dir():
                return candidate
        pytest.skip(".agents/skills/yoke not found from this checkout")

    def test_no_qa_requirements_auto_import_recipes(self) -> None:
        root = self._live_skills_root()
        offenders: list[tuple[str, int, str]] = []
        for md in root.rglob("*.md"):
            for line_no, line in enumerate(
                md.read_text(encoding="utf-8").splitlines(), start=1,
            ):
                if "qa_requirements_auto" in line:
                    offenders.append((str(md), line_no, line.strip()))
        assert offenders == [], (
            "residual qa_requirements_auto recipe shape found in .agents/:\n"
            + "\n".join(f"{p}:{n}: {ln}" for p, n, ln in offenders)
        )

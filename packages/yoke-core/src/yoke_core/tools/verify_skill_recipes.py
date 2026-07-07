"""Smoke harness for ``yoke <subcommand>`` recipes in skill bodies.

Walks ``.agents/skills/yoke/**/*.md``, extracts fenced shell lines that
start with ``yoke ``, and smoke-dispatches each recipe through the CLI
with a stub dispatcher. Parse + registry-resolution errors still surface
because they happen before the stubbed dispatch.

CLI:

    python3 -m yoke_core.tools.verify_skill_recipes \\
        [--skill-root PATH] [--output PATH] [--json] [--parse-only]

Exits 0 when every recipe passes; 1 when any recipe fails; 2 on a
configuration error (skill-root missing, unreadable, etc.).

Recipe annotation: ``yoke ... # expect_error: <code>``.
When present, a dispatcher-stubbed error matching ``<code>`` is success.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shlex
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.tools.verify_skill_recipes_resolution import dispatch_needed
from yoke_core.tools.verify_skill_recipes_smoke import smoke_cli_patches


_FENCED_BASH_RE = re.compile(
    r"^```(?:bash|sh|shell)?\s*\n(.*?)^```",
    re.MULTILINE | re.DOTALL,
)
_EXPECT_ERROR_RE = re.compile(r"#\s*expect_error:\s*(\S+)")
_YOKE_LINE_RE = re.compile(r"^\s*yoke\s+\S+")
# Skill bodies use template syntax that the smoke harness cannot
# dispatch literally — placeholders (``{N}`` / ``{id-number}`` and the
# ``[CHECKOUT]`` / ``[SUBPATH]`` square-bracket optional/placeholder
# notation), shell variable interpolation (``$VAR`` / ``$_VAR`` /
# ``${VAR}``), the literal ``YOK-N`` doc convention (where ``N`` is just
# an example letter), and shell composition (redirection, ``||``, ``&&``,
# pipes). Any of these flags the recipe as ``is_template`` and the harness
# records it as a successful skip rather than dispatching with garbage.
_TEMPLATE_INDICATORS_RE = re.compile(
    r"\{[^}]+\}"            # brace placeholder
    r"|\[[^\]]+\]"          # [PLACEHOLDER] / [optional-arg] notation
    r"|\$[A-Za-z_][\w]*"     # $VAR
    r"|\$\{[^}]+\}"          # ${VAR}
    r"|\bYOK-N\b"            # doc convention
    r"|2>&1"                 # stderr redirection
    r"|>/?\S+"               # output redirection (>file, >/dev/null, etc.)
    r"|\|\|"                 # shell or-list
    r"|&&"                   # shell and-list
)


@dataclass
class RecipeVerdict:
    file: str
    line_number: int
    recipe: str
    ok: bool
    function_id: Optional[str]
    expect_error: Optional[str]
    error: Optional[str] = None
    template_skipped: bool = False
    parse_only: bool = False


def _resolve_skill_root(arg_value: Optional[str]) -> Path:
    if arg_value:
        return Path(arg_value).resolve()
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__)) / ".agents" / "skills" / "yoke"


def _walk_skill_files(skill_root: Path) -> Iterable[Path]:
    if not skill_root.is_dir():
        raise FileNotFoundError(f"skill-root not found: {skill_root}")
    for path in sorted(skill_root.glob("**/*.md")):
        if path.is_file():
            yield path


def _join_continuations(block: str) -> List[Tuple[int, str]]:
    """Return ``(line_number, joined_line)`` per logical line in *block*.

    Lines ending in ``\\`` are spliced with the next line (the standard
    shell continuation shape). The line number is the source line where
    the logical line started.
    """
    out: List[Tuple[int, str]] = []
    raw_lines = block.split("\n")
    i = 0
    while i < len(raw_lines):
        line_no_offset = i + 1  # 1-based offset within the block
        current = raw_lines[i]
        while current.rstrip().endswith("\\") and (i + 1) < len(raw_lines):
            # Strip the trailing backslash; join with the next line.
            current = current.rstrip()[:-1].rstrip() + " " + raw_lines[i + 1]
            i += 1
        out.append((line_no_offset, current))
        i += 1
    return out


def extract_recipes(
    text: str,
) -> List[Tuple[int, str, Optional[str], bool]]:
    """Return ``(line_number, recipe_line, expect_error_code, is_template)``.

    Walks every fenced ``bash``/``sh``/``shell`` block, joins
    line-continuation backslashes, then extracts every line starting
    with ``yoke ``. A recipe containing ``{placeholder}`` syntax is
    classified ``is_template=True`` — the smoke harness skips dispatch
    for those because the placeholder is substituted at skill
    invocation time, not at recipe authorship time.
    """
    recipes: List[Tuple[int, str, Optional[str], bool]] = []
    for match in _FENCED_BASH_RE.finditer(text):
        block = match.group(1)
        block_start_offset = match.start(1)
        prefix = text[:block_start_offset]
        block_first_line = prefix.count("\n") + 1
        for relative_line, joined in _join_continuations(block):
            stripped = joined.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not _YOKE_LINE_RE.match(stripped):
                continue
            expect_match = _EXPECT_ERROR_RE.search(stripped)
            expect_code = expect_match.group(1) if expect_match else None
            command_only = stripped.split("#", 1)[0].rstrip()
            is_template = bool(_TEMPLATE_INDICATORS_RE.search(command_only))
            recipes.append(
                (
                    block_first_line + relative_line - 1,
                    command_only,
                    expect_code,
                    is_template,
                )
            )
    return recipes


def _stub_dispatch_factory(
    captured: List[FunctionCallRequest],
    expected_error: Optional[str] = None,
):
    def _stub(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        if expected_error is not None:
            return FunctionCallResponse(
                success=False,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                error=FunctionError(
                    code=expected_error,
                    message=f"stubbed expected error: {expected_error}",
                ),
            )
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            # item_id satisfies resolve_item_id_via_dispatch for recipes
            # that round-trip a ref resolution through the dispatcher.
            result={"smoke": True, "item_id": 1791},
        )
    return _stub


def smoke_dispatch(
    recipe: str,
    expected_error: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Run one recipe through the yoke CLI with a stubbed dispatcher.

    Returns ``(ok, function_id, error_detail)``. Stdout/stderr are
    suppressed; argparse SystemExit (rc!=0) is captured as a failure.
    """
    try:
        argv = shlex.split(recipe)
    except ValueError as exc:
        return False, None, f"shlex parse error: {exc}"
    needs_dispatch, error = dispatch_needed(argv)
    if error:
        return False, None, error
    if not needs_dispatch:
        return True, None, None
    captured: List[FunctionCallRequest] = []
    stub = _stub_dispatch_factory(captured, expected_error=expected_error)
    try:
        with smoke_cli_patches(stub):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                rc = cli_main(argv[1:])
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        return False, None, f"SystemExit({code})"
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"
    if expected_error is not None:
        if rc == 1 and captured:
            return True, captured[-1].function, None
        return (
            False, captured[-1].function if captured else None,
            f"expected error not raised: {expected_error}",
        )
    if rc != 0:
        return False, None, f"cli_main exit={rc}"
    if not captured:
        return False, None, "no dispatch captured"
    return True, captured[-1].function, None


def parse_recipe(recipe: str) -> Tuple[bool, Optional[str]]:
    try:
        shlex.split(recipe)
    except ValueError as exc:
        return False, f"shlex parse error: {exc}"
    return True, None


def count_recipes(skill_root: Path) -> int:
    """Return the number of extracted ``yoke`` recipes without dispatching."""
    total = 0
    for md_file in _walk_skill_files(skill_root):
        total += len(extract_recipes(md_file.read_text(encoding="utf-8")))
    return total


def verify_skill_root(
    skill_root: Path,
    *,
    quick_per_directory: Optional[int] = None,
    parse_only: bool = False,
) -> List[RecipeVerdict]:
    verdicts: List[RecipeVerdict] = []
    by_dir: dict[str, int] = {}
    for md_file in _walk_skill_files(skill_root):
        text = md_file.read_text(encoding="utf-8")
        for line_number, recipe, expect_code, is_template in extract_recipes(text):
            if quick_per_directory is not None:
                directory = str(md_file.parent)
                count = by_dir.get(directory, 0)
                if count >= quick_per_directory:
                    continue
                by_dir[directory] = count + 1
            if parse_only:
                ok, error = parse_recipe(recipe)
                verdicts.append(RecipeVerdict(
                    file=str(md_file), line_number=line_number, recipe=recipe,
                    ok=ok, function_id=None, expect_error=expect_code,
                    error=error, template_skipped=False, parse_only=True,
                ))
                continue
            if is_template:
                verdicts.append(RecipeVerdict(
                    file=str(md_file), line_number=line_number, recipe=recipe,
                    ok=True, function_id=None, expect_error=expect_code,
                    error=None, template_skipped=True,
                ))
                continue
            ok, function_id, error = smoke_dispatch(
                recipe, expected_error=expect_code,
            )
            verdicts.append(RecipeVerdict(
                file=str(md_file),
                line_number=line_number,
                recipe=recipe,
                ok=ok,
                function_id=function_id,
                expect_error=expect_code,
                error=error,
            ))
    return verdicts


def _format_summary(verdicts: List[RecipeVerdict]) -> str:
    total = len(verdicts)
    failures = [v for v in verdicts if not v.ok]
    templates = [v for v in verdicts if v.template_skipped]
    parse_only = [v for v in verdicts if v.parse_only]
    lines = [
        f"verify_skill_recipes: {total} recipes inspected "
        f"({len(templates)} template-skipped"
        f"{', ' + str(len(parse_only)) + ' parse-only' if parse_only else ''}), "
        f"{len(failures)} failures.",
    ]
    if failures:
        lines.append("\nFailures:")
        for v in failures:
            lines.append(
                f"  {v.file}:{v.line_number} - {v.recipe}"
            )
            if v.error:
                lines.append(f"    error: {v.error}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_skill_recipes",
        description="Smoke-dispatch every yoke <subcommand> recipe in skill bodies.",
    )
    parser.add_argument("--skill-root", default=None, help="Override skill body root.")
    parser.add_argument("--output", default="-", help="Write summary to PATH.")
    parser.add_argument("--json", action="store_true", help="Emit JSON verdicts.")
    parser.add_argument("--parse-only", action="store_true",
                        help="Shell-parse recipes without dispatching.")
    parsed = parser.parse_args(argv)
    skill_root = _resolve_skill_root(parsed.skill_root)
    try:
        verdicts = verify_skill_root(skill_root, parse_only=parsed.parse_only)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if parsed.json:
        body = json.dumps(
            [v.__dict__ for v in verdicts], indent=2, sort_keys=True,
        ) + "\n"
    else:
        body = _format_summary(verdicts)
    if parsed.output == "-":
        sys.stdout.write(body)
    else:
        Path(parsed.output).write_text(body, encoding="utf-8")
    return 1 if any(not v.ok for v in verdicts) else 0


if __name__ == "__main__":
    sys.exit(main())

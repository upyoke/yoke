"""Every registered human read selects one section and outlines on overflow."""

import argparse
import json

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.transport.output_limit import REPLY_LIMIT_BYTES, read_output_scope
from yoke_cli.transport.public_ref_display import emit_response
from yoke_cli.transport.read_sections import (
    OUTLINE_BUDGET_BYTES,
    section_outline,
    select_section,
)
from yoke_contracts.api.function_call import FunctionCallResponse

ROUTE = ("yoke", "strategy", "doc", "get")

DOC = """# Plan

Intro.

## Live status

Now.

```text
## Not a heading
```

### In flight

Nested.

## Next up

Tail.
"""


def _response(text):
    return FunctionCallResponse(
        success=True, function="strategy.doc.get", version="v1", result={"content": text}
    )


def _emit(args, text, *, parser=None, json_mode=False):
    parser = parser or argparse.ArgumentParser(prog="read")
    parser.add_argument("slug")
    parser.add_argument("--project")
    with read_output_scope(args, "strategy.doc.get", ROUTE):
        parse_or_usage_error(parser, args, "read")
        return emit_response(
            _response(text),
            json_mode=json_mode,
            human_writer=lambda response, stdout, stderr: stdout.write(
                response.result["content"]
            ),
        )


def test_section_runs_to_the_next_same_level_heading_outside_fences():
    selected = select_section(DOC, "## live STATUS")
    assert selected.startswith("## Live status\n")
    assert "## Not a heading" in selected
    assert "### In flight" in selected
    assert "Next up" not in selected


def test_section_flag_prints_only_that_section(capsys):
    assert _emit(["PLAN", "--section", "In flight"], DOC) == 0
    assert capsys.readouterr().out == "### In flight\n\nNested.\n"


def test_missing_section_refuses_with_working_commands(capsys):
    assert _emit(["PLAN", "--project", "p", "--section", "Nope"], DOC) == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "read_section_missing" in out.err
    assert "yoke strategy doc get PLAN --project p --section 'Next up'" in out.err
    assert "--section Nope" not in out.err


def test_json_with_section_refuses_instead_of_ignoring_it(capsys):
    assert _emit(["PLAN", "--section", "Next up"], DOC, json_mode=True) == 1
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["error"]["code"] == "read_section_requires_human_output"


def test_json_without_section_is_never_refused(capsys):
    big = "## Big\n" + "x" * (REPLY_LIMIT_BYTES + 1)
    assert _emit(["PLAN"], big, json_mode=True) == 0
    assert json.loads(capsys.readouterr().out)["result"]["content"] == big


def test_overflow_lists_each_heading_with_its_exact_command(capsys):
    big = DOC + "\n## Archive\n\n" + "x" * REPLY_LIMIT_BYTES + "\n"
    assert _emit(["PLAN", "--project", "p"], big) == 1
    err = capsys.readouterr().err
    assert "read_output_limit_exceeded" in err
    assert "Read one section:" in err
    assert "- Plan (" in err
    assert "  - Archive (" in err
    assert "yoke strategy doc get PLAN --project p --section Archive" in err
    assert "Not a heading" not in err


def test_oversized_section_outlines_its_own_subsections(capsys):
    big = "## Archive\n\n### Old\n\n" + "x" * REPLY_LIMIT_BYTES + "\n\n## Next\n"
    assert _emit(["PLAN", "--section", "Archive", "--full"], big) == 0
    capsys.readouterr()
    assert _emit(["PLAN", "--section", "Archive"], big) == 1
    err = capsys.readouterr().err
    assert "--section Old" in err
    assert "--section Next" not in err


def test_outline_keeps_two_levels_and_both_ends_within_budget():
    entries = "".join(f"## Entry {n}\n\n### Detail {n}\n\nbody\n" for n in range(2000))
    outline = section_outline("# Log\n\n" + entries, lambda h: f"read --section {h!r}")
    assert len(outline.encode("utf-8")) <= OUTLINE_BUDGET_BYTES + 200
    assert "- Log (" in outline
    assert "Entry 0 (" in outline
    assert "Entry 1999 (" in outline
    assert "more headings not shown" in outline
    assert "Detail" not in outline
    assert outline.endswith("Read a listed section to see the headings under it.")


def test_text_without_headings_keeps_the_narrowing_hint(capsys):
    assert _emit(["PLAN"], "x" * (REPLY_LIMIT_BYTES + 1)) == 1
    err = capsys.readouterr().err
    assert "Read one section" not in err


def test_a_read_with_its_own_section_flag_keeps_it(capsys):
    parser = argparse.ArgumentParser(prog="read")
    parser.add_argument("--section", help="Own section.")
    big = "## A\n" + "x" * (REPLY_LIMIT_BYTES + 1)
    assert _emit(["PLAN", "--section", "A"], big, parser=parser) == 1
    err = capsys.readouterr().err
    assert "read_output_limit_exceeded" in err
    assert "Read one section" not in err
    assert [a.dest for a in parser._actions].count("section") == 1

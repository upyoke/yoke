"""Polish skill framing — bash-first claim/lifecycle/db-claim recipes.

For each documented operation in the three touched polish files
(`parse-and-claim.md`, `advance.md`, `fixes.md`), the canonical CLI
recipe (`yoke <subcommand>`) MUST appear before any function-call
JSON envelope for the same operation. The CLI recipe is the surface
the operator-facing operator actually runs; the JSON envelope is for
dispatch-surface callers and is allowed to remain as a tail
"Function-call equivalent" block but never as the lead.

The retained function-call envelopes must also use the canonical
`lifecycle.transition.execute` function id and the `source_status` /
`target_status` payload keys (not `from` / `to`); the regex pair below
enforces both at once.

The leading CLI examples must not teach `--session-id`; the active
harness session is resolved from the environment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read

POLISH_DIR = SKILLS / "polish"

# (filename, operation_label, cli_marker_regex, json_marker_regex)
#
# cli_marker_regex matches the canonical CLI invocation. json_marker_regex
# matches the function-call envelope for the same operation. The test
# asserts the CLI marker appears before the JSON marker (or the JSON is
# absent).
OPERATION_PAIRS: tuple[tuple[str, str, str, str], ...] = (
    (
        "parse-and-claim.md",
        "claim acquire",
        r"yoke claims work acquire",
        r'"function":\s*"claims\.work\.acquire"',
    ),
    (
        "parse-and-claim.md",
        "lifecycle enters the bound working stage",
        r'yoke lifecycle transition[^\n]+--from "\$LIVE_STAGE" --to "\$NEXT_STAGE"',
        r'"function":\s*"lifecycle\.transition\.execute"',
    ),
    (
        "advance.md",
        "lifecycle completes the bound segment",
        r'yoke lifecycle transition[^\n]+--from "\$LIVE_STAGE" --to "\$NEXT_STAGE"',
        r'"function":\s*"lifecycle\.transition\.execute"',
    ),
    (
        "advance.md",
        "claim release",
        r"yoke claims work release",
        r'"function":\s*"claims\.work\.release"',
    ),
    (
        "fixes.md",
        "db-claim amend",
        r"yoke db-claim amend",
        r'"function":\s*"db_claim\.amend"',
    ),
)


@pytest.fixture(scope="module")
def polish_texts() -> dict[str, str]:
    return {
        name: _read(POLISH_DIR / name)
        for name in {"parse-and-claim.md", "advance.md", "fixes.md"}
    }


@pytest.mark.parametrize(
    "filename,label,cli_regex,json_regex",
    OPERATION_PAIRS,
    ids=[f"{f}:{label}" for f, label, _, _ in OPERATION_PAIRS],
)
def test_cli_recipe_leads_function_envelope(
    polish_texts: dict[str, str],
    filename: str,
    label: str,
    cli_regex: str,
    json_regex: str,
) -> None:
    text = polish_texts[filename]
    cli_match = re.search(cli_regex, text)
    json_match = re.search(json_regex, text)
    assert cli_match is not None, (
        f"{filename} ({label}): expected a leading CLI recipe matching "
        f"/{cli_regex}/. The bash recipe MUST come first so Bash-driven "
        f"sessions see the working surface; the function-call JSON "
        f"envelope demotes to a tail 'Function-call equivalent' note."
    )
    if json_match is not None:
        assert cli_match.start() < json_match.start(), (
            f"{filename} ({label}): CLI recipe (offset {cli_match.start()}) "
            f"must precede the function-call JSON envelope "
            f"(offset {json_match.start()}). Invert the order so the "
            f"working bash recipe leads and the JSON envelope demotes."
        )


def test_polish_lifecycle_envelopes_use_canonical_shape(
    polish_texts: dict[str, str],
) -> None:
    """Every retained lifecycle JSON envelope must use the canonical
    function id and the source_status / target_status payload keys.

    Catches the legacy `"function": "lifecycle.transition"` (no `.execute`
    suffix) and the legacy `"from"` / `"to"` payload keys.
    """
    legacy_function_re = re.compile(r'"function":\s*"lifecycle\.transition"\s*[,}]')
    legacy_from_re = re.compile(
        r'"from":\s*"(reviewed-implementation|polishing-implementation)"'
    )
    legacy_to_re = re.compile(r'"to":\s*"(polishing-implementation|implemented)"')
    for filename, text in polish_texts.items():
        assert legacy_function_re.search(text) is None, (
            f"{filename}: retained lifecycle envelope uses legacy "
            f'"function": "lifecycle.transition" — use '
            f'"lifecycle.transition.execute" instead.'
        )
        assert legacy_from_re.search(text) is None, (
            f"{filename}: retained lifecycle envelope uses legacy "
            f'"from" payload key — use "source_status" instead.'
        )
        assert legacy_to_re.search(text) is None, (
            f"{filename}: retained lifecycle envelope uses legacy "
            f'"to" payload key — use "target_status" instead.'
        )
    for filename in ("parse-and-claim.md", "advance.md"):
        text = polish_texts[filename]
        assert "definition.skill_bindings" in text
        assert "definition.transitions" in text
        assert "definition.stages" in text
        assert "workflow_next_stage_ambiguous" in text
        assert "POLISH_THROUGH_STAGE" in text
        assert not re.search(
            r"reviewed-implementation|polishing-implementation|\bimplemented\b", text
        ), f"{filename}: polish routing must not name literal stage ids"
    assert "skip the entry transition" in polish_texts["parse-and-claim.md"]
    assert "repeat steps 10–12" in polish_texts["advance.md"]
    assert "shared handoff recipe" in polish_texts["advance.md"]


def test_leading_cli_examples_omit_session_id(polish_texts: dict[str, str]) -> None:
    """Leading CLI examples must not teach --session-id; the active
    harness session is resolved from the environment.
    """
    pattern = re.compile(
        r"(?:yoke|python3 -m runtime\.api\.service_client)[^\n]*--session-id"
    )
    for filename, text in polish_texts.items():
        match = pattern.search(text)
        assert match is None, (
            f"{filename}: leading CLI example teaches --session-id "
            f"({match.group(0) if match else ''!r}). Drop the flag — the "
            f"active harness session resolves from the environment."
        )


def test_polish_files_under_file_budget_limits() -> None:
    """Each touched polish file stays under the 350-line hard limit
    (300-line design target is advisory).
    """
    limit = 350
    for name in ("parse-and-claim.md", "advance.md", "fixes.md"):
        path: Path = POLISH_DIR / name
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        assert line_count <= limit, (
            f"{name}: {line_count} lines exceeds the {limit}-line hard limit."
        )


@pytest.mark.parametrize("canon", ["issue.07", "issue.08", "epic.05", "epic.06"])
@pytest.mark.parametrize("rename_stages", [False, True])
def test_polish_reruns_review_command_plan(canon: str, rename_stages: bool) -> None:
    """Execute the taught selector against pins and renamed stage identities."""
    path = (
        REPO
        / "packages/yoke-core/src/yoke_core/domain/builtin_workflow_canon"
        / f"{canon}.json"
    )
    definition = json.loads(path.read_text())["definition"]
    review_id = next(
        stage["id"]
        for stage in definition["stages"]
        if stage["board_bucket"] == "reviewing"
    )
    if rename_stages:
        names = {
            stage["id"]: f"state-{index}"
            for index, stage in enumerate(definition["stages"])
        }
        for stage in definition["stages"]:
            stage["id"] = names[stage["id"]]
        for row in (*definition["transitions"], *definition["skill_bindings"]):
            for key in ("from_stage_id", "to_stage_id", "through_stage_id"):
                if key in row:
                    row[key] = names[row[key]]
        review_id = names[review_id]
    binding = next(
        row for row in definition["skill_bindings"] if row["skill_id"] == "polish"
    )
    text = _read(POLISH_DIR / "verify-and-commit.md")
    recipe = re.search(r"```python\n(.*?)\n```", text, re.DOTALL)
    assert recipe is not None
    context = {"definition": definition, "POLISH_ENTRY_STAGE": binding["from_stage_id"]}
    exec(compile(recipe.group(1), "polish-review-selector", "exec"), context)
    assert context["REVIEW_STAGE"] == review_id
    assert context["REVIEW_STAGE"] != binding["through_stage_id"]
    assert '--transition "$REVIEW_STAGE"' in text
    assert '--transition "$NEXT_STAGE"' not in text
    assert "previously satisfied" in text


def test_polish_refuses_ambiguous_review_attachment() -> None:
    text = _read(POLISH_DIR / "verify-and-commit.md")
    recipe = re.search(r"```python\n(.*?)\n```", text, re.DOTALL)
    assert recipe is not None
    definition = {
        "stages": [{"id": "finish", "board_bucket": "reviewing"}],
        "transitions": [],
    }
    with pytest.raises(
        SystemExit, match="polish_review_transition_ambiguous.*workflow owner"
    ):
        exec(
            compile(recipe.group(1), "polish-review-selector", "exec"),
            {
                "definition": definition,
                "POLISH_ENTRY_STAGE": "finish",
            },
        )

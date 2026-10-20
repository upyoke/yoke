"""Polish skill framing — bash-first claim/lifecycle/db-claim recipes.

For each documented operation in the three touched polish files
(`parse-and-claim.md`, `advance.md`, `fixes.md`), the canonical CLI
recipe (`yoke <subcommand>`) MUST appear before any function-call
JSON envelope for the same operation. The CLI recipe is the surface
the operator-facing operator actually runs; the JSON envelope is for
dispatch-surface callers and is allowed to remain as a tail
"Function-call equivalent" block but never as the lead.

Any retained function-call envelope must use the canonical
`lifecycle.transition.execute` function id and the `source_status` /
`target_status` payload keys (not `from` / `to`). Polish routing names no
literal stage ids; it reads its pinned binding.

The leading CLI examples must not teach `--session-id`; the active
harness session is resolved from the environment.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read

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
        r"yoke lifecycle transition",
        r'"function":\s*"lifecycle\.transition\.execute"',
    ),
    (
        "advance.md",
        "lifecycle completes the bound segment",
        r"yoke lifecycle transition[^\n]+--from <live-stage> --to <next-stage>",
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
        assert not re.search(
            r"reviewed-implementation|polishing-implementation|\bimplemented\b",
            polish_texts[filename],
        ), f"{filename}: polish routing must not name literal stage ids"


def test_polish_routes_through_its_pinned_binding(
    polish_texts: dict[str, str],
) -> None:
    parse = polish_texts["parse-and-claim.md"]
    assert "yoke workflows item get PREFIX-N --json" in parse
    assert "The binding containing the live status must be `polish`" in parse
    assert "[stage handoff](../shared/stage-handoff.md)" in parse
    assert "At the entry stage, take the one declared forward edge" in parse
    assert "Until the through-stage" in polish_texts["advance.md"]


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


def test_polish_reruns_review_plan_for_the_unique_review_edge() -> None:
    text = " ".join(_read(POLISH_DIR / "verify-and-commit.md").split())
    assert "unique pinned forward edge from an implementing-bucket" in text
    assert "to a reviewing-bucket stage at or before the polish entry" in text
    assert "stop if not unique" in text
    assert "Rerun every case not passing on the current commit" in text
    assert "--transition <review-stage>" in text
    assert "--transition <next-stage>" not in text

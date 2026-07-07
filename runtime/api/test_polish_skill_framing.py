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
        "lifecycle reviewed-implementation -> polishing-implementation",
        r"/yoke advance.+polishing-implementation",
        r'"function":\s*"lifecycle\.transition\.execute"',
    ),
    (
        "advance.md",
        "lifecycle polishing-implementation -> implemented",
        r"/yoke advance.+implemented",
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
    return {name: _read(POLISH_DIR / name) for name in {"parse-and-claim.md", "advance.md", "fixes.md"}}


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


def test_polish_lifecycle_envelopes_use_canonical_shape(polish_texts: dict[str, str]) -> None:
    """AC-8: every retained lifecycle JSON envelope must use the canonical
    function id and the source_status / target_status payload keys.

    Catches the legacy `"function": "lifecycle.transition"` (no `.execute`
    suffix) and the legacy `"from"` / `"to"` payload keys.
    """
    legacy_function_re = re.compile(r'"function":\s*"lifecycle\.transition"\s*[,}]')
    legacy_from_re = re.compile(r'"from":\s*"(reviewed-implementation|polishing-implementation)"')
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


def test_leading_cli_examples_omit_session_id(polish_texts: dict[str, str]) -> None:
    """AC-9: leading CLI examples must not teach --session-id; the active
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
    """AC-7: each touched polish file stays under the 350-line hard limit
    (300-line design target is advisory).
    """
    limit = 350
    for name in ("parse-and-claim.md", "advance.md", "fixes.md"):
        path: Path = POLISH_DIR / name
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        assert line_count <= limit, (
            f"{name}: {line_count} lines exceeds the {limit}-line hard limit."
        )

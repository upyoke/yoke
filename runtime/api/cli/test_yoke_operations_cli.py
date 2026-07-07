"""Tests for the ``yoke`` operations CLI (Phase 0 in-checkout entrypoint).

Covers the EXP-AC set on YOK-1819's mid-flight expansion — grammar-rule
reversibility, subcommand resolution, entrypoint behaviour, error
shapes, and ``--help`` completeness. Per-family adapter dispatch happy
paths live in :mod:`test_yoke_operations_cli_dispatch`.
"""

from __future__ import annotations

import io
import json
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

import pytest

from yoke_cli.commands import flag_adapters as adapters
from yoke_cli.main import main as cli_main
from yoke_cli.commands.registry import (
    SUBCOMMAND_REGISTRY,
    cli_to_function_id_stem,
    function_id_to_cli,
    resolve,
)


def _expected_cli_version() -> str:
    try:
        return package_version("yoke-cli")
    except PackageNotFoundError:
        return "0.1.0"


class _TtyInput:
    def __init__(self, interactive: bool) -> None:
        self._interactive = interactive

    def isatty(self) -> bool:
        return self._interactive


def _write_usable_machine_config(tmp_path: Path) -> Path:
    token_file = tmp_path / "token"
    token_file.write_text("secret-token\n", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({
            "schema_version": 1,
            "active_env": "prod",
            "connections": {
                "prod": {
                    "transport": "https",
                    "api_url": "https://api.example.test",
                    "credential_source": {
                        "kind": "token_file",
                        "path": str(token_file),
                    },
                },
            },
            "temp_root": str(tmp_path / "tmp"),
            "cache_dir": str(tmp_path / "cache"),
        }),
        encoding="utf-8",
    )
    return config


# ---------------------------------------------------------------------------
# Round-trip grammar-rule reversibility
# ---------------------------------------------------------------------------


class TestGrammarRuleReversibility:
    """Function-id ↔ CLI tokens must follow the strict mechanical rule."""

    def test_every_registered_function_id_maps_to_its_cli_tokens(self) -> None:
        for cli_tokens, (function_id, _adapter) in SUBCOMMAND_REGISTRY.items():
            translated = function_id_to_cli(function_id)
            assert translated == cli_tokens, (
                f"grammar rule violation: function_id={function_id!r} "
                f"translates to {translated!r}, registered as {cli_tokens!r}"
            )

    def test_cli_to_function_id_stem_round_trips(self) -> None:
        for cli_tokens, (function_id, _adapter) in SUBCOMMAND_REGISTRY.items():
            stem = cli_to_function_id_stem(cli_tokens)
            assert function_id.startswith(stem + ".") or function_id == stem, (
                f"CLI {cli_tokens!r} → stem {stem!r} is not a prefix of "
                f"registered function id {function_id!r}"
            )

    def test_no_function_id_contains_hyphens(self) -> None:
        # Hyphens belong in CLI tokens, never inside function-id segments.
        for _cli_tokens, (function_id, _) in SUBCOMMAND_REGISTRY.items():
            assert "-" not in function_id, (
                f"function id {function_id!r} contains a hyphen — "
                "underscores belong in function ids, hyphens in CLI tokens"
            )

    def test_no_cli_token_contains_underscores(self) -> None:
        # Underscores belong in function ids, never inside CLI tokens.
        for cli_tokens, (_fn, _adapter) in SUBCOMMAND_REGISTRY.items():
            for token in cli_tokens:
                assert "_" not in token, (
                    f"CLI token {token!r} (in {cli_tokens!r}) contains an "
                    "underscore — hyphens are the CLI separator"
                )

    def test_no_synthetic_terminal_in_cli_tokens(self) -> None:
        # `.run`/`.execute` are synthetic terminals the grammar drops. A CLI
        # last-token of "run"/"execute" is only legitimate when the function
        # id has an explicit operation named "run"/"execute" before the
        # synthetic terminal (e.g. doctor.run.run -> ('doctor', 'run')).
        for cli_tokens, (function_id, _) in SUBCOMMAND_REGISTRY.items():
            last = cli_tokens[-1]
            if last not in ("run", "execute"):
                continue
            parts = function_id.split(".")
            assert len(parts) >= 2 and parts[-2] == last, (
                f"CLI tokens {cli_tokens!r} ends in synthetic-looking "
                f"terminal {last!r}, but function id {function_id!r} has "
                f"no explicit operation {last!r} before the synthetic "
                "terminal — the grammar would not produce this CLI tuple"
            )


# ---------------------------------------------------------------------------
# Subcommand resolution
# ---------------------------------------------------------------------------


class TestSubcommandResolution:
    def test_three_token_resolves_before_two_token(self) -> None:
        # ("items", "structured-field", "replace") must beat ("items",) prefix.
        cli_tokens, function_id, _, remaining = resolve(
            ["items", "structured-field", "replace", "YOK-1819", "--field", "spec"]
        )
        assert cli_tokens == ("items", "structured-field", "replace")
        assert function_id == "items.structured_field.replace"
        assert remaining == ["YOK-1819", "--field", "spec"]

    def test_two_token_resolves_when_third_isnt_registered(self) -> None:
        cli_tokens, function_id, _, remaining = resolve(
            ["events", "query", "--event-name", "ItemStatusChanged"]
        )
        assert cli_tokens == ("events", "query")
        assert function_id == "events.query.run"
        assert remaining == ["--event-name", "ItemStatusChanged"]

    def test_status_alias_resolves_to_holder_get(self) -> None:
        # Field-note 8814: "claims work status" is an operator-facing alias
        # (like "claims work current") routing to the same
        # claims.work.holder_get function id via the holder-get adapter.
        cli_tokens, function_id, adapter, remaining = resolve(
            ["claims", "work", "status", "--item", "YOK-1884"]
        )
        assert cli_tokens == ("claims", "work", "status")
        assert function_id == "claims.work.holder_get"
        assert adapter is adapters.claims_work_current
        assert remaining == ["--item", "YOK-1884"]

    def test_unknown_subcommand_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            resolve(["nope", "this", "doesnt-exist"])

    def test_empty_argv_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            resolve([])


# ---------------------------------------------------------------------------
# Top-level entrypoint behaviour
# ---------------------------------------------------------------------------


class TestEntrypointBehaviour:
    def test_no_args_prints_help_when_machine_config_is_ready(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        config = _write_usable_machine_config(tmp_path)
        monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config))

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_main([])
        assert rc == 0
        assert "yoke — Yoke operations CLI" in buf.getvalue()

    def test_no_args_missing_config_tty_points_to_onboard(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        monkeypatch.setenv(
            "YOKE_MACHINE_CONFIG_FILE", str(tmp_path / "missing.json"),
        )
        monkeypatch.setattr(sys, "stdin", _TtyInput(True))

        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli_main([])

        assert rc == 1
        text = err.getvalue()
        assert "machine config not found" in text
        assert "Start setup with `yoke onboard`." in text
        assert "--non-interactive" not in text
        assert "yoke --help" in text

    def test_no_args_missing_config_non_tty_prints_automation_recipe(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        monkeypatch.setenv(
            "YOKE_MACHINE_CONFIG_FILE", str(tmp_path / "missing.json"),
        )
        monkeypatch.setattr(sys, "stdin", _TtyInput(False))

        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli_main([])

        assert rc == 1
        text = err.getvalue()
        assert "machine config not found" in text
        assert (
            "yoke onboard --non-interactive --env <env>"
            in text
        )
        assert "--api-url <url>" in text
        assert "yoke --help" in text

    def test_help_flag_prints_help(self) -> None:
        for flag in ("--help", "-h", "help"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_main([flag])
            assert rc == 0
            assert "Available subcommands" in buf.getvalue()

    def test_version_flag_prints_version(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_main(["--version"])
        assert rc == 0
        assert buf.getvalue().strip() == _expected_cli_version()

    def test_unknown_subcommand_returns_two(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli_main(["definitely", "not", "a-subcommand"])
        assert rc == 2
        assert "unknown subcommand" in err.getvalue()

    def test_keyboard_interrupt_returns_clean_ctrl_c_exit(self, monkeypatch) -> None:
        def _interrupt(_argv):
            raise KeyboardInterrupt

        monkeypatch.setitem(
            SUBCOMMAND_REGISTRY,
            ("interrupt",),
            ("interrupt.run", _interrupt),
        )
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli_main(["interrupt"])
        assert rc == 130
        assert err.getvalue().strip() == "yoke: interrupted by Ctrl-C."
        assert "Traceback" not in err.getvalue()

    def test_help_listing_groups_by_family(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli_main(["--help"])
        out = buf.getvalue()
        families = {fn.split(".", 1)[0]
                    for _tokens, (fn, _) in SUBCOMMAND_REGISTRY.items()}
        for family in families:
            assert f"[{family}]" in out
        assert (
            "yoke board art variant create --ascii|--mixed|--image PATH"
            in out
        )
        board_section = re.search(r"\n  \[board\](.*?)(?=\n  \[|\Z)", out, re.S)
        assert board_section
        assert (
            "yoke board art variant create --ascii|--mixed|--image PATH"
            in board_section.group(1)
        )

# ---------------------------------------------------------------------------
# items get --section guard — teaches the two-command shape (8844 / 8855)
# ---------------------------------------------------------------------------


class TestItemsGetSectionGuard:
    """``items get`` with ``--section`` accepts exactly one field; the guard
    error must teach the corrected two-command shape instead of just
    rejecting (field-notes 8844, 8855 — the footgun was sticky)."""

    def _run_section_guard(self, *fields: str) -> tuple[int, str]:
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = cli_main(
                ["items", "get", "YOK-99", *fields, "--section", "## H"]
            )
        return rc, err.getvalue()

    def test_multiple_fields_plus_section_teaches_two_calls(self) -> None:
        rc, msg = self._run_section_guard("status", "title", "body")
        assert rc == 2
        # Echoes what was passed and prints both corrected commands keyed to
        # the real item id so the fix is copy-pasteable.
        assert "exactly one field argument" in msg
        assert "status title body" in msg
        assert msg.count("yoke items get YOK-99") == 2
        assert "--section" in msg

    def test_zero_fields_plus_section_teaches_two_calls(self) -> None:
        rc, msg = self._run_section_guard()
        assert rc == 2
        assert "got 0: none" in msg
        assert "yoke items get YOK-99" in msg


# ---------------------------------------------------------------------------
# Help-text completeness
# ---------------------------------------------------------------------------


class TestHelpText:
    def test_every_registered_function_id_has_a_usage_entry(self) -> None:
        for _tokens, (function_id, _adapter) in SUBCOMMAND_REGISTRY.items():
            assert function_id in adapters.ADAPTER_USAGE, (
                f"function id {function_id!r} is registered but has no "
                "ADAPTER_USAGE entry"
            )

    def test_every_usage_string_starts_with_yoke(self) -> None:
        for function_id, usage in adapters.ADAPTER_USAGE.items():
            assert usage.startswith("yoke "), (
                f"usage for {function_id!r} should start with 'yoke ': {usage!r}"
            )


# ---------------------------------------------------------------------------
# Usage-string ↔ parser conformance
# ---------------------------------------------------------------------------


_FLAG_TOKEN_RE = re.compile(r"--[A-Za-z0-9][A-Za-z0-9-]*")
_ANGLE_PLACEHOLDER_RE = re.compile(r"<[^<>]*>")


def _usage_flag_tokens(usage: str) -> set[str]:
    return set(_FLAG_TOKEN_RE.findall(_ANGLE_PLACEHOLDER_RE.sub(" ", usage)))


def _capture_subcommand_help(cli_tokens: tuple[str, ...]) -> str:
    out = io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = cli_main([*cli_tokens, "--help"])
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
    assert rc == 0, (
        f"`yoke {' '.join(cli_tokens)} --help` exited {rc} instead of "
        "printing parser help"
    )
    return out.getvalue()


class TestUsageParserConformance:
    """Every flag a usage string advertises must exist on the parser.

    The parser is ground truth: ``--help`` output is generated from the
    argparse definition, so a usage-string flag missing there is a stale
    or confabulated teaching surface.
    """

    @pytest.mark.parametrize(
        "cli_tokens, function_id",
        [(tokens, fn) for tokens, (fn, _adapter) in sorted(
            SUBCOMMAND_REGISTRY.items())],
        ids=lambda value: " ".join(value) if isinstance(value, tuple) else None,
    )
    def test_usage_flags_exist_on_parser(
        self, cli_tokens: tuple[str, ...], function_id: str,
        monkeypatch,
    ) -> None:
        monkeypatch.setenv(
            "YOKE_MACHINE_CONFIG_FILE", "/nonexistent/machine-config.json",
        )
        usage = adapters.ADAPTER_USAGE[function_id]
        usage_flags = _usage_flag_tokens(usage)
        help_text = _capture_subcommand_help(cli_tokens)
        parser_flags = set(_FLAG_TOKEN_RE.findall(help_text))
        missing = usage_flags - parser_flags
        assert not missing, (
            f"usage string for {function_id!r} advertises flags the parser "
            f"does not define: {sorted(missing)}\n  usage: {usage}"
        )

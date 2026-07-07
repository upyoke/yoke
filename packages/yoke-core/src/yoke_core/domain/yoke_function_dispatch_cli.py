"""CLI entrypoint for the Yoke function-call dispatcher.

Reads a request envelope from file/stdin, calls ``dispatch()``, and maps
the structured response to shell exit codes:

- ``0``: success, response JSON on stdout.
- ``1``: constructed envelope dispatched but failed, error + JSON on stderr.
- ``2``: invalid envelope/input, field-path or parse message on stderr.

The dispatcher itself stays a pure programmatic surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional, Sequence

from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_contracts.api.function_call import FunctionCallResponse


EXIT_SUCCESS = 0
EXIT_DISPATCH_FAILURE = 1
EXIT_ENVELOPE_INVALID = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.yoke_function_dispatch_cli",
        description=(
            "Dispatch a Yoke function-call envelope and map the response "
            "to a Unix exit code (0 success, 1 dispatch failure, 2 envelope "
            "or input parse failure)."
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--request-file",
        metavar="PATH",
        help="Read the envelope JSON from PATH.",
    )
    source.add_argument(
        "--stdin",
        action="store_true",
        help="Read the envelope JSON from stdin.",
    )
    parser.add_argument(
        "--ambient-session-id",
        metavar="ID",
        default=None,
        help=(
            "Override the env-chain session lookup. Mirrors the "
            "``ambient_session_id`` kwarg on ``dispatch()``."
        ),
    )
    return parser


def _load_envelope(args: argparse.Namespace) -> Any:
    if args.stdin:
        raw = sys.stdin.read()
        source_label = "<stdin>"
    else:
        try:
            with open(args.request_file, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            raise ValueError(
                f"could not read --request-file {args.request_file!r}: {exc}"
            ) from exc
        source_label = args.request_file
    if not raw.strip():
        raise ValueError(f"empty envelope read from {source_label}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in envelope from {source_label}: {exc}") from exc


def _emit_failure(response: FunctionCallResponse) -> int:
    error = response.error
    code = error.code if error is not None else "unknown_error"
    message = error.message if error is not None else "(no error message)"
    if code == "envelope_invalid":
        print(message, file=sys.stderr)
        return EXIT_ENVELOPE_INVALID
    print(f"{code}: {message}", file=sys.stderr)
    print(response.model_dump_json(), file=sys.stderr)
    return EXIT_DISPATCH_FAILURE


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        envelope = _load_envelope(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ENVELOPE_INVALID

    response = dispatch(envelope, ambient_session_id=args.ambient_session_id)
    if response.success:
        print(response.model_dump_json())
        return EXIT_SUCCESS
    return _emit_failure(response)


if __name__ == "__main__":
    sys.exit(main())

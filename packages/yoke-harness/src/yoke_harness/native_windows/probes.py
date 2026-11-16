"""Canonical baseline probes with native paths and a real Windows GUI session."""

import json
from pathlib import PureWindowsPath

from yoke_harness.ssh_mac_baseline_probes import (
    parse_baseline_probes,
    run_baseline_probes,
)
from yoke_harness.standard_baseline_probes import standard_probes


def capture_document(control, supplied):
    result = control._run("(Get-Command python.exe -ErrorAction Stop).Source")
    python = result.stdout.strip()
    if result.returncode or not PureWindowsPath(python).is_absolute():
        raise ValueError(
            "windows_baseline_python_required: install native Python 3 for the standard test user, prove python.exe works, and retry capture"
        )
    standard = standard_probes("windows")
    for probe in standard:
        probe["argv"][0] = python
    extras = []
    if supplied is not None:
        parsed = parse_baseline_probes(supplied)
        names = {probe["name"] for probe in standard}
        if names - {probe.name for probe in parsed}:
            raise ValueError(
                "baseline_standard_probes_missing: include the standard harness checks or omit the probes file"
            )
        extras = [
            {
                "name": probe.name,
                "argv": list(probe.argv),
                **(
                    {"expect_output_contains": probe.expect_output_contains}
                    if probe.expect_output_contains
                    else {}
                ),
            }
            for probe in parsed
            if probe.name not in names
        ]
    document = json.dumps({"probes": [*standard, *extras]})
    parse_baseline_probes(document)
    return document


def prove_document(control, document):
    return run_baseline_probes(
        parse_baseline_probes(document),
        run_gui_command=lambda argv, timeout: control.run_command(
            argv, required_session_context="gui", timeout=timeout
        ),
        classify_gui_failures=False,
    )

"""Strict native feature evidence from the fixed SYSTEM restore task."""

from yoke_contracts.machine_qa_failures import HostControlLocalError

FEATURES = frozenset({"Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform"})


def feature_states(value):
    valid = isinstance(value, list) and len(value) == len(FEATURES)
    states = {}
    if valid:
        for row in value:
            if (
                not isinstance(row, dict) or not isinstance(row.get("Name"), str)
                or row["Name"] not in FEATURES
                or row["Name"] in states or type(row.get("InstallState")) is not int
                or row["InstallState"] not in (1, 2, 3)
            ):
                valid = False
                break
            states[row["Name"]] = row["InstallState"]
    if not valid or set(states) != FEATURES:
        raise HostControlLocalError(
            code="native_windows_features_unverified", phase="native_feature_proof",
            detail="The fixed recovery task did not return complete, known Windows feature states.",
            recovery_hint="Refresh the fixed administrator recovery program with the full guest provisioner, acquire a fresh QA lease, and retry; do not grant the test user WMI or administrator access.",
        )
    return states


def features_absent(states):
    # Win32_OptionalFeature: 1 enabled, 2 disabled, 3 absent; unknown never passes.
    return set(states) == FEATURES and all(type(state) is int and state in (2, 3) for state in states.values())

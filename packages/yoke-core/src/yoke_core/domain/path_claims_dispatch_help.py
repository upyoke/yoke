"""Canonical ``--help`` descriptions for the path-claim dispatch parsers.

Extracted from the dispatch siblings so the dispatch modules stay
within the 350-line authored cap. Consumed under
``argparse.RawTextHelpFormatter`` — each constant includes a worked
example with a concrete ``YOK-N`` value.
"""

from __future__ import annotations


REGISTER_DESCRIPTION = (
    "Register a path claim covering one or more files (or planned paths) "
    "for an item.\n\n"
    "Worked example (canonical agent shape):\n"
    "  yoke claims path register --item YOK-N \\\n"
    "    --paths runtime/api/domain/foo.py,runtime/api/domain/test_foo.py\n\n"
    "Worked example (planned files not yet on disk):\n"
    "  yoke claims path register --item YOK-N --allow-planned \\\n"
    "    --paths runtime/api/service_client_bar.py\n\n"
    "Operator-debug fallback inside a Yoke checkout:\n"
    "  python3 -m yoke_core.api.service_client path-claim-register \\\n"
    "    --item YOK-N --integration-target main \\\n"
    "    --paths runtime/api/domain/foo.py,runtime/api/domain/test_foo.py\n\n"
    "Exception mode (operator no-claim justification on no paths):\n"
    "  python3 -m yoke_core.api.service_client path-claim-register \\\n"
    "    --item YOK-N --mode exception \\\n"
    "    --reason \"evidence-only ticket; no repo changes\"\n"
)


WIDEN_DESCRIPTION = (
    "Widen a non-terminal path claim with additional paths. Identify the "
    "claim by positional id or ``--item YOK-N``.\n\n"
    "Worked example (canonical agent shape):\n"
    "  yoke claims path widen --claim-id 138 --item YOK-N \\\n"
    "    --add-paths runtime/api/domain/foo_helper.py \\\n"
    "    --reason \"implementation discovered helper sibling\"\n\n"
    "Operator-debug fallback inside a Yoke checkout:\n"
    "  python3 -m yoke_core.api.service_client path-claim-widen \\\n"
    "    --item YOK-N \\\n"
    "    --paths runtime/api/domain/foo_helper.py \\\n"
    "    --reason \"implementation discovered helper sibling\"\n\n"
    "Planned (not-yet-on-disk) paths require ``--allow-planned``:\n"
    "  python3 -m yoke_core.api.service_client path-claim-widen \\\n"
    "    --item YOK-N --paths runtime/api/service_client_new.py \\\n"
    "    --allow-planned --reason \"new adapter module\"\n"
)


__all__ = ["REGISTER_DESCRIPTION", "WIDEN_DESCRIPTION"]

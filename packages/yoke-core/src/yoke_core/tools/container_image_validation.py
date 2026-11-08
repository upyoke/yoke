"""Validate every installed core module and its real project bundle once."""

from __future__ import annotations

import sys

from yoke_core.tools.product_wheel_validation import verify_installed_boot


def verify_bundle():
    # Keep bundle imports behind the tracked complete-module import pass.
    from yoke_core.tools.container_bundle_validation import verify_project_bundle

    return verify_project_bundle()


def main() -> int:
    failed = False
    for name, check in (
        ("installed core modules", verify_installed_boot),
        ("installed project bundle", verify_bundle),
    ):
        try:
            check()
        except (Exception, SystemExit) as exc:
            failed = True
            print(
                f"container_image_validation_failed: {name}: {exc}; "
                "fix the installed product and rebuild the image",
                file=sys.stderr,
            )
        else:
            print(f"container image validation passed: {name}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

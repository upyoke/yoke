# Browser-authenticated host missions

Test-machine browser authorization, profile capture, restoration, and proof
belong to the [Machine QA Pack Linux provisioning procedure](../../../../packs/machine-qa/versions/1.3.7/files/docs/packs/machine-qa/linux-host-provisioning.md).
After installation, read `docs/packs/machine-qa/linux-host-provisioning.md`.
That guide identifies the supported OS and both mission execution routes.

For the mission contract, see [Exploratory QA](../exploratory-qa.md).
For browser implementation details, see the project's browser-substrate docs.

Profile snapshot capture and restore create every missing directory with
owner-only permissions. Existing directories keep their permissions; an unsafe
credential directory is refused with its path, including in the onboarding
wizard, so the operator can inspect that directory before retrying.

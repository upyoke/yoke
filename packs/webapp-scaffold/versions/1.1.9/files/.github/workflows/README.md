# GitHub Actions Workflows

The Webapp Scaffold Pack installs only ci.yml. It runs backend tests and the
frontend build for pushes and pull requests.

Smoke workflows belong to a separate Pack; production, hotfix,
preview-environment, and runner workflows are project-owned. Inspect and
preview only the capabilities this project needs:

    yoke packs list --project <project>
    yoke packs get smoke-testing /path/to/project --project <project>

Every installed workflow becomes project-owned source. Review its action pins,
permissions, triggers, environments, secrets, commands, and health checks
before applying or committing it.

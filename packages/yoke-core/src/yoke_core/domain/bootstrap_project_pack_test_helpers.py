"""Pack-operation fakes shared by bootstrap project tests."""

from pathlib import Path


def install_fake_pack_operations(monkeypatch) -> list[dict[str, object]]:
    """Install an in-process Pack client fake for bootstrap setup tests."""

    calls: list[dict[str, object]] = []
    installed: dict[str, dict[str, str]] = {}

    def fake_load_receipt(_repo_root: Path) -> dict[str, object]:
        return {"schema_version": 1, "packs": dict(installed)}

    def fake_run_pack_operation(
        repo_root: Path,
        *,
        project: str,
        pack: str,
        operation: str,
        apply: bool,
    ) -> dict[str, object]:
        calls.append({
            "repo_root": repo_root,
            "project": project,
            "pack": pack,
            "operation": operation,
            "apply": apply,
        })
        if not apply:
            raise AssertionError("bootstrap must apply each requested Pack")

        representative_files = {
            "production-deploy": (
                ".github/workflows/externalwebapp-deploy.yml",
                "name: ExternalWebapp Deploy\n",
            ),
            "smoke-testing": (
                ".github/workflows/externalwebapp-smoke.yml",
                "name: ExternalWebapp Smoke Test\n",
            ),
            "ephemeral-environments": (
                ".github/workflows/externalwebapp-ephemeral.yml",
                "name: ExternalWebapp Ephemeral\n",
            ),
            "vps-hosting": ("ops/provision-tls.sh", "#!/bin/sh\n"),
        }
        relative_path, content = representative_files[pack]
        target = repo_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        installed[pack] = {"version": "1.0.0"}
        return {
            "pack": pack,
            "operation": operation,
            "applied": True,
            "refused": False,
        }

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_setup.load_receipt",
        fake_load_receipt,
    )
    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_setup.run_pack_operation",
        fake_run_pack_operation,
    )
    return calls


__all__ = ["install_fake_pack_operations"]

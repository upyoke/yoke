"""Prepare automatic browser identities before a Browser case starts capturing."""


def prepare_automatic_identities(project, declared, identities):
    # Credential access and Playwright execution stay in the local harness;
    # this orchestration never reads values or adds them to QA artifacts.
    from yoke_cli.commands.browser_sign_in import prepare_browser_runtime
    from yoke_harness import browser_client
    from yoke_harness.browser_automatic_sign_in import sign_in_expired_sites

    selected = [
        declared[name]
        for name in dict.fromkeys(identities)
        if name in declared and any(s.sign_in for s in declared[name].sites)
    ]
    if selected:
        runtime = prepare_browser_runtime("authorize-automatic.js")
        for identity in selected:
            sign_in_expired_sites(browser_client, runtime, project, identity)

"""Installer mission territory and proof, alongside stable deterministic cases."""

from yoke_core.domain.installer_campaign_current_text_cases import (
    CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES,
)

WELCOME_FRAME = {'position': 2,
 'case_key': 'welcome-frame',
 'entry_surface': '/usr/bin/curl -fsSL {{installer_base_url}}/install | /usr/bin/env '
                  'HOME=/var/empty XDG_BIN_HOME=/var/empty/.local/bin '
                  'PATH=/usr/bin:/bin:/usr/sbin:/sbin '
                  'YOKE_INSTALL_BASE_URL={{installer_base_url}} '
                  'YOKE_CHANNEL={{release_channel}} /bin/sh',
 'required_completion': 'welcome-frame',
 'host_baselines': [],
 'starting_state': 'as_is',
 'starting_state_reason': 'The installer runs with HOME=/var/empty and a minimal '
                          'system PATH, so it neither reads nor changes the host '
                          "user's state",
 'method_id': 'exploratory-mission',
 'instructions': 'Resolve host/setup obstacles yourself: answer consent prompts, '
                 "select the declared identity's email in Google's account chooser "
                 'and dismiss stray sheets. Report each workaround in ranked '
                 'findings with evidence and its tested boundary. Never replace '
                 'browser approval with yoke machines approve, stored credentials or '
                 'token paste. Stop for a real password, 2FA or payment step. '
                 'Explore the authored welcome using the declared public installer '
                 'entry surface in visible Terminal. Keep HOME=/var/empty, '
                 'XDG_BIN_HOME=/var/empty/.local/bin and the minimal macOS system '
                 'PATH; do not change the real home. Observe the automatic uv '
                 'attempt and diagnose its refusal. An unrelated download failure '
                 'does not prove the welcome outcome.',
 'expected_outcome': "The real installer deterministically presents Yoke's authored "
                     'identity and attempts uv installation, then exits 1 with the '
                     'named uv installation failure and its manual-install recovery. '
                     'Capture text and a screenshot or an explicit capture-degraded '
                     'reason. Required visible text: ["Your operating system for '
                     'software delivery", "Installing uv", "uv installation failed. '
                     'Install uv manually", "then rerun: curl -fsSL"]. Exit code 1 '
                     'is expected only with the diagnosed uv installation refusal '
                     'and manual-install recovery. Keep evidence secret-free; no '
                     'Traceback or "Paste your Yoke API token." prompt.',
 'method_config': {'executor': 'informed_subagent'}}

COLD_START_HOSTED = {'position': 3,
 'case_key': 'cold-start-hosted',
 'entry_surface': '/usr/bin/curl -fsSL {{installer_base_url}}/install | /usr/bin/env '
                  'YOKE_INSTALL_BASE_URL={{installer_base_url}} '
                  'YOKE_CHANNEL={{release_channel}} '
                  'YOKE_ONBOARD_DESTINATION={{app_url}} /bin/sh',
 'required_completion': 'complete-onboarding',
 'host_baselines': ['fresh-host', 'shell-preconfigured'],
 'starting_state': 'baseline',
 'starting_state_reason': None,
 'method_id': 'exploratory-mission',
 'instructions': 'Resolve host/setup obstacles yourself: answer consent prompts, '
                 "select the declared identity's email in Google's account chooser "
                 'and dismiss stray sheets. Report each workaround in ranked '
                 'findings with evidence and its tested boundary. Never replace '
                 'browser approval with yoke machines approve, stored credentials or '
                 'token paste. Stop for a real password, 2FA or payment step. '
                 'Explore public {{environment_display_name}} hosted onboarding '
                 'through {{app_url}} from each declared PATH baseline. Approve the '
                 'displayed Match code in the host browser using the declared '
                 'identity; verify the same-tab confirmation and the terminal '
                 'advancing. Keep GitHub disabled and choose machine-only setup, '
                 'inspect Review, Apply and follow the parent installer handoff. '
                 'Before walk-end restores state, verify at least one hosted token '
                 'file exists under $HOME/.yoke/secrets, the secrets directory mode '
                 'is 700 and every *.token file mode is 600. Use zsh '
                 'files=("$HOME"/.yoke/secrets/*.token(N)); (( ${#files[@]} > 0 )); '
                 'inspect each file in "${files[@]}" with stat without reading contents. '
                 'Record the three checks '
                 'separately (token-file-exists, secrets-directory-mode-700, '
                 'token-file-modes-600) without reading token contents. Investigate '
                 'usability and failures rather than replaying timed keystrokes.',
 'expected_outcome': 'Both fresh-host and shell-preconfigured complete '
                     'browser-approved {{environment_display_name}} onboarding with '
                     'exit code 0, Apply report and parent installer handoff. The '
                     'fresh host repairs PATH and the preconfigured shell does not. '
                     'Before cleanup token-file-exists proves at least one hosted '
                     'token; secrets-directory-mode-700 proves mode 700; '
                     'token-file-modes-600 proves every token mode 600 without '
                     'exposing contents. Required visible text: ["Sign in and choose '
                     'an organization.", "Approve this machine in your browser, then '
                     'continue here.", "Match code:", "Open:", "Connect GitHub?", '
                     '"Review what Yoke will save.", "Apply", "Setup complete.", '
                     '"Everything in the Review plan was applied.", "Report:", '
                     '"Next: bring your existing work into Yoke.", "run /yoke '
                     'onboard"]. Exit code 0 and a durable Apply report are '
                     'required, followed by "Next: bring your existing work into '
                     'Yoke." and "run /yoke onboard". Keep evidence secret-free; no '
                     'Traceback or "Paste your Yoke API token." prompt.',
 'method_config': {'executor': 'informed_subagent'}}

CONNECT_WAIT = {'position': 9,
 'case_key': 'connect-wait',
 'entry_surface': '{yoke_bin} setup --connect {{app_url}} --project-mode '
                  'machine-only',
 'required_completion': 'connect-wait',
 'host_baselines': ['fresh-host'],
 'starting_state': None,
 'starting_state_reason': None,
 'method_id': 'exploratory-mission',
 'instructions': 'Resolve host/setup obstacles yourself: answer consent prompts, '
                 "select the declared identity's email in Google's account chooser "
                 'and dismiss stray sheets. Report each workaround in ranked '
                 'findings with evidence and its tested boundary. Never replace '
                 'browser approval with yoke machines approve, stored credentials or '
                 'token paste. Stop for a real password, 2FA or payment step. '
                 'Prepare the current published {{environment_display_name}} release '
                 'without setup using the public installer with YOKE_NO_SETUP=1, '
                 'then repair PATH through its installed guidance. Start fresh '
                 'hosted authorization at {{app_url}} with no reusable connection in '
                 'the declared baseline. Inspect the visible Terminal while approval '
                 'is pending; stop at that frame without approving or substituting '
                 'token paste. Preserve the host state required by this case until '
                 'proof is captured.',
 'expected_outcome': 'The Terminal shows the Match code, browser URL, and explicit '
                     'continue-after-approval instruction without exposing a '
                     'credential. Required visible text: ["Sign in and choose an '
                     'organization.", "Approve this machine in your browser, then '
                     'continue here.", "Match code:", "Open:"]. End at connect-wait '
                     'with authorization still pending; an exit or an approval does '
                     'not substitute for this frame. Keep evidence secret-free; no '
                     'Traceback or "Paste your Yoke API token." prompt.',
 'method_config': {'executor': 'informed_subagent'}}

REVIEW_FRAME = {'position': 10,
 'case_key': 'review-frame',
 'entry_surface': '{yoke_bin} setup --connect {{app_url}} --project-mode '
                  'machine-only',
 'required_completion': 'back-before-apply',
 'host_baselines': ['fresh-host'],
 'starting_state': None,
 'starting_state_reason': None,
 'method_id': 'exploratory-mission',
 'instructions': 'Resolve host/setup obstacles yourself: answer consent prompts, '
                 "select the declared identity's email in Google's account chooser "
                 'and dismiss stray sheets. Report each workaround in ranked '
                 'findings with evidence and its tested boundary. Never replace '
                 'browser approval with yoke machines approve, stored credentials or '
                 'token paste. Stop for a real password, 2FA or payment step. '
                 'Prepare the current published {{environment_display_name}} release '
                 'without setup using the public installer with YOKE_NO_SETUP=1 and '
                 'its supported PATH repair. Start fresh authorization at '
                 '{{app_url}}. Approve the Match code through the declared host '
                 'browser and verify same-tab confirmation and terminal advancement. '
                 'Keep GitHub disabled and inspect machine-only Review before Apply. '
                 'Select Show all changes, capture every named pending write and the '
                 'existing-token reuse line, reveal Show summary and back out '
                 'without Apply. Category counts alone do not prove the write list.',
 'expected_outcome': 'Review names the pending writes and presents Apply as the '
                     'primary action only after browser approval has produced a '
                     'verified connection. Required visible text: ["Sign in and '
                     'choose an organization.", "Approve this machine in your '
                     'browser, then continue here.", "Match code:", "Open:", '
                     '"Connect GitHub?", "Review what Yoke will save.", "Apply", '
                     '"Show summary", "Reuse this machine\'s existing Yoke API '
                     'token"]. Show all changes exposes named writes including '
                     '"Reuse this machine\'s existing Yoke API token"; Show summary '
                     'remains available; end before Apply. Keep evidence '
                     'secret-free; no Traceback or "Paste your Yoke API token." '
                     'prompt.',
 'method_config': {'executor': 'informed_subagent'}}

_STABLE = {case["case_key"]: case for case in CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES}
INSTALLER_CAMPAIGN_CASES = (
    _STABLE["path-on-shell"],
    {**_STABLE["path-repair"], "host_baselines": ["fresh-host"], "starting_state": None},
    _STABLE["apply-handoff"],
    _STABLE["universe-born"],
    WELCOME_FRAME,
    COLD_START_HOSTED,
    CONNECT_WAIT,
    REVIEW_FRAME,
)

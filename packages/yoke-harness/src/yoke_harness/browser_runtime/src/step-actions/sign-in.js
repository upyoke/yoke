"use strict";

const { signInSite } = require('../automatic-sign-in');
const { checkSites } = require('../verify-sign-in');

async function executeSignIn(page, step, options) {
  const entry = options.signIn;
  const identity = entry?.identity;
  const result = { site: step.site, identity, state: 'failed' };
  if (!entry || entry.site !== step.site || !entry.sign_in) {
    return { ...result, success: false,
      error: 'browser_sign_in_step_not_automatic: declare automatic sign_in for '
        + 'this case identity and site, then retry the case' };
  }
  try {
    const submitted = await signInSite(page.context(), entry, entry.secret_files, page);
    if (submitted.state === 'secret_missing') {
      const key = `sign-in.${identity}.${step.site}.${submitted.field}`;
      return { ...result, success: false,
        error: `browser_sign_in_secret_missing: store ${key} with `
          + 'yoke projects capability secret set --cap-type browser-control '
          + `--project ${entry.project} --key ${key} --value-stdin, then retry` };
    }
    const checked = submitted.state === 'submitted'
      ? (await checkSites(page.context(), [entry.probe]))[0] : submitted;
    if (checked.state === 'signed_in') {
      return { site: step.site, identity, state: 'signed_in', success: true };
    }
  } catch (_) {
    // Playwright logs, URLs and probe details may contain a credential.
  }
  return { ...result, success: false,
    error: 'browser_automatic_sign_in_failed: check the stored credentials and '
      + 'declared sign_in steps and signed_in_check, then retry the case' };
}

module.exports = { executeSignIn };

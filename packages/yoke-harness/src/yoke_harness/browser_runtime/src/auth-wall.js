'use strict';

/**
 * Detect a cookie-session authentication wall: a page whose visible
 * affordance is Sign in, rather than the screen a case asked for.
 *
 * A navigate that lands here is still a successful navigate — login-form
 * cases start on this page on purpose. A wait_for or assert that times
 * out here is not a missing selector on the requested screen.
 */

const PROBE_TIMEOUT_MS = 200;
const SIGN_IN_NAME = /^sign in$/i;

/**
 * @param {import('playwright').Page} page
 * @returns {Promise<boolean>}
 */
async function pageShowsAuthenticationWall(page) {
  if (!page) {
    return false;
  }
  try {
    const candidates = [
      page.getByRole('link', { name: SIGN_IN_NAME }),
      page.getByRole('button', { name: SIGN_IN_NAME }),
    ];
    const visible = await Promise.all(
      candidates.map((loc) =>
        loc.first().isVisible({ timeout: PROBE_TIMEOUT_MS }).catch(() => false)
      )
    );
    return visible.some(Boolean);
  } catch (_) {
    return false;
  }
}

/**
 * @param {Object} step
 * @param {Error|string} err
 * @returns {boolean}
 */
function isSelectorWaitTimeout(step, err) {
  const action = step && step.action;
  if (action !== 'wait_for' && action !== 'assert') {
    return false;
  }
  const message = String((err && err.message) || err || '');
  return /timeout/i.test(message);
}

function authenticationWallError() {
  return (
    'execution_target_unauthorized: this page is an authentication wall, '
    + 'not the screen the case asked for'
  );
}

module.exports = {
  authenticationWallError,
  isSelectorWaitTimeout,
  pageShowsAuthenticationWall,
};

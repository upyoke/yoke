'use strict';

/**
 * Google's account chooser is a sign-in page the password-wall probe misses.
 *
 * When it is showing, click the account the case identity recorded. Never
 * type a password or any other credential. If that account is not offered,
 * or a Google sign-in page remains, the step fails as browser_sign_in_setup.
 */

const SETUP = 'browser_sign_in_setup';
const PROBE_TIMEOUT_MS = 200;
const SELECT_TIMEOUT_MS = 3000;

function googleHost(page) {
  try {
    return new URL(page.url()).hostname === 'accounts.google.com';
  } catch (_) {
    return false;
  }
}

/**
 * @param {import('playwright').Page} page
 * @returns {Promise<boolean>}
 */
async function pageOnGoogleSignIn(page) {
  return Boolean(page) && googleHost(page);
}

/**
 * @param {import('playwright').Page} page
 * @param {string} account
 * @returns {Promise<{ok: boolean, error?: string}>}
 */
async function clickRecordedAccount(page, account) {
  if (!account) {
    return {
      ok: false,
      error: `${SETUP}: this identity records no Google account to choose`,
    };
  }
  if (/["\\\s\]]/.test(account)) {
    return {
      ok: false,
      error: `${SETUP}: the recorded account cannot be selected`,
    };
  }
  const row = page.locator(`[data-identifier="${account}"]`).first();
  const offered = await row.isVisible({ timeout: PROBE_TIMEOUT_MS }).catch(() => false);
  if (!offered) {
    return {
      ok: false,
      error: `${SETUP}: Google's account chooser does not offer ${account}`,
    };
  }
  try {
    await row.click();
  } catch (err) {
    return {
      ok: false,
      error: `${SETUP}: could not select ${account} (${err.message || err})`,
    };
  }
  await page.waitForURL(
    (next) => {
      try {
        return new URL(next).hostname !== 'accounts.google.com';
      } catch (_) {
        return false;
      }
    },
    { timeout: SELECT_TIMEOUT_MS },
  ).catch(() => {});
  return { ok: true };
}

/**
 * Leave Google's chooser by selecting `account`, or name why the run cannot.
 *
 * @param {import('playwright').Page} page
 * @param {string} [account]
 * @returns {Promise<{signInPage: boolean, error?: string}>}
 */
async function settleGoogleSignIn(page, account) {
  if (!page || !googleHost(page)) {
    return { signInPage: false };
  }
  const chooser = await page.getByRole('heading', { name: /choose an account/i })
    .first()
    .isVisible({ timeout: PROBE_TIMEOUT_MS })
    .catch(() => false);
  if (chooser) {
    const selected = await clickRecordedAccount(page, account || '');
    if (!selected.ok) {
      return { signInPage: true, error: selected.error };
    }
  }
  if (googleHost(page)) {
    return {
      signInPage: true,
      error: `${SETUP}: a Google sign-in page is still showing`,
    };
  }
  return { signInPage: false };
}

module.exports = {
  pageOnGoogleSignIn,
  settleGoogleSignIn,
};

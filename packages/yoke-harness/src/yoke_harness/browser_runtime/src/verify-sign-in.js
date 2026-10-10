'use strict';

/**
 * Headless signed-in check for every site one browser identity declares.
 *
 * Usage: node verify-sign-in.js --profile-dir path --checks JSON
 *
 * `--checks` is a JSON array of `{site, url, signed_in_selector}` or
 * `{site, url, signed_in_status}` probes (shape owned by
 * `yoke_contracts.browser_identity`). Each site is checked separately and the
 * process prints one JSON object: `{"sites": [{site, state, detail}]}` where
 * state is `signed_in`, `expired` (the site answered, and not signed in) or
 * `unreachable` (the check could not get an answer, which no sign-in fixes).
 *
 * A selector probe loads the URL and is signed in when the element is visible
 * and the page shows no sign-in wall -- the same wall detection a case step
 * uses (`auth-wall.js`). A status probe requests the URL with the profile's
 * cookies and without following redirects, because a signed-out request is
 * usually redirected to a sign-in page that itself answers 200.
 *
 * This only reads: it never types, clicks or signs in.
 */

const { chromium } = require('playwright');
const { launchOptions } = require('./browser-executable');
const { pageShowsAuthenticationWall } = require('./auth-wall');

const CHECK_TIMEOUT_MS = 15000;

function parseArgs(argv) {
  const args = { profileDir: '', checks: null };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--profile-dir':
        args.profileDir = argv[++i];
        break;
      case '--checks':
        args.checks = JSON.parse(argv[++i]);
        break;
      default:
        throw new Error(`Unknown argument: ${argv[i]}`);
    }
  }
  if (!args.profileDir || !Array.isArray(args.checks)) {
    throw new Error('--profile-dir and a --checks JSON array are required.');
  }
  return args;
}

async function checkStatus(context, check) {
  const response = await context.request.get(check.url, {
    maxRedirects: 0,
    timeout: CHECK_TIMEOUT_MS,
    failOnStatusCode: false,
  });
  const status = response.status();
  return status === check.signed_in_status
    ? { state: 'signed_in', detail: `answered ${status}` }
    : { state: 'expired', detail: `answered ${status}, signed in answers ${check.signed_in_status}` };
}

async function checkSelector(context, check) {
  const page = await context.newPage();
  try {
    await page.goto(check.url, { waitUntil: 'domcontentloaded', timeout: CHECK_TIMEOUT_MS });
    const visible = await page.locator(check.signed_in_selector).first()
      .waitFor({ state: 'visible', timeout: CHECK_TIMEOUT_MS })
      .then(() => true, () => false);
    if (visible && !(await pageShowsAuthenticationWall(page))) {
      return { state: 'signed_in', detail: `${check.signed_in_selector} is visible` };
    }
    return {
      state: 'expired',
      detail: `landed on ${page.url()} without ${check.signed_in_selector}`,
    };
  } finally {
    await page.close().catch(() => {});
  }
}

/**
 * Check each declared site with an already-open persistent context.
 * Exported so the contract test can drive it without a real profile.
 */
async function checkSites(context, checks) {
  const sites = [];
  for (const check of checks) {
    try {
      const outcome = check.signed_in_status !== undefined
        ? await checkStatus(context, check)
        : await checkSelector(context, check);
      sites.push({ site: check.site, ...outcome });
    } catch (error) {
      sites.push({
        site: check.site,
        state: 'unreachable',
        detail: String((error && error.message) || error).split('\n')[0],
      });
    }
  }
  return sites;
}

async function main() {
  const args = parseArgs(process.argv);
  const context = await chromium.launchPersistentContext(args.profileDir, {
    ...launchOptions(),
    headless: true,
    chromiumSandbox: true,
  });
  try {
    console.log(JSON.stringify({ sites: await checkSites(context, args.checks) }));
  } finally {
    await context.close();
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`browser_sign_in_check_failed: ${err.message}`);
    process.exit(1);
  });
}

module.exports = { checkSites, parseArgs };

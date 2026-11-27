'use strict';

/**
 * Signed-in check for every site one browser identity declares.
 *
 * Usage: node verify-sign-in.js (--profile-dir path | --live-endpoint URL) --checks JSON
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

const { randomUUID } = require('node:crypto');
const { chromium, request } = require('playwright');
const { launchOptions } = require('./browser-executable');
const { pageShowsAuthenticationWall } = require('./auth-wall');

const CHECK_TIMEOUT_MS = 15000;

function parseArgs(argv) {
  const args = { profileDir: '', liveEndpoint: '', checks: null };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--profile-dir':
        args.profileDir = argv[++i];
        break;
      case '--live-endpoint':
        args.liveEndpoint = argv[++i];
        if (!/^ws:\/\/127\.0\.0\.1:\d+\/devtools\/browser\/[0-9a-fA-F-]{36}$/.test(args.liveEndpoint)) {
          throw new Error('--live-endpoint must be the managed loopback browser endpoint.');
        }
        break;
      case '--checks':
        args.checks = JSON.parse(argv[++i]);
        break;
      default:
        throw new Error(`Unknown argument: ${argv[i]}`);
    }
  }
  if (Boolean(args.profileDir) === Boolean(args.liveEndpoint) || !Array.isArray(args.checks)) {
    throw new Error('Specify --profile-dir or --live-endpoint and a --checks JSON array.');
  }
  return args;
}

async function checkStatus(context, check, live) {
  // A live browser's context.request would apply Set-Cookie from the probe
  // to the operator's session. Seed a separate request jar for this URL.
  const client = live
    ? await request.newContext({
      storageState: { cookies: await context.cookies(check.url), origins: [] },
    })
    : context.request;
  try {
    const response = await client.get(check.url, {
      maxRedirects: 0,
      timeout: CHECK_TIMEOUT_MS,
      failOnStatusCode: false,
    });
    const status = response.status();
    return status === check.signed_in_status
      ? { state: 'signed_in', detail: `answered ${status}` }
      : { state: 'expired', detail: `answered ${status}, signed in answers ${check.signed_in_status}` };
  } finally {
    if (live) await client.dispose();
  }
}

async function openProbePage(context, cdp) {
  if (!cdp) {
    const page = await context.newPage();
    return { page, close: () => page.close().catch(() => {}) };
  }
  // A background target leaves the operator's selected tab alone. Identify
  // the newly created page by a URL unique to this probe.
  const url = `about:blank#${randomUUID()}`;
  let targetId;
  const close = async () => {
    if (targetId) await cdp.send('Target.closeTarget', { targetId });
  };
  try {
    const [page] = await Promise.all([
      context.waitForEvent('page', {
        predicate: (candidate) => candidate.url() === url,
        timeout: CHECK_TIMEOUT_MS,
      }),
      cdp.send('Target.createTarget', { url, background: true }).then((target) => {
        targetId = target.targetId;
      }),
    ]);
    return { page, close };
  } catch (error) {
    await close();
    throw error;
  }
}

async function checkSelector(context, check, cdp) {
  const { page, close } = await openProbePage(context, cdp);
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
    await close();
  }
}

/**
 * Check each declared site with an already-open persistent context.
 * Exported so the contract test can drive it without a real profile.
 */
async function checkSites(context, checks, cdp = null) {
  const sites = [];
  for (const check of checks) {
    try {
      const outcome = check.signed_in_status !== undefined
        ? await checkStatus(context, check, Boolean(cdp))
        : await checkSelector(context, check, cdp);
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

async function checkLiveSites(endpoint, checks) {
  const browser = await chromium.connectOverCDP(endpoint, {
    isLocal: true, noDefaults: true, timeout: CHECK_TIMEOUT_MS,
  });
  try {
    const context = browser.contexts()[0];
    const cdp = await browser.newBrowserCDPSession();
    const sites = await checkSites(context, checks, cdp);
    if (!browser.isConnected()) throw new Error('The managed browser disconnected during verification.');
    return sites;
  } finally {
    // For connectOverCDP this disconnects the client. The existing browser
    // and its default context belong to the operator.
    await browser.close();
  }
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.liveEndpoint) {
    console.log(JSON.stringify({ sites: await checkLiveSites(args.liveEndpoint, args.checks) }));
    return;
  }
  const context = await chromium.launchPersistentContext(args.profileDir, {
    ...launchOptions(),
    headless: true,
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

module.exports = { checkSites, checkLiveSites, parseArgs };

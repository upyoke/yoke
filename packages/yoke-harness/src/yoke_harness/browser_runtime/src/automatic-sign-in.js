'use strict';

const fs = require('node:fs');

/** Credentials exist only in this process and the Playwright page.
 * Never return page text, URLs, exception messages, or Playwright call logs.
 */
async function signInSite(context, site, secretFiles, ownedPage) {
  let page = ownedPage;
  try {
    page = page || await context.newPage();
    page.setDefaultTimeout(15000);
    await page.goto(site.sign_in.url, { waitUntil: 'domcontentloaded', timeout: 15000 });
    const appOrigin = new URL(site.origin).origin;
    const credentialOrigins = new Set([appOrigin, ...(site.sign_in.credential_origins || [])]
      .map(origin => new URL(origin).origin));
    for (const step of site.sign_in.steps) {
      if (step.fill) {
        if (!credentialOrigins.has(new URL(page.url()).origin)) {
          return { site: site.site, state: 'failed' };
        }
        let value;
        try {
          value = fs.readFileSync(secretFiles[step.secret], 'utf8').trim();
        } catch (_) {
          return { site: site.site, state: 'secret_missing', field: step.secret };
        }
        if (!value) return { site: site.site, state: 'secret_missing', field: step.secret };
        await page.locator(step.fill).fill(value);
      } else {
        await page.locator(step.click).click();
      }
    }
    await page.waitForURL(url => url.origin === appOrigin, { timeout: 15000 });
    return { site: site.site, state: 'submitted' };
  } catch (_) {
    return { site: site.site, state: 'failed' };
  } finally {
    if (page && !ownedPage) await page.close().catch(() => {});
  }
}

module.exports = { signInSite };

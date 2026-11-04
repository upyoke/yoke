'use strict';

const fs = require('node:fs');
const { chromium } = require('playwright');
const { launchOptions } = require('./browser-executable');
const { checkSites } = require('./verify-sign-in');
const { signInSite } = require('./automatic-sign-in');

async function main() {
  // Both arguments are file paths. The manifest contains declarations and secret
  // paths, never credential values. This context has no tracing or screenshots.
  const [profileDir, manifestPath] = process.argv.slice(2);
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const context = await chromium.launchPersistentContext(profileDir, {
    ...launchOptions(), headless: true,
  });
  try {
    const sites = [];
    for (const entry of manifest.sites) {
      const submitted = await signInSite(context, entry, entry.secret_files);
      const checked = submitted.state === 'submitted'
        ? (await checkSites(context, [entry.probe]))[0] : submitted;
      // A site can echo a password in its URL or error response. Keep only
      // closed-vocabulary states, even when the verification fails.
      sites.push({ site: entry.site, state: checked.state,
        ...(checked.state === 'secret_missing' ? { field: checked.field } : {}) });
    }
    console.log(JSON.stringify({ sites }));
  } finally {
    await context.close();
  }
}

main().catch(() => {
  console.error('browser_automatic_sign_in_failed');
  process.exitCode = 1;
});

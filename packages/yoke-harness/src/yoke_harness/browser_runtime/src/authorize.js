'use strict';

/**
 * Operator sign-in window for one project's persistent browser profile.
 *
 * Usage: node authorize.js --profile-dir path [--url URL]
 *
 * Opens the profile in a headed Chromium window and blocks until the operator
 * closes it. Whatever they sign into is written into the profile, so every
 * worker context the daemon later opens from it is already signed in. This
 * process never types a credential and never navigates on the operator's
 * behalf beyond the optional starting URL.
 */

const { chromium } = require('playwright');

function parseArgs(argv) {
  const args = { profileDir: '', url: '' };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--profile-dir':
        args.profileDir = argv[++i];
        break;
      case '--url':
        args.url = argv[++i];
        break;
      default:
        console.error(`Unknown argument: ${argv[i]}`);
        process.exit(3);
    }
  }
  if (!args.profileDir) {
    console.error('--profile-dir is required.');
    process.exit(3);
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv);
  const context = await chromium.launchPersistentContext(args.profileDir, {
    headless: false,
  });
  const page = context.pages().find((candidate) => !candidate.isClosed())
    || (await context.newPage());
  if (args.url) {
    try {
      await page.goto(args.url, { waitUntil: 'domcontentloaded' });
    } catch (err) {
      // A starting URL is a convenience; the operator can navigate anywhere.
      console.error(`Could not open ${args.url}: ${err.message}`);
    }
  }
  console.log('Sign in to whatever sites you need, then close the window.');
  await new Promise((resolve) => context.on('close', resolve));
  console.log('Window closed. Profile saved.');
}

main().catch((err) => {
  console.error(`Failed to open the sign-in window: ${err.message}`);
  process.exit(1);
});

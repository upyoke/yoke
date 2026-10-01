'use strict';

// Observe both Playwright launch paths without starting an unsandboxed browser.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { createBrowserManager } = require('../src/browser-manager');

async function main() {
  const calls = [];
  const context = { close: async () => {} };
  chromium.launchPersistentContext = async (directory, options) => {
    calls.push({ directory, ...options });
    return context;
  };
  chromium.launch = async (options) => {
    calls.push(options);
    return { newContext: async () => context, close: async () => {} };
  };
  for (const options of [{}, { profileDir: '/profile', headless: false }]) {
    const manager = createBrowserManager(options);
    await manager.launch();
    await manager.closeBrowser();
  }
  assert.deepEqual(calls, [
    { headless: true, chromiumSandbox: true },
    { directory: '/profile', headless: false, chromiumSandbox: true },
  ]);
  console.log('PASS: persistent and throwaway QA browsers require Chromium sandboxing');
}

main().catch(error => { console.error(error); process.exitCode = 1; });

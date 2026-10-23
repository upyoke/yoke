'use strict';

/**
 * Google's account chooser selects the recorded account and never types
 * a credential. A missing account or a page that stays on Google sign-in
 * is browser_sign_in_setup.
 *
 * Run: node tests/google-account-chooser.test.js
 */

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const { executeStep } = require('../src/step-runner');

const CHOOSER = fs.readFileSync(
  path.join(__dirname, 'fixtures', 'google-account-chooser.html'),
  'utf8',
);
const LINGERING = fs.readFileSync(
  path.join(__dirname, 'fixtures', 'google-sign-in-lingering.html'),
  'utf8',
);
const APP = '<!DOCTYPE html><html><body><main id="home">Home</main></body></html>';

let testCount = 0;
let passCount = 0;
let failCount = 0;
let browser;
let context;

function assert(condition, message) {
  testCount++;
  if (condition) {
    passCount++;
    console.log(`  PASS: ${message}`);
  } else {
    failCount++;
    console.log(`  FAIL: ${message}`);
  }
}

function assertEqual(actual, expected, message) {
  testCount++;
  if (actual === expected) {
    passCount++;
    console.log(`  PASS: ${message}`);
  } else {
    failCount++;
    console.log(`  FAIL: ${message} (expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)})`);
  }
}

async function setup() {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
}

async function teardown() {
  if (browser) await browser.close();
}

async function routedPage() {
  const page = await context.newPage();
  await page.route('https://accounts.google.com/**', (route) => {
    const url = route.request().url();
    route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: url.includes('/signin') ? LINGERING : CHOOSER,
    });
  });
  await page.route('https://app.example.test/**', (route) => {
    route.fulfill({ status: 200, contentType: 'text/html', body: APP });
  });
  return page;
}

async function navigate(page, route, account) {
  return executeStep(page, {
    action: 'navigate',
    route,
  }, { baseUrl: 'https://app.example.test', account });
}

async function testMatchingAccountIsSelected() {
  console.log('\n## Test: a matching account is selected');
  const page = await routedPage();
  const result = await navigate(
    page,
    'https://accounts.google.com/AccountChooser',
    'buyer@example.com',
  );
  assertEqual(result.success, true, 'navigate leaves the chooser');
  assertEqual(result.signInPage, false, 'the app page is not a sign-in page');
  assert(page.url().startsWith('https://app.example.test/'), 'the recorded account opens the app');
  assertEqual(await page.locator('#home').textContent(), 'Home', 'the app page loaded');
  await page.close();
}

async function testMissingAccountIsSetupError() {
  console.log('\n## Test: a chooser without the recorded account is a setup error');
  const page = await routedPage();
  const result = await navigate(
    page,
    'https://accounts.google.com/AccountChooser',
    'other@example.com',
  );
  assertEqual(result.success, false, 'the step does not succeed');
  assertEqual(result.signInSetup, true, 'the failure is a sign-in setup error');
  assert(
    String(result.error).includes('browser_sign_in_setup'),
    'the error names browser_sign_in_setup',
  );
  assert(
    String(result.error).includes('other@example.com'),
    'the error names the account that was not offered',
  );
  assertEqual(await page.locator('#password').inputValue(), '', 'no credential was entered');
  await page.close();
}

async function testUnrecordedAccountIsSetupError() {
  console.log('\n## Test: a chooser with no recorded account is a setup error');
  const page = await routedPage();
  const result = await navigate(page, 'https://accounts.google.com/AccountChooser', '');
  assertEqual(result.success, false, 'the step does not succeed');
  assert(
    String(result.error).includes('records no Google account'),
    'the error says the identity records no Google account',
  );
  assertEqual(await page.locator('#password').inputValue(), '', 'no credential was entered');
  await page.close();
}

async function testLingeringGoogleSignInIsSetupError() {
  console.log('\n## Test: a lingering Google sign-in page is a setup error');
  const page = await routedPage();
  const result = await navigate(
    page,
    'https://accounts.google.com/signin/v2',
    'buyer@example.com',
  );
  assertEqual(result.success, false, 'the step does not succeed');
  assert(
    String(result.error).includes('still showing'),
    'the error says a Google sign-in page is still showing',
  );
  assertEqual(await page.locator('#password').inputValue(), '', 'no credential was entered');
  assertEqual(result.signInPage, true, 'the page is still a sign-in page');
  await page.close();
}

async function run() {
  console.log('=== Google account chooser ===');
  await setup();
  try {
    await testMatchingAccountIsSelected();
    await testMissingAccountIsSetupError();
    await testUnrecordedAccountIsSetupError();
    await testLingeringGoogleSignInIsSetupError();
  } catch (err) {
    console.error('\nUnexpected error:', err);
    failCount++;
  } finally {
    await teardown();
  }
  console.log(`\n=== Results: ${passCount}/${testCount} passed, ${failCount} failed ===`);
  if (failCount > 0) process.exit(1);
}

run();

'use strict';

/**
 * Authentication-wall detection on wait_for / assert timeout, without
 * failing a navigate that lands on Sign in (login-form cases start there).
 *
 * Run: node tests/auth-wall.test.js
 */

const path = require('path');
const { chromium } = require('playwright');
const { executeStep } = require('../src/step-runner');

let testCount = 0;
let passCount = 0;
let failCount = 0;

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

let browser;
let context;

function fixtureUrl(name) {
  return `file://${path.join(__dirname, 'fixtures', name)}`;
}

function baseUrl() {
  return `file://${path.join(__dirname, 'fixtures')}`;
}

async function setup() {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
}

async function teardown() {
  if (browser) await browser.close();
}

async function testWaitForTimeoutOnSignInPageIsUnauthorized() {
  console.log('\n## Test: wait_for timeout on a Sign in page is unauthorized');
  const page = await context.newPage();
  await page.goto(fixtureUrl('sign-in-page.html'), { waitUntil: 'domcontentloaded' });

  const result = await executeStep(page, {
    action: 'wait_for',
    target: '.shipping-run-grid',
    timeout_ms: 200,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'wait_for on a missing grid fails');
  assertEqual(result.authenticationWall, true, 'step reports an authentication wall');
  assert(
    String(result.error).includes('execution_target_unauthorized'),
    'error names execution_target_unauthorized, not a selector timeout',
  );

  await page.close();
}

async function testWaitForTimeoutWithoutSignInStaysTimeout() {
  console.log('\n## Test: wait_for timeout without Sign in stays a timeout');
  const page = await context.newPage();
  await page.goto(fixtureUrl('test-page.html'), { waitUntil: 'domcontentloaded' });

  const result = await executeStep(page, {
    action: 'wait_for',
    target: '#non-existent',
    timeout_ms: 200,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'wait_for on a missing element fails');
  assertEqual(result.authenticationWall, undefined, 'no authentication wall on an ordinary page');
  assert(
    /timeout/i.test(String(result.error)),
    'error remains the selector timeout',
  );
  assert(
    !String(result.error).includes('execution_target_unauthorized'),
    'ordinary timeout is not classified unauthorized',
  );

  await page.close();
}

async function testNavigateOntoSignInSucceeds() {
  console.log('\n## Test: navigate onto Sign in succeeds and reports the wall');
  const page = await context.newPage();

  const result = await executeStep(page, {
    action: 'navigate',
    route: 'sign-in-page.html',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'navigate onto a Sign in page succeeds');
  assertEqual(result.authenticationWall, true, 'navigate reports the authentication wall');

  await page.close();
}

async function testWaitForSignInLinkSucceeds() {
  console.log('\n## Test: wait_for the Sign in control succeeds on that page');
  const page = await context.newPage();
  await page.goto(fixtureUrl('sign-in-page.html'), { waitUntil: 'domcontentloaded' });

  const result = await executeStep(page, {
    action: 'wait_for',
    target: 'a',
    timeout_ms: 1000,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'wait_for a visible Sign in link succeeds');
  assertEqual(result.authenticationWall, true, 'successful wait_for still reports the wall');

  await page.close();
}

async function run() {
  console.log('=== Authentication wall ===');
  await setup();
  try {
    await testWaitForTimeoutOnSignInPageIsUnauthorized();
    await testWaitForTimeoutWithoutSignInStaysTimeout();
    await testNavigateOntoSignInSucceeds();
    await testWaitForSignInLinkSucceeds();
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

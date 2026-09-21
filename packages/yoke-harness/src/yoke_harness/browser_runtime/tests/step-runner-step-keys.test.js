'use strict';

/**
 * Tests for refusing keys a browser step kind does not define.
 *
 * Run: node tests/step-runner-step-keys.test.js
 */

const fs = require('fs');
const os = require('os');
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
    console.log(
      `  FAIL: ${message} (expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)})`
    );
  }
}

let browser;
let context;

function baseUrl() {
  return `file://${path.join(__dirname, 'fixtures')}`;
}

function fixtureUrl() {
  return `file://${path.join(__dirname, 'fixtures', 'test-page.html')}`;
}

async function testNavigateTargetDoesNotFallThroughToBaseUrl() {
  console.log('\n## Test: navigate with target instead of route is refused');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });
  const before = page.url();

  const result = await executeStep(page, {
    action: 'navigate',
    target: '/should-not-open',
  }, { baseUrl: 'https://example.com' });

  assertEqual(result.success, false, 'misplaced target on navigate fails');
  assert(
    /does not honour key "target"/.test(result.error || ''),
    'error names the unrecognised key'
  );
  assert(
    /Defined keys: .*route/.test(result.error || ''),
    'error names the keys navigate defines'
  );
  assertEqual(page.url(), before, 'the page did not navigate to the base URL');
  await page.close();
}

async function testEmptyNavigateRouteIsRefused() {
  console.log('\n## Test: navigate without a route is refused');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });
  const before = page.url();

  const result = await executeStep(page, {
    action: 'navigate',
  }, { baseUrl: 'https://example.com' });

  assertEqual(result.success, false, 'navigate without route fails');
  assert(
    /requires a non-empty route/.test(result.error || ''),
    'error names the missing route'
  );
  assertEqual(page.url(), before, 'the page did not fall through to the base URL');
  await page.close();
}

async function testAssertDoesNotAcceptRoute() {
  console.log('\n## Test: assert with a misplaced route is refused');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await executeStep(page, {
    action: 'assert',
    route: '/',
    target: 'button',
    check: 'visible',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'misplaced route on assert fails');
  assert(
    /does not honour key "route"/.test(result.error || ''),
    'error names the unrecognised key'
  );
  await page.close();
}

async function testScreenshotHonoursLabel() {
  console.log('\n## Test: screenshot honours label');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });
  const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yoke-step-keys-'));

  const result = await executeStep(page, {
    action: 'screenshot',
    capture: true,
    label: 'home',
  }, { baseUrl: baseUrl(), outputDir });

  assertEqual(result.success, true, 'screenshot with label succeeds');
  assert(
    Array.isArray(result.artifacts) && result.artifacts.length === 1,
    'one artifact produced'
  );
  assert(
    /screenshot-home-\d+\.png$/.test(result.artifacts[0] || ''),
    'artifact filename includes the label'
  );
  await page.close();
}

async function testDelayDoesNotAcceptMs() {
  console.log('\n## Test: delay with ms instead of duration is refused');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await executeStep(page, {
    action: 'delay',
    ms: 1,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'undefined ms key on delay fails');
  assert(
    /does not honour key "ms"/.test(result.error || ''),
    'error names the unrecognised key'
  );
  assert(
    /Defined keys: .*duration/.test(result.error || ''),
    'error names duration as the defined wait field'
  );
  await page.close();
}

async function run() {
  console.log('=== Step Runner Tests: Step Keys ===');
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
  try {
    await testNavigateTargetDoesNotFallThroughToBaseUrl();
    await testEmptyNavigateRouteIsRefused();
    await testAssertDoesNotAcceptRoute();
    await testScreenshotHonoursLabel();
    await testDelayDoesNotAcceptMs();
  } catch (err) {
    console.error('\nUnexpected error:', err);
    failCount++;
  } finally {
    if (browser) await browser.close();
  }
  console.log(`\n=== Results: ${passCount}/${testCount} passed, ${failCount} failed ===`);
  if (failCount > 0) process.exit(1);
}

run();

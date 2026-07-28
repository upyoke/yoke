'use strict';

/**
 * Tests for the scenario step executor — basic actions.
 *
 * Run: node tests/step-executor.test.js
 *
 * Covers: resolveUrl, navigate, click, fill_form, wait_for, hover, select.
 * Companion files cover assertion checks, body-target text semantics,
 * screenshot/timeout/errors/delay, and stale-schema rejection.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');
const { executeStep, resolveUrl } = require('../src/step-executor');

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
let tmpDir;

async function setup() {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'step-exec-test-'));
}

async function teardown() {
  if (browser) await browser.close();
  try {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  } catch (_) {
    // Ignore cleanup errors
  }
}

function fixtureUrl() {
  const fixturePath = path.join(__dirname, 'fixtures', 'test-page.html');
  return `file://${fixturePath}`;
}

function baseUrl() {
  const fixturesDir = path.join(__dirname, 'fixtures');
  return `file://${fixturesDir}`;
}

async function testResolveUrl() {
  console.log('\n## Test: resolveUrl handles relative and absolute routes');

  // AC-8: Relative route gets baseUrl prepended
  assertEqual(
    resolveUrl('/home', 'http://localhost:3000'),
    'http://localhost:3000/home',
    'Relative route with leading slash gets base URL prepended'
  );

  assertEqual(
    resolveUrl('about', 'http://localhost:3000'),
    'http://localhost:3000/about',
    'Relative route without leading slash gets base URL prepended with slash'
  );

  // AC-8: Absolute URLs pass through
  assertEqual(
    resolveUrl('https://example.com/page', 'http://localhost:3000'),
    'https://example.com/page',
    'Absolute https URL passes through'
  );

  assertEqual(
    resolveUrl('http://example.com/page', 'http://localhost:3000'),
    'http://example.com/page',
    'Absolute http URL passes through'
  );

  // Trailing slash on base URL
  assertEqual(
    resolveUrl('/test', 'http://localhost:3000/'),
    'http://localhost:3000/test',
    'Trailing slash on base URL is normalized'
  );

  // Empty route returns base URL
  assertEqual(
    resolveUrl('', 'http://localhost:3000'),
    'http://localhost:3000',
    'Empty route returns base URL'
  );
}

async function testNavigateAction() {
  console.log('\n## Test: navigate action');
  const page = await context.newPage();

  // AC-2: navigate calls page.goto with the resolved URL
  const result = await executeStep(page, {
    route: '/test-page.html',
    action: 'navigate',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'navigate succeeds');
  assert(typeof result.duration_ms === 'number', 'duration_ms is a number');
  assert(result.duration_ms >= 0, 'duration_ms is non-negative');

  // Verify we actually navigated
  assert(page.url().includes('test-page.html'), 'page URL contains test-page.html');

  await page.close();
}

async function testClickAction() {
  console.log('\n## Test: click action');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // AC-3: click resolves target and clicks
  const result = await executeStep(page, {
    route: '',
    action: 'click',
    target: 'button',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'click on button succeeds');
  assert(typeof result.duration_ms === 'number', 'duration_ms is a number');

  await page.close();
}

async function testClickNonExistentTarget() {
  console.log('\n## Test: click on non-existent target fails');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // AC-10: Failed steps return error
  const result = await executeStep(page, {
    route: '',
    action: 'click',
    target: '#does-not-exist',
    timeout_ms: 500,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'click on non-existent target fails');
  assert(typeof result.error === 'string' && result.error.length > 0, 'error message is descriptive');
  assert(typeof result.duration_ms === 'number', 'duration_ms is a number');

  await page.close();
}

async function testFillFormAction() {
  console.log('\n## Test: fill_form action');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // AC-4: fill_form iterates fields and fills each
  const result = await executeStep(page, {
    route: '',
    action: 'fill_form',
    fields: {
      '[data-testid="email"]': 'test@example.com',
      '#search-input': 'hello world',
    },
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'fill_form succeeds');

  // Verify values were actually set
  const emailVal = await page.locator('[data-testid="email"]').inputValue();
  assertEqual(emailVal, 'test@example.com', 'email field was filled');

  const searchVal = await page.locator('#search-input').inputValue();
  assertEqual(searchVal, 'hello world', 'search field was filled');

  await page.close();
}

async function testWaitForVisible() {
  console.log('\n## Test: wait_for action succeeds for visible element');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // AC-5: wait_for waits for target to be visible
  const result = await executeStep(page, {
    route: '',
    action: 'wait_for',
    target: 'button',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'wait_for visible element succeeds');

  await page.close();
}

async function testWaitForTimeout() {
  console.log('\n## Test: wait_for times out for hidden element');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // AC-10: Timeout returns error
  const result = await executeStep(page, {
    route: '',
    action: 'wait_for',
    target: '#non-existent-element',
    timeout_ms: 500,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'wait_for non-existent element fails');
  assert(typeof result.error === 'string', 'error message is present');

  await page.close();
}

async function testHoverAction() {
  console.log('\n## Test: hover action');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await executeStep(page, {
    route: '',
    action: 'hover',
    target: 'button',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'hover action succeeds');

  await page.close();
}

async function testSelectAction() {
  console.log('\n## Test: select action');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await executeStep(page, {
    route: '',
    action: 'select',
    target: 'select[aria-label="Choose a color"]',
    value: 'Blue',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'select action succeeds');

  // Verify selection was made
  const selected = await page.locator('select[aria-label="Choose a color"]').inputValue();
  assertEqual(selected, 'Blue', 'select option was set to Blue');

  await page.close();
}

async function run() {
  console.log('=== Step Executor Tests: Basics ===');
  await setup();
  try {
    await testResolveUrl();
    await testNavigateAction();
    await testClickAction();
    await testClickNonExistentTarget();
    await testFillFormAction();
    await testWaitForVisible();
    await testWaitForTimeout();
    await testHoverAction();
    await testSelectAction();
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

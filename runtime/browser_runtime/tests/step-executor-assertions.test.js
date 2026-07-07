'use strict';

/**
 * Tests for the scenario step executor — assert action checks.
 *
 * Run: node tests/step-executor-assertions.test.js
 *
 * Covers: assert with check ∈ {visible, hidden, text_contains, count_gte}
 * for non-body targets. Body-target visible-text + hydration semantics
 * live in ``step-executor-body-text.test.js``.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');
const { executeStep } = require('../src/step-executor');

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

async function testAssertVisible() {
  console.log('\n## Test: assert visible check');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // AC-6: assert visible
  const result = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'button',
    check: 'visible',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'assert visible on visible element succeeds');

  await page.close();
}

async function testAssertHidden() {
  console.log('\n## Test: assert hidden check');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // AC-6: assert hidden on non-existent element
  const result = await executeStep(page, {
    route: '',
    action: 'assert',
    target: '#hidden-element',
    check: 'hidden',
    timeout_ms: 1000,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'assert hidden on non-existent element succeeds');

  await page.close();
}

async function testAssertTextContains() {
  console.log('\n## Test: assert text_contains check');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // AC-6: text_contains with matching text
  const result = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'h1',
    check: 'text_contains',
    expected: 'Test Page',
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'assert text_contains with matching text succeeds');

  // Case-insensitive matching.
  const resultCI = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'h1',
    check: 'text_contains',
    expected: 'test page',
  }, { baseUrl: baseUrl() });

  assertEqual(resultCI.success, true, 'assert text_contains with lowercase expected matches uppercase page text');

  await page.setContent('<!doctype html><html><body><h1>EVERYBODY POOPS</h1></body></html>');

  // Seeded keyword scenario: lowercase expected text against uppercase page text.
  const resultCI2 = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'h1',
    check: 'text_contains',
    expected: 'poop',
  }, { baseUrl: baseUrl() });

  assertEqual(resultCI2.success, true, 'assert text_contains matches seeded lowercase keyword against uppercase page text');

  // text_contains with non-matching text
  const result2 = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'h1',
    check: 'text_contains',
    expected: 'Not Found Text',
  }, { baseUrl: baseUrl() });

  assertEqual(result2.success, false, 'assert text_contains with non-matching text fails');
  assert(result2.error.includes('Expected text to contain'), 'error message describes the mismatch');

  await page.close();
}

async function testAssertCountGte() {
  console.log('\n## Test: assert count_gte check');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // AC-6: count_gte with known element count (at least 2 links in nav)
  const result = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'nav a',
    check: 'count_gte',
    min_count: 2,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'assert count_gte succeeds when count is sufficient');

  // count_gte with too-high threshold
  const result2 = await executeStep(page, {
    route: '',
    action: 'assert',
    target: 'nav a',
    check: 'count_gte',
    min_count: 100,
  }, { baseUrl: baseUrl() });

  assertEqual(result2.success, false, 'assert count_gte fails when count is too low');
  assert(result2.error.includes('Expected at least'), 'error message describes count mismatch');

  await page.close();
}

async function run() {
  console.log('=== Step Executor Tests: Assertions ===');
  await setup();
  try {
    await testAssertVisible();
    await testAssertHidden();
    await testAssertTextContains();
    await testAssertCountGte();
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

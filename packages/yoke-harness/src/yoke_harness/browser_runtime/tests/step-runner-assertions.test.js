'use strict';

/**
 * Tests for the scenario step runner — assert action checks.
 *
 * Run: node tests/step-runner-assertions.test.js
 *
 * Covers: assert with check ∈ {visible, hidden, text_contains, count_gte,
 * count_eq} for non-body targets, and the match count an absence-shaped
 * check reports about itself. Body-target visible-text + hydration
 * semantics live in ``step-runner-body-text.test.js``.
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

  // At least 2 links in the fixture's nav.
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

async function testAbsenceMatchCount() {
  console.log('\n## Test: absence-shaped checks report what they matched');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // Nothing on the page is a #hidden-element, so this assertion could not
  // have failed: Playwright reports a detached locator as hidden.
  const detached = await executeStep(page, {
    route: '',
    action: 'assert',
    target: '#hidden-element',
    check: 'hidden',
    timeout_ms: 1000,
  }, { baseUrl: baseUrl() });

  assertEqual(detached.success, true, 'hidden on a detached locator still succeeds');
  assertEqual(
    detached.vacuous_absence && detached.vacuous_absence.matched_elements,
    0,
    'hidden on a detached locator reports matching zero elements',
  );
  assertEqual(
    detached.vacuous_absence && detached.vacuous_absence.target,
    '#hidden-element',
    'the report names the locator that matched nothing',
  );

  // The element is on the page and genuinely hidden, so the same check is a
  // real observation and carries no report.
  await page.setContent(
    '<!doctype html><html><body><p id="banner" style="display:none">Hi</p>'
    + '<p class="card">One</p><p class="card">Two</p></body></html>'
  );
  const present = await executeStep(page, {
    route: '',
    action: 'assert',
    target: '#banner',
    check: 'hidden',
    timeout_ms: 1000,
  }, { baseUrl: baseUrl() });

  assertEqual(present.success, true, 'hidden on a present hidden element succeeds');
  assertEqual(
    present.vacuous_absence,
    undefined,
    'hidden on a present element reports nothing vacuous',
  );

  const countZero = await executeStep(page, {
    route: '',
    action: 'assert',
    target: '.absent-card',
    check: 'count_eq',
    expected: 0,
  }, { baseUrl: baseUrl() });

  assertEqual(countZero.success, true, 'count_eq 0 on a zero-match locator succeeds');
  assertEqual(
    countZero.vacuous_absence && countZero.vacuous_absence.check,
    'count_eq',
    'count_eq 0 reports itself as an absence that matched nothing',
  );

  const countTwo = await executeStep(page, {
    route: '',
    action: 'assert',
    target: '.card',
    check: 'count_eq',
    expected: 2,
  }, { baseUrl: baseUrl() });

  assertEqual(
    countTwo.vacuous_absence,
    undefined,
    'a count check that matched elements reports nothing vacuous',
  );

  await page.close();
}

async function run() {
  console.log('=== Step Runner Tests: Assertions ===');
  await setup();
  try {
    await testAssertVisible();
    await testAssertHidden();
    await testAssertTextContains();
    await testAssertCountGte();
    await testAbsenceMatchCount();
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

'use strict';

/**
 * Tests that presence questions answer for a selector matching many
 * elements, while checks reading a value stay strict.
 *
 * Run: node tests/step-runner-presence.test.js
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

async function openCards(page) {
  await page.goto(`${baseUrl()}/repeated-cards.html`);
  const matched = await page.locator('.card').count();
  assert(matched > 1, `fixture holds ${matched} matching cards, more than one`);
}

async function testWaitForAcceptsManyMatches() {
  console.log('\n## Test: wait_for resolves a selector matching many elements');
  const page = await context.newPage();
  await openCards(page);

  const result = await executeStep(page, {
    action: 'wait_for',
    target: '.card',
    timeout_ms: 2000,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'wait_for succeeds on a 6-match selector');
  assertEqual(result.error, undefined, 'wait_for reports no strict-mode error');
  await page.close();
}

async function testVisibleAcceptsManyMatches() {
  console.log('\n## Test: assert visible resolves many matches');
  const page = await context.newPage();
  await openCards(page);

  const result = await executeStep(page, {
    action: 'assert',
    target: '.card',
    check: 'visible',
    timeout_ms: 2000,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'visible succeeds on a 6-match selector');
  await page.close();
}

async function testVisibleStillFailsWhenAbsent() {
  console.log('\n## Test: assert visible still fails for an absent target');
  const page = await context.newPage();
  await openCards(page);

  const result = await executeStep(page, {
    action: 'assert',
    target: '.no-such-card',
    check: 'visible',
    timeout_ms: 500,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'visible fails when nothing matches');
  await page.close();
}

async function testHiddenKeepsUnnarrowedCount() {
  console.log('\n## Test: assert hidden counts every match, not just the first');
  const page = await context.newPage();
  await openCards(page);

  // Absent target: the count decides this observed nothing, and a
  // first-match locator could only ever answer zero or one.
  const absent = await executeStep(page, {
    action: 'assert',
    target: '.no-such-card',
    check: 'hidden',
    timeout_ms: 500,
  }, { baseUrl: baseUrl() });

  assertEqual(absent.success, true, 'hidden passes for an absent target');
  assert(
    absent.vacuous_absence !== undefined,
    'hidden on an absent target reports vacuous_absence'
  );
  assertEqual(
    absent.vacuous_absence.matched_elements,
    0,
    'vacuous_absence records zero matched elements'
  );

  const present = await executeStep(page, {
    action: 'assert',
    target: '#placeholder',
    check: 'hidden',
    timeout_ms: 500,
  }, { baseUrl: baseUrl() });

  assertEqual(
    present.success,
    false,
    'hidden fails while a matching element is still visible'
  );
  await page.close();
}

async function testTextChecksStayStrict() {
  console.log('\n## Test: text_equals stays strict on an ambiguous target');
  const page = await context.newPage();
  await openCards(page);

  const result = await executeStep(page, {
    action: 'assert',
    target: '.card',
    check: 'text_equals',
    expected: 'card one',
    timeout_ms: 1000,
  }, { baseUrl: baseUrl() });

  assertEqual(
    result.success,
    false,
    'text_equals refuses a selector matching many elements'
  );
  assert(
    /strict mode/i.test(String(result.error)),
    `text_equals names strict mode in its error (got ${JSON.stringify(result.error)})`
  );
  await page.close();
}

async function run() {
  console.log('=== Step Runner Tests: Presence ===');
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
  try {
    await testWaitForAcceptsManyMatches();
    await testVisibleAcceptsManyMatches();
    await testVisibleStillFailsWhenAbsent();
    await testHiddenKeepsUnnarrowedCount();
    await testTextChecksStayStrict();
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

'use strict';

/**
 * Tests that count assertions honour timeout_ms by polling.
 *
 * Run: node tests/step-runner-count-wait.test.js
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

async function paintCardsAfter(page, delayMs) {
  await page.setContent(
    '<!doctype html><html><body><div id="host"></div></body></html>'
  );
  await page.evaluate((ms) => {
    setTimeout(() => {
      document.getElementById('host').innerHTML =
        '<p class="card">one</p><p class="card">two</p>';
    }, ms);
  }, delayMs);
}

async function testCountGteWaitsForLatePaint() {
  console.log('\n## Test: count_gte waits until the locator matches');
  const page = await context.newPage();
  await paintCardsAfter(page, 300);

  const result = await executeStep(page, {
    action: 'assert',
    target: '.card',
    check: 'count_gte',
    min_count: 1,
    timeout_ms: 2000,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'count_gte succeeds after the cards paint');
  await page.close();
}

async function testCountGteTimesOutWhenNothingPaints() {
  console.log('\n## Test: count_gte honours a short timeout_ms');
  const page = await context.newPage();
  await page.setContent(
    '<!doctype html><html><body><div id="host"></div></body></html>'
  );

  const start = Date.now();
  const result = await executeStep(page, {
    action: 'assert',
    target: '.card',
    check: 'count_gte',
    min_count: 1,
    timeout_ms: 200,
  }, { baseUrl: baseUrl() });
  const elapsed = Date.now() - start;

  assertEqual(result.success, false, 'count_gte fails when nothing appears');
  assert(
    /Expected at least 1 elements, found 0/.test(result.error || ''),
    'error reports the count it observed'
  );
  assert(elapsed >= 150, `waited for timeout_ms (elapsed ${elapsed}ms)`);
  assert(elapsed < 1500, `did not hang past the budget (elapsed ${elapsed}ms)`);
  await page.close();
}

async function testCountEqWaitsForExactCount() {
  console.log('\n## Test: count_eq waits until the count holds');
  const page = await context.newPage();
  await paintCardsAfter(page, 300);

  const result = await executeStep(page, {
    action: 'assert',
    target: '.card',
    check: 'count_eq',
    expected: 2,
    timeout_ms: 2000,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'count_eq succeeds after both cards paint');
  await page.close();
}

async function run() {
  console.log('=== Step Runner Tests: Count Wait ===');
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
  try {
    await testCountGteWaitsForLatePaint();
    await testCountGteTimesOutWhenNothingPaints();
    await testCountEqWaitsForExactCount();
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

'use strict';

/**
 * Tests the ready action: waiting for a loading placeholder to leave, by
 * selector, by the text it shows, or both.
 *
 * Run: node tests/step-runner-ready.test.js
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

async function openCards(page, settleMs) {
  const query = settleMs ? `?settle_ms=${settleMs}` : '';
  await page.goto(`${baseUrl()}/repeated-cards.html${query}`);
}

async function testReadyWaitsOutSelector() {
  console.log('\n## Test: ready waits for a loading selector to go away');
  const page = await context.newPage();
  await openCards(page, 400);

  const result = await executeStep(page, {
    action: 'ready',
    target: '#placeholder',
    timeout_ms: 3000,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'ready succeeds once the placeholder hides');
  const stillShowing = await page.locator('#placeholder').isVisible();
  assertEqual(stillShowing, false, 'the placeholder is gone when ready returns');
  await page.close();
}

async function testReadyWaitsOutText() {
  console.log('\n## Test: ready waits for placeholder text to go away');
  const page = await context.newPage();
  await openCards(page, 400);

  const result = await executeStep(page, {
    action: 'ready',
    text: 'Loading evidence',
    timeout_ms: 3000,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'ready succeeds once the text disappears');
  const visibleText = await page.evaluate(() => document.body.innerText);
  assert(
    !visibleText.includes('Loading evidence'),
    'the loading text is gone when ready returns'
  );
  await page.close();
}

async function testReadyTimesOutWhileStillLoading() {
  console.log('\n## Test: ready fails while the page is still loading');
  const page = await context.newPage();
  await openCards(page);

  const result = await executeStep(page, {
    action: 'ready',
    text: 'Loading',
    timeout_ms: 500,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'ready fails when the text never leaves');
  assert(
    /still shows/i.test(String(result.error)),
    `the refusal says the page is still loading (got ${JSON.stringify(result.error)})`
  );
  await page.close();
}

async function testReadyRefusesEmptyStep() {
  console.log('\n## Test: ready refuses a step naming no loading indicator');
  const page = await context.newPage();
  await openCards(page);

  const result = await executeStep(page, {
    action: 'ready',
    timeout_ms: 500,
  }, { baseUrl: baseUrl() });

  assertEqual(
    result.success,
    false,
    'ready with neither target nor text is refused, not passed'
  );
  assert(
    /requires target, text, or both/i.test(String(result.error)),
    `the refusal names what the step needs (got ${JSON.stringify(result.error)})`
  );
  await page.close();
}

async function testReadyAcceptsManyMatches() {
  console.log('\n## Test: ready resolves a selector matching many elements');
  const page = await context.newPage();
  await openCards(page);

  // A repeated loading skeleton is the ordinary shape of this selector, so
  // presence resolution has to hold here as it does for wait_for.
  await page.evaluate(() => {
    const host = document.getElementById('scroller');
    for (let index = 0; index < 3; index += 1) {
      const skeleton = document.createElement('div');
      skeleton.className = 'skeleton';
      skeleton.textContent = 'shimmer';
      host.appendChild(skeleton);
    }
    setTimeout(() => {
      document.querySelectorAll('.skeleton').forEach((node) => node.remove());
    }, 300);
  });

  const result = await executeStep(page, {
    action: 'ready',
    target: '.skeleton',
    timeout_ms: 3000,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'ready succeeds on a 3-match selector');
  await page.close();
}

async function run() {
  console.log('=== Step Runner Tests: Ready ===');
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
  try {
    await testReadyWaitsOutSelector();
    await testReadyWaitsOutText();
    await testReadyTimesOutWhileStillLoading();
    await testReadyRefusesEmptyStep();
    await testReadyAcceptsManyMatches();
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

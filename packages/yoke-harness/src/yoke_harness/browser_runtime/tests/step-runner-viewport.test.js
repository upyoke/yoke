'use strict';

/**
 * Tests for the viewport a step states.
 *
 * Responsive behaviour is only provable by resizing the real viewport —
 * constraining an element inside a wide window proves the element, not the
 * product. A step therefore says the width it is about, the width is applied
 * before the step runs so its assertions and its capture both see it, and it
 * stays applied so a case reads as a walk down the widths.
 *
 * Run: node tests/step-runner-viewport.test.js
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

function baseUrl() {
  return `file://${path.join(__dirname, 'fixtures')}`;
}

function fixtureUrl() {
  return `file://${path.join(__dirname, 'fixtures', 'test-page.html')}`;
}

async function testStepResizesBeforeItRuns() {
  console.log('\n## Test: a step is measured at the width it states');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await executeStep(page, {
    route: '',
    action: 'delay',
    ms: 1,
    viewport: { width: 375, height: 812 },
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, true, 'a step carrying a viewport succeeds');
  assertEqual(page.viewportSize().width, 375, 'the viewport is the stated width');
  assertEqual(page.viewportSize().height, 812, 'the viewport is the stated height');

  // It stays set: the steps that follow are about the same width until one
  // of them says otherwise.
  const next = await executeStep(page, {
    route: '', action: 'delay', ms: 1,
  }, { baseUrl: baseUrl() });
  assertEqual(next.success, true, 'the following step succeeds');
  assertEqual(page.viewportSize().width, 375, 'the width holds for later steps');

  const wide = await executeStep(page, {
    route: '', action: 'delay', ms: 1, viewport: { width: 1440, height: 900 },
  }, { baseUrl: baseUrl() });
  assertEqual(wide.success, true, 'a later width is taken');
  assertEqual(page.viewportSize().width, 1440, 'the later width is applied');
  await page.close();
}

async function testMalformedViewportIsNamed() {
  console.log('\n## Test: a malformed viewport refuses by name');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await executeStep(page, {
    route: '', action: 'delay', ms: 1, viewport: { width: '375' },
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'a viewport without numbers fails');
  assert(
    /step\.viewport needs numeric width and height/.test(result.error || ''),
    'the failure names the field and what it needs',
  );
  await page.close();
}

async function main() {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
  try {
    await testStepResizesBeforeItRuns();
    await testMalformedViewportIsNamed();
  } finally {
    if (browser) await browser.close();
  }
  console.log(`\n${passCount}/${testCount} passed, ${failCount} failed`);
  process.exit(failCount > 0 ? 1 : 0);
}

main();

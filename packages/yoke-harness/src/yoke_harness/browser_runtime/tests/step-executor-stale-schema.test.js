'use strict';

/**
 * Tests for the scenario step executor — stale-schema rejection.
 *
 * Run: node tests/step-executor-stale-schema.test.js
 *
 * Covers stale-schema rejection: legacy ``action: "wait"``, legacy ``url``
 * field on navigate, legacy ``selector`` field on click, and the
 * canonical-alongside-legacy rejection path.
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

async function testLegacyWaitActionRejected() {
  console.log('\n## Test: legacy "wait" action is rejected with clear error');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // The removed "wait" action should produce a validation error.
  const result = await executeStep(page, {
    action: 'wait',
    duration: 500,
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'legacy wait action is rejected');
  assert(result.error.includes('Stale browser scenario schema'), 'error mentions stale schema');
  assert(result.error.includes('"action":"wait"'), 'error identifies the legacy field');
  assert(result.error.includes('canonical vocabulary'), 'error points to canonical vocabulary');

  await page.close();
}

async function testStaleUrlFieldRejected() {
  console.log('\n## Test: legacy "url" field is rejected with clear error');
  const page = await context.newPage();

  const result = await executeStep(page, {
    action: 'navigate',
    url: '/test-page.html',  // legacy field — should be "route"
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'navigate with legacy "url" field is rejected');
  assert(result.error.includes('Stale browser scenario schema'), 'error mentions stale schema');
  assert(result.error.includes('"url"'), 'error identifies the legacy field');

  await page.close();
}

async function testStaleSelectorFieldRejected() {
  console.log('\n## Test: legacy "selector" field is rejected with clear error');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await executeStep(page, {
    action: 'click',
    selector: 'button',  // legacy field — should be "target"
  }, { baseUrl: baseUrl() });

  assertEqual(result.success, false, 'click with legacy "selector" field is rejected');
  assert(result.error.includes('Stale browser scenario schema'), 'error mentions stale schema');
  assert(result.error.includes('"selector"'), 'error identifies the legacy field');

  await page.close();
}

async function testLegacyFieldsRejectedEvenAlongsideCanonical() {
  console.log('\n## Test: legacy fields are rejected even when canonical fields are also present');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const navigateResult = await executeStep(page, {
    action: 'navigate',
    route: '/test-page.html',
    url: '/should-be-ignored.html',
  }, { baseUrl: baseUrl() });

  assertEqual(navigateResult.success, false, 'navigate is rejected when legacy "url" is present alongside "route"');
  assert(navigateResult.error.includes('"url"'), 'error identifies the legacy "url" field');

  const clickResult = await executeStep(page, {
    action: 'click',
    target: 'button',
    selector: 'button',
  }, { baseUrl: baseUrl() });

  assertEqual(clickResult.success, false, 'click is rejected when legacy "selector" is present alongside "target"');
  assert(clickResult.error.includes('"selector"'), 'error identifies the legacy "selector" field');

  await page.close();
}

async function run() {
  console.log('=== Step Executor Tests: Stale Schema Rejection ===');
  await setup();
  try {
    await testLegacyWaitActionRejected();
    await testStaleUrlFieldRejected();
    await testStaleSelectorFieldRejected();
    await testLegacyFieldsRejectedEvenAlongsideCanonical();
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

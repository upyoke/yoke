'use strict';

/**
 * Tests for accessibility snapshot and ref system.
 *
 * Run: node tests/snapshot.test.js
 *
 * Tests use a local HTML fixture and real Playwright browser instance.
 */

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const { accessibilitySnapshot, buildRefMap } = require('../src/snapshot');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Test context -- shared browser, fixture page
// ---------------------------------------------------------------------------

let browser;
let context;

async function setup() {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext();
}

async function teardown() {
  if (browser) await browser.close();
}

function fixtureUrl() {
  const fixturePath = path.join(__dirname, 'fixtures', 'test-page.html');
  return `file://${fixturePath}`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

async function testOutputJsonShape() {
  console.log('\n## Test: Output JSON shape matches contract');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await accessibilitySnapshot(page);

  assert(Array.isArray(result.tree), 'tree is an array');
  assert(typeof result.refs === 'object' && result.refs !== null, 'refs is an object');
  assert(typeof result.url === 'string', 'url is a string');
  assert(typeof result.timestamp === 'string', 'timestamp is a string');
  // timestamp should be ISO format
  assert(!isNaN(Date.parse(result.timestamp)), 'timestamp is valid ISO date');

  // refs should have string keys with string values
  const refKeys = Object.keys(result.refs);
  assert(refKeys.length > 0, 'refs map is not empty');
  for (const key of refKeys) {
    assert(typeof key === 'string', `ref key ${key} is a string`);
    assert(/^\d+$/.test(key), `ref key ${key} is a numeric string`);
    assert(typeof result.refs[key] === 'string', `ref value for ${key} is a string`);
  }

  await page.close();
}

async function testInteractiveElementsGetRefIds() {
  console.log('\n## Test: Interactive elements in tree have refId fields');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await accessibilitySnapshot(page);

  // Collect all nodes with refId by walking the tree
  function collectRefs(nodes) {
    const refs = [];
    for (const node of (Array.isArray(nodes) ? nodes : [nodes])) {
      if (node.refId !== undefined) {
        refs.push(node);
      }
      if (node.children) {
        refs.push(...collectRefs(node.children));
      }
    }
    return refs;
  }

  const annotatedNodes = collectRefs(result.tree);
  assert(annotatedNodes.length > 0, 'At least one tree node has a refId');

  // Each refId should be an integer
  for (const node of annotatedNodes) {
    assert(typeof node.refId === 'number' && Number.isInteger(node.refId), `refId ${node.refId} is an integer`);
  }

  await page.close();
}

async function testRefStability() {
  console.log('\n## Test: Two snapshots on same page produce same refs');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result1 = await accessibilitySnapshot(page);
  const result2 = await accessibilitySnapshot(page);

  // Same number of refs
  const keys1 = Object.keys(result1.refs).sort();
  const keys2 = Object.keys(result2.refs).sort();
  assertEqual(keys1.length, keys2.length, 'Same number of refs');

  // Same ref ID -> locator mappings
  let allMatch = true;
  for (const key of keys1) {
    if (result1.refs[key] !== result2.refs[key]) {
      allMatch = false;
      console.log(`    Mismatch at ref ${key}: ${result1.refs[key]} vs ${result2.refs[key]}`);
    }
  }
  assert(allMatch, 'All ref assignments are identical across snapshots');

  await page.close();
}

async function testDataTestidPriority() {
  console.log('\n## Test: data-testid element gets testid-based locator (priority 1)');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await accessibilitySnapshot(page);

  // Find the ref whose locator references data-testid="email"
  const emailRef = Object.entries(result.refs).find(
    ([_, loc]) => loc.includes('data-testid="email"')
  );
  assert(emailRef !== undefined, 'Found ref with data-testid="email" locator');
  if (emailRef) {
    assert(emailRef[1].startsWith('[data-testid='), 'Locator is testid-based (starts with [data-testid=)');
  }

  // The email input should NOT have a role-based locator (testid takes priority)
  const emailRoleBased = Object.entries(result.refs).find(
    ([_, loc]) => loc.includes('role=textbox') && loc.includes('Email')
  );
  // If both exist, that means testid didn't take priority
  assert(emailRoleBased === undefined, 'Email input does not also have a role-based locator');

  await page.close();
}

async function testNonInteractiveExcluded() {
  console.log('\n## Test: Non-interactive elements do not get ref IDs');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await accessibilitySnapshot(page);

  // Walk tree to find static text nodes
  function findByRole(nodes, targetRole) {
    const found = [];
    for (const node of (Array.isArray(nodes) ? nodes : [nodes])) {
      if (node.role === targetRole) {
        found.push(node);
      }
      if (node.children) {
        found.push(...findByRole(node.children, targetRole));
      }
    }
    return found;
  }

  // StaticText nodes should not have refId
  const staticTexts = findByRole(result.tree, 'StaticText');
  for (const st of staticTexts) {
    assert(st.refId === undefined, `StaticText "${(st.name || '').substring(0, 30)}..." has no refId`);
  }

  // "paragraph" role nodes should not have refId
  const paragraphs = findByRole(result.tree, 'paragraph');
  for (const p of paragraphs) {
    assert(p.refId === undefined, `Paragraph node has no refId`);
  }

  // "none" or "presentation" role nodes should not have refId
  const noneNodes = findByRole(result.tree, 'none');
  for (const n of noneNodes) {
    assert(n.refId === undefined, `None/presentation node has no refId`);
  }

  await page.close();
}

async function testBuildRefMapStandalone() {
  console.log('\n## Test: buildRefMap returns correct shape');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const refs = await buildRefMap(page);

  assert(typeof refs === 'object' && refs !== null, 'buildRefMap returns an object');
  const keys = Object.keys(refs);
  assert(keys.length > 0, 'buildRefMap returns non-empty map');

  // All keys should be numeric strings, all values should be strings
  for (const key of keys) {
    assert(/^\d+$/.test(key), `Key ${key} is a numeric string`);
    assert(typeof refs[key] === 'string' && refs[key].length > 0, `Value for ${key} is a non-empty string`);
  }

  await page.close();
}

async function testRefLocatorFormats() {
  console.log('\n## Test: Ref locator formats match expected patterns');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await accessibilitySnapshot(page);
  const locators = Object.values(result.refs);

  // We should see at least one testid-based locator
  const hasTestId = locators.some(l => l.includes('data-testid='));
  assert(hasTestId, 'At least one locator uses data-testid');

  // We should see at least one role-based locator
  const hasRole = locators.some(l => l.startsWith('role='));
  assert(hasRole, 'At least one locator uses role= format');

  await page.close();
}

async function testNoUrlCapturesCurrentPage() {
  console.log('\n## Test: Snapshot without navigation captures current page');
  const page = await context.newPage();
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  // Take snapshot without providing URL -- should capture current state
  const result = await accessibilitySnapshot(page);

  assert(result.url.includes('test-page.html'), 'URL reflects the current page');
  assert(result.tree.length > 0, 'Tree is not empty');

  await page.close();
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------

async function run() {
  console.log('# Snapshot & Ref System Tests\n');

  try {
    await setup();
  } catch (err) {
    console.error('Setup failed:', err.message);
    console.error('Make sure Playwright browsers are installed: npx playwright install chromium');
    process.exit(1);
  }

  const tests = [
    testOutputJsonShape,
    testInteractiveElementsGetRefIds,
    testRefStability,
    testDataTestidPriority,
    testNonInteractiveExcluded,
    testBuildRefMapStandalone,
    testRefLocatorFormats,
    testNoUrlCapturesCurrentPage,
  ];

  for (const test of tests) {
    try {
      await test();
    } catch (err) {
      testCount++;
      failCount++;
      console.log(`  FAIL: ${test.name} threw: ${err.message}`);
    }
  }

  await teardown();

  console.log(`\n---\nResults: ${passCount}/${testCount} passed, ${failCount} failed`);
  process.exit(failCount > 0 ? 1 : 0);
}

run();

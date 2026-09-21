'use strict';

/**
 * Tests for the page a run owns.
 *
 * Steps used to land on whichever page the manager was holding, and a page
 * that had gone was replaced with whatever else the context still had open.
 * A QA case could therefore be handed the previous case's page — its route
 * and its phone-width viewport — partway through, and its later assertions
 * timed out against a screen it never navigated to.
 *
 * Run: node tests/page-ownership.test.js
 */

const path = require('path');
const { createBrowserManager } = require('../src/browser-manager');
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

let manager;

function baseUrl() {
  return `file://${path.join(__dirname, 'fixtures')}`;
}

function fixtureUrl() {
  return `file://${path.join(__dirname, 'fixtures', 'test-page.html')}`;
}

async function testOwnedPageIsSizedWhenOpened() {
  console.log('\n## Test: an opened page is sized before anything loads');
  const opened = await manager.openOwnedPage({ width: 1440, height: 900 });
  assert(Boolean(opened.pageId), 'opening a page returns an id that addresses it');
  assertEqual(opened.opened, true, 'a fresh page reports that it was opened');
  assertEqual(opened.viewport.width, 1440, 'the page is the stated width');
  const page = manager.ownedPage(opened.pageId);
  assertEqual(page.viewportSize().height, 900, 'the page is the stated height');
  await manager.closeOwnedPage(opened.pageId);
}

async function testOneRunsWidthNeverReachesAnother() {
  console.log('\n## Test: one run\'s width never reaches another run');
  const phone = await manager.openOwnedPage({ width: 375, height: 812 });
  await executeStep(manager.ownedPage(phone.pageId), {
    action: 'delay', duration: 1, viewport: { width: 375, height: 812 },
  }, { baseUrl: baseUrl() });

  const desktop = await manager.openOwnedPage({ width: 1440, height: 900 });
  assert(desktop.pageId !== phone.pageId, 'each run addresses its own page');
  assertEqual(
    manager.ownedPage(desktop.pageId).viewportSize().width, 1440,
    'the later run is measured at its own width, not the earlier one\'s',
  );
  assertEqual(
    manager.ownedPage(phone.pageId).viewportSize().width, 375,
    'the earlier run keeps its width while it is still open',
  );
  await manager.closeOwnedPage(phone.pageId);
  await manager.closeOwnedPage(desktop.pageId);
}

async function testAnUnknownPageRefusesByName() {
  console.log('\n## Test: an unknown or closed page refuses by name');
  let message = '';
  try {
    manager.ownedPage('never-opened');
  } catch (err) {
    message = err.message;
  }
  assert(
    /No open page is registered as "never-opened"/.test(message),
    'an id nobody opened names itself in the refusal',
  );
  assert(
    /POST \/api\/exec\/page/.test(message),
    'the refusal names how to open one',
  );

  // A page that goes on its own -- a crash, or a site that closed the tab --
  // rather than one its owner released.
  const opened = await manager.openOwnedPage({ width: 800, height: 600 });
  await manager.ownedPage(opened.pageId).close();
  message = '';
  try {
    manager.ownedPage(opened.pageId);
  } catch (err) {
    message = err.message;
  }
  assert(
    /has closed/.test(message),
    'a page that closed under a run says so rather than substituting another',
  );

  message = '';
  const released = await manager.openOwnedPage({ width: 800, height: 600 });
  await manager.closeOwnedPage(released.pageId);
  try {
    manager.ownedPage(released.pageId);
  } catch (err) {
    message = err.message;
  }
  assert(
    /No open page is registered/.test(message),
    'a released page is no longer addressable',
  );
}

async function testANamedPageComesBackAsItStands() {
  console.log('\n## Test: a named page comes back as its owner left it');
  const first = await manager.openOwnedPage({ width: 1440, height: 900 }, 'exploratory');
  await manager.ownedPage(first.pageId).setViewportSize({ width: 390, height: 844 });

  const again = await manager.openOwnedPage({ width: 1440, height: 900 }, 'exploratory');
  assertEqual(again.pageId, 'exploratory', 'the name addresses the same page');
  assertEqual(again.opened, false, 'reuse reports that nothing was opened');
  assertEqual(again.viewport.width, 390, 'reuse does not resize the page its owner set');
  await manager.closeOwnedPage('exploratory');
}

async function testInteractivePageIsNeverAStrayOne() {
  console.log('\n## Test: the interactive page is never a stray one');
  const stray = await manager.openOwnedPage({ width: 320, height: 480 });
  await manager.ownedPage(stray.pageId).goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const interactive = await manager.getPage();
  assert(
    interactive !== manager.ownedPage(stray.pageId),
    'an interactive caller is not handed a page another caller owns',
  );
  await manager.closeOwnedPage(stray.pageId);
}

async function testStepReportsWhatThePageWas() {
  console.log('\n## Test: every step reports the page it actually ran on');
  const opened = await manager.openOwnedPage({ width: 1024, height: 768 });
  const page = manager.ownedPage(opened.pageId);
  await page.goto(fixtureUrl(), { waitUntil: 'domcontentloaded' });

  const result = await executeStep(page, {
    action: 'delay', duration: 1,
  }, { baseUrl: baseUrl() });
  assertEqual(result.success, true, 'the step succeeds');
  assertEqual(result.viewport.width, 1024, 'the step reports the width it ran at');
  assertEqual(result.url, fixtureUrl(), 'the step reports the url it ran on');

  const failed = await executeStep(page, {
    action: 'assert', target: '#nope', check: 'visible', timeout_ms: 200,
  }, { baseUrl: baseUrl() });
  assertEqual(failed.success, false, 'a failing step still fails');
  assertEqual(
    failed.viewport.width, 1024,
    'a failing step reports the page too, so the failure can be read',
  );
  await manager.closeOwnedPage(opened.pageId);
}

async function main() {
  manager = createBrowserManager({ headless: true });
  await manager.launch();
  try {
    await testOwnedPageIsSizedWhenOpened();
    await testOneRunsWidthNeverReachesAnother();
    await testAnUnknownPageRefusesByName();
    await testANamedPageComesBackAsItStands();
    await testInteractivePageIsNeverAStrayOne();
    await testStepReportsWhatThePageWas();
  } finally {
    await manager.closeBrowser();
  }
  console.log(`\n${passCount}/${testCount} passed, ${failCount} failed`);
  process.exit(failCount > 0 ? 1 : 0);
}

main();

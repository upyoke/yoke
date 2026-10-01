'use strict';

/**
 * Tests route resolution and credential redaction.
 *
 * These are pure functions over URLs, so they need no browser: keeping them
 * apart from the browser-driven suites is what lets a URL regression be seen
 * without launching Chromium.
 *
 * Run: node tests/step-runner-url.test.js
 */

const { resolveUrl } = require('../src/step-runner');
const { redactUrl } = require('../src/step-actions/navigation');

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

async function testResolveUrl() {
  console.log('\n## Test: resolveUrl handles relative and absolute routes');

  // Relative route gets baseUrl prepended
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

  // Absolute URLs pass through
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

  // A fragment route replaces only the fragment. String concatenation put it
  // after the query instead, producing '?token=X/#/route' -- a URL the server
  // reads as a path under the token.
  assertEqual(
    resolveUrl('#/route', 'http://localhost:3000/?token=abc123'),
    'http://localhost:3000/?token=abc123#/route',
    'Bare fragment route keeps the base query and does not gain a slash'
  );

  assertEqual(
    resolveUrl('/#/route', 'http://localhost:3000/?token=abc123'),
    'http://localhost:3000/?token=abc123#/route',
    'Fragment route keeps the base query and does not gain a slash'
  );

  // The base query is how a token-gated server recognises the session, so it
  // travels to a path route too.
  assertEqual(
    resolveUrl('/dashboard', 'http://localhost:3000/?token=abc123'),
    'http://localhost:3000/dashboard?token=abc123',
    'Base query carries onto a path route'
  );

  // A route stating the same parameter wins over the base.
  assertEqual(
    resolveUrl('/dashboard?token=route', 'http://localhost:3000/?token=base'),
    'http://localhost:3000/dashboard?token=route',
    'Route query wins over the base query'
  );

  // A base carrying a path prefix keeps it: resolving against the origin
  // would silently drop the prefix the universe is served under.
  assertEqual(
    resolveUrl('/panel', 'http://localhost:3000/yoke'),
    'http://localhost:3000/yoke/panel',
    'Base path prefix survives an absolute-looking route'
  );

  // A protocol-relative route stays on the base origin.
  assertEqual(
    resolveUrl('//example.com/page', 'http://localhost:3000/'),
    'http://localhost:3000/example.com/page',
    'Protocol-relative route does not escape the base origin'
  );
}

async function testResolveUrlResolvesFileBase() {
  console.log('\n## Test: resolveUrl keeps a file: base scheme');

  // The substrate's own fixtures are served from disk, and a file: URL has
  // no origin -- composing one from `origin` would lose the scheme.
  assertEqual(
    resolveUrl('/test-page.html', 'file:///tmp/fixtures'),
    'file:///tmp/fixtures/test-page.html',
    'A file: base resolves a rooted route under its directory'
  );

  assertEqual(
    resolveUrl('test-page.html', 'file:///tmp/fixtures'),
    'file:///tmp/fixtures/test-page.html',
    'A file: base resolves a bare route under its directory'
  );
}

async function testResolveUrlRefusesUnusableBase() {
  console.log('\n## Test: resolveUrl refuses a base it cannot navigate');

  for (const [bad, expected] of [
    ['not a url', /is not an absolute URL/],
    ['localhost:3000', /localhost: scheme, which cannot be navigated/],
    ['ftp://host/', /ftp: scheme, which cannot be navigated/],
  ]) {
    let message = '';
    try {
      resolveUrl('/home', bad);
    } catch (err) {
      message = String(err.message);
    }
    assert(
      expected.test(message),
      `${JSON.stringify(bad)} is refused by name (got ${JSON.stringify(message)})`
    );
    assert(
      /http:\/\/localhost:3000/.test(message),
      `${JSON.stringify(bad)} refusal shows the shape a base URL should have`
    );
  }
}

async function testRedactUrl() {
  console.log('\n## Test: redactUrl masks credential query values');

  assertEqual(
    redactUrl('http://localhost:3000/x?token=SECRET&page=2'),
    'http://localhost:3000/x?token=REDACTED&page=2',
    'A token value is masked and the rest of the query survives'
  );

  assertEqual(
    redactUrl('http://localhost:3000/x?access_token=A&signature=B'),
    'http://localhost:3000/x?access_token=REDACTED&signature=REDACTED',
    'Every credential-bearing parameter is masked'
  );

  assertEqual(
    redactUrl('http://localhost:3000/plain'),
    'http://localhost:3000/plain',
    'A URL with no credential query is unchanged'
  );

  assertEqual(
    redactUrl('not a url'),
    'not a url',
    'An unparseable value is returned as-is rather than suppressed'
  );
}

async function run() {
  console.log('=== Step Runner Tests: URL Resolution ===');
  try {
    await testResolveUrl();
    await testResolveUrlResolvesFileBase();
    await testResolveUrlRefusesUnusableBase();
    await testRedactUrl();
  } catch (err) {
    console.error('\nUnexpected error:', err);
    failCount++;
  }
  console.log(`\n=== Results: ${passCount}/${testCount} passed, ${failCount} failed ===`);
  if (failCount > 0) process.exit(1);
}

run();

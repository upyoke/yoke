'use strict';

/**
 * Browser manager -- wraps a single Playwright browser context.
 *
 * With a profile directory the context is persistent: it opens the operator's
 * signed-in Chromium profile for one project, so every page handed out is
 * signed into whatever the operator signed into. Without one the context is a
 * throwaway with an empty cookie jar.
 *
 * Two kinds of page come out of that context, and the difference is who owns
 * the page's state. `getPage` is the interactive one: a person browsing or a
 * diagnostic snapshot means "whatever I am looking at now", so it keeps one
 * current page. `openOwnedPage` is for a caller whose whole run is about one
 * page -- a QA case walking its steps -- which addresses that page by id for
 * every call and closes it at the end. Nothing else can hand that page to
 * another caller, so no route and no viewport can arrive from one run in the
 * next.
 *
 * Exports: createBrowserManager(options) -> { launch, getBrowser, getPage, newPage, openOwnedPage, ownedPage, closeOwnedPage, closeBrowser, isConnected, getProfileDir }
 */

const crypto = require('crypto');
const { chromium } = require('playwright');

/**
 * @param {Object} options
 * @param {string} [options.browserType='chromium'] - Browser type (only chromium supported today)
 * @param {boolean} [options.headless=true] - Run headless
 * @param {string} [options.profileDir] - Persistent profile directory, or empty for a throwaway context
 * @returns {Object} Browser manager interface
 */
function createBrowserManager(options = {}) {
  const browserType = options.browserType || 'chromium';
  const headless = options.headless !== false;
  const profileDir = options.profileDir || '';

  let browser = null;
  let context = null;
  let currentPage = null;
  // pageId -> Page, for callers that own their page for a whole run.
  const ownedPages = new Map();

  async function launch() {
    if (browserType !== 'chromium') {
      throw new Error(`Unsupported browser type: ${browserType}. Only chromium is supported.`);
    }
    if (profileDir) {
      // A persistent context owns its own browser process; Playwright returns
      // no Browser handle for it, so `context` is the lifecycle authority.
      context = await chromium.launchPersistentContext(profileDir, { headless });
      return context;
    }
    browser = await chromium.launch({ headless });
    context = await browser.newContext();
    return browser;
  }

  function getBrowser() {
    return browser;
  }

  function getProfileDir() {
    return profileDir;
  }

  /**
   * Get the interactive current page, creating one if needed. Navigates to
   * url if provided.
   *
   * A gone current page is replaced with a new one rather than with whatever
   * else the context still has open. Adopting a stray page silently handed
   * one caller another caller's page, complete with its route and its
   * viewport, and every later capture then described a screen nobody asked
   * for.
   */
  async function getPage(url) {
    if (!context) {
      throw new Error('Browser not launched. Call launch() first.');
    }
    if (!currentPage || currentPage.isClosed()) {
      currentPage = await context.newPage();
    }
    if (url) {
      await currentPage.goto(url, { waitUntil: 'domcontentloaded' });
    }
    return currentPage;
  }

  /**
   * Open a page owned by one caller, sized before anything is loaded into it.
   *
   * A caller that lives for one run takes a fresh id each time. A caller that
   * spans separate processes -- an exploratory agent submitting one step per
   * command -- names its page instead, and gets the same page back for as
   * long as it stays open. A named page is returned as it stands: the size
   * and the route its owner established are the state it came back for, so
   * reuse never resizes it.
   *
   * @param {{width: number, height: number}} viewport - Required: an opened
   *   page states its size rather than inheriting one.
   * @param {string} [pageId] - A name the owner reuses across calls.
   * @returns {Promise<{pageId: string, viewport: {width: number, height: number}, opened: boolean}>}
   */
  async function openOwnedPage(viewport, pageId) {
    if (!context) {
      throw new Error('Browser not launched. Call launch() first.');
    }
    const existing = pageId ? ownedPages.get(pageId) : null;
    if (existing && !existing.isClosed()) {
      return { pageId, viewport: existing.viewportSize(), opened: false };
    }
    const { width, height } = viewport || {};
    if (!Number.isFinite(width) || !Number.isFinite(height)) {
      throw new Error(
        'opening a page needs a viewport with numeric width and height, '
        + `got ${JSON.stringify(viewport)}`
      );
    }
    const page = await context.newPage();
    await page.setViewportSize({ width, height });
    const id = pageId || crypto.randomUUID();
    ownedPages.set(id, page);
    return { pageId: id, viewport: page.viewportSize(), opened: true };
  }

  /**
   * Resolve an owned page by id, or refuse by name.
   */
  function ownedPage(pageId) {
    const page = ownedPages.get(pageId);
    if (!page) {
      throw new Error(
        `No open page is registered as ${JSON.stringify(pageId)}. A page is `
        + 'addressable only between opening it and closing it; open one with '
        + 'POST /api/exec/page before sending steps.'
      );
    }
    if (page.isClosed()) {
      ownedPages.delete(pageId);
      throw new Error(
        `The page registered as ${JSON.stringify(pageId)} has closed, so the `
        + 'state this run was observing is gone. Nothing else is substituted '
        + 'for it: open a new page and restart the run that owns it.'
      );
    }
    return page;
  }

  /**
   * Close an owned page. Closing an unknown id is not an error -- the caller
   * asked for it to be gone and it is.
   */
  async function closeOwnedPage(pageId) {
    const page = ownedPages.get(pageId);
    ownedPages.delete(pageId);
    if (page && !page.isClosed()) {
      try {
        await page.close();
      } catch (_) {
        // The page may already be gone with its browser.
      }
    }
    return { closed: true };
  }

  /**
   * Always create a new page. Navigates to url if provided.
   */
  async function newPage(url) {
    if (!context) {
      throw new Error('Browser not launched. Call launch() first.');
    }
    currentPage = await context.newPage();
    if (url) {
      await currentPage.goto(url, { waitUntil: 'domcontentloaded' });
    }
    return currentPage;
  }

  async function closeBrowser() {
    const closable = browser || context;
    if (closable) {
      try {
        await closable.close();
      } catch (_) {
        // Browser may already be disconnected
      }
      browser = null;
      context = null;
      currentPage = null;
      ownedPages.clear();
    }
  }

  function isConnected() {
    if (browser) {
      return browser.isConnected();
    }
    return context !== null;
  }

  return {
    launch,
    getBrowser,
    getProfileDir,
    getPage,
    newPage,
    openOwnedPage,
    ownedPage,
    closeOwnedPage,
    closeBrowser,
    isConnected,
  };
}

module.exports = { createBrowserManager };

#!/usr/bin/env node
"use strict";

// Optional reference bridge for web-forager-browser.
//
// web-forager-browser itself has no runtime dependencies. This file only works when
// `playwright` is installed next to it (or globally resolvable). Modes:
//
//   node bridges/playwright-bridge.js                      fresh chromium
//   WEB_FORAGER_BROWSER_HEADFUL=1 node bridges/playwright-bridge.js  visible window
//   WEB_FORAGER_BROWSER_PROFILE=/path/to/profile node bridges/...    persistent profile
//   WEB_FORAGER_BROWSER_CDP=http://127.0.0.1:9222 node bridges/...   attach to your browser
//
// Protocol: one JSON-RPC 2.0 request per line on stdin, one response per line
// on stdout. Methods: goto, snapshot, click, scroll, screenshot, tabs, observe.

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

let playwright;
try {
  playwright = require("playwright");
} catch (error) {
  process.stderr.write(
    "playwright-bridge: playwright is not installed.\n" +
      "Install it with `npm i playwright && npx playwright install chromium`, " +
      "or point WEB_FORAGER_BRIDGE at your own bridge implementing the same protocol.\n",
  );
  process.exit(3);
}

// Every request the page makes — the document itself and each subresource —
// is checked against the private-address guard. A hostile page therefore
// cannot use the browser to read http://127.0.0.1:... or a metadata endpoint.
const { isPublicRequestUrl } = require("../lib/netguard");

const SNAPSHOT_SCRIPT = () => {
  const nodes = [];
  let seq = 0;
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 1 && rect.height > 1 && style.visibility !== "hidden" && style.display !== "none";
  };
  const push = (role, el) => {
    if (!el || !visible(el)) return;
    const name = (el.getAttribute("aria-label") || el.innerText || el.textContent || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 300);
    if (!name) return;
    const id = String(++seq);
    el.setAttribute("data-web-forager-browser-id", id);
    const node = { role, name, locator: `[data-web-forager-browser-id="${id}"]` };
    if (el.tagName === "A") node.href = el.href || "";
    nodes.push(node);
  };
  const scope = document.body || document.documentElement;
  for (const el of scope.querySelectorAll("h1,h2,h3,h4")) push("heading", el);
  for (const el of scope.querySelectorAll("a[href]")) push("link", el);
  for (const el of scope.querySelectorAll("button,[role=button]")) push("button", el);
  for (const el of scope.querySelectorAll("p,li,span,div")) {
    if (el.children.length === 0 && (el.textContent || "").trim().length > 4) push("text", el);
  }
  return { url: location.href, title: document.title, nodes: nodes.slice(0, 800) };
};

let browser = null;
let context = null;

async function getPage() {
  if (!context) throw new Error("no page: call goto first");
  const pages = context.pages();
  return pages.length ? pages[pages.length - 1] : context.newPage();
}

const DEFAULT_PROFILE = path.join(os.homedir(), ".web-forager", "browser", "profile");
// Sites fingerprint the default automation flags; drop the loudest one and
// keep navigator.webdriver from being set where the browser allows it.
const LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"];
const LAUNCH_OPTIONS = {
  ignoreDefaultArgs: ["--enable-automation"],
  args: LAUNCH_ARGS,
  viewport: { width: 1280, height: 900 },
};

function profilePath() {
  const configured = (process.env.WEB_FORAGER_BROWSER_PROFILE || "").trim();
  if (["off", "0", "false", "none"].includes(configured.toLowerCase())) return "";
  return path.resolve(configured || DEFAULT_PROFILE);
}

async function installNetGuard(active) {
  try {
    await active.route("**/*", async (route) => {
      const url = route.request().url();
      if (/^https?:/i.test(url) && !(await isPublicRequestUrl(url))) {
        return route.abort("blockedbyclient");
      }
      return route.continue();
    });
  } catch (error) {
    process.stderr.write(
      `playwright-bridge: could not install the private-address guard (${error.message}); ` +
        "navigation checks in the caller still apply.\n",
    );
  }
}

async function start() {
  if (context) return;
  if (process.env.WEB_FORAGER_BROWSER_CDP) {
    browser = await playwright.chromium.connectOverCDP(process.env.WEB_FORAGER_BROWSER_CDP);
    context = browser.contexts()[0] || (await browser.newContext());
    await installNetGuard(context);
    return;
  }
  const headless = process.env.WEB_FORAGER_BROWSER_HEADFUL !== "1";
  // A fresh context per run has no cookies, and Bilibili, Sogou and Zhihu turn
  // that into a risk-control page immediately. The profile persists by default;
  // WEB_FORAGER_BROWSER_PROFILE=off gives the old throwaway browser.
  const profile = profilePath();
  if (profile) {
    fs.mkdirSync(profile, { recursive: true });
    context = await playwright.chromium.launchPersistentContext(profile, { headless, ...LAUNCH_OPTIONS });
    await installNetGuard(context);
    return;
  }
  browser = await playwright.chromium.launch({ headless, ...LAUNCH_OPTIONS });
  context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await installNetGuard(context);
}

const SETTLE_MS = 500;

async function goto(params) {
  await start();
  const page = context.pages()[0] || (await context.newPage());
  await page.goto(String(params.url), { waitUntil: "domcontentloaded", timeout: 45000 });
  // domcontentloaded fires before the page's own redirects run; a login wall or
  // verification page then swaps the document out from under the next call.
  // Wait for the load event when it comes, then let the redirect settle.
  await page.waitForLoadState("load", { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(SETTLE_MS);
  const title = await page.title().catch(() => "");
  return { url: page.url(), title };
}

async function snapshot() {
  const page = await getPage();
  try {
    return await page.evaluate(SNAPSHOT_SCRIPT);
  } catch (error) {
    const message = String(error && error.message ? error.message : error);
    if (!/context was destroyed|navigat|target closed|frame was detached/i.test(message)) throw error;
    // The document changed after goto: wait for the new one and read it once
    // more, reporting where the page actually ended up if that also fails.
    await page.waitForTimeout(2000);
    try {
      return await page.evaluate(SNAPSHOT_SCRIPT);
    } catch (retryError) {
      const url = page.url();
      const wrapped = new Error(
        `snapshot failed after a redirect (page is at ${url}): ${retryError.message || retryError}`,
      );
      wrapped.url = url;
      throw wrapped;
    }
  }
}

function locate(page, locator) {
  const value = String(locator || "");
  if (/^[.#[\]]/.test(value) || value.includes("[data-web-forager-browser-id")) return page.locator(value).first();
  return page.getByText(value, { exact: false }).first();
}

async function click(params) {
  const page = await getPage();
  await locate(page, params.locator).click({ timeout: 15000 });
  return { ok: true, url: page.url() };
}

async function scroll(params) {
  const page = await getPage();
  await page.mouse.wheel(0, Number(params.dy || 600));
  await page.waitForTimeout(400);
  return { ok: true };
}

async function screenshot() {
  const page = await getPage();
  const dir = path.join(os.homedir(), ".web-forager/browser", "screenshots");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${Date.now()}.png`);
  await page.screenshot({ path: file, fullPage: false });
  return { path: file };
}

async function currentUrl() {
  if (!context) return { url: "" };
  const page = await getPage();
  return { url: page.url(), title: await page.title().catch(() => "") };
}

async function tabs() {
  if (!context) return { tabs: [] };
  const pages = context.pages();
  const out = [];
  for (const page of pages) out.push({ url: page.url(), title: await page.title() });
  return { tabs: out };
}

function stamp(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = String(Math.floor(total / 60)).padStart(2, "0");
  const rest = String(total % 60).padStart(2, "0");
  return `${minutes}:${rest}`;
}

async function observeDanmaku(page, ms) {
  const seen = new Set();
  const entries = [];
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    const batch = await page.evaluate(() => {
      const video = document.querySelector("video");
      const time = video && Number.isFinite(video.currentTime) ? video.currentTime : 0;
      const nodes = Array.from(
        document.querySelectorAll('[class*="danmaku"], [class*="danmaku-item"], [class*="bili-danmaku"]'),
      );
      const texts = nodes.map((el) => (el.textContent || "").replace(/\s+/g, " ").trim()).filter(Boolean);
      return { time, texts };
    });
    for (const text of batch.texts) {
      const key = text.slice(0, 120);
      if (seen.has(key)) continue;
      seen.add(key);
      entries.push({ time: stamp(batch.time), text: key });
    }
    await page.waitForTimeout(300);
  }
  return { topic: "danmaku", entries: entries.slice(0, 500) };
}

async function observeNetwork(page, ms) {
  const events = [];
  const listener = (response) => {
    if (events.length >= 300) return;
    const request = response.request();
    events.push({
      url: response.url(),
      status: response.status(),
      method: request.method(),
      resource_type: request.resourceType(),
      content_type: (response.headers() || {})["content-type"] || "",
    });
  };
  page.on("response", listener);
  try {
    await page.waitForTimeout(ms);
  } finally {
    page.off("response", listener);
  }
  return { topic: "network", events };
}

async function observe(params) {
  const page = await getPage();
  const topic = String(params.topic || "danmaku");
  const ms = Math.min(Math.max(Number(params.ms || 3000), 0), 60000);
  if (topic === "network") return observeNetwork(page, ms);
  return observeDanmaku(page, ms);
}

// Declare what this bridge actually implements, so web-forager-browser never
// assumes a capability the bridge cannot serve.
function describe() {
  return {
    protocol: 1,
    capabilities: { loginState: true, screenshot: true, cua: true, observe: true },
    modes: {
      headful: process.env.WEB_FORAGER_BROWSER_HEADFUL === "1",
      profile: Boolean(process.env.WEB_FORAGER_BROWSER_PROFILE),
      cdp: Boolean(process.env.WEB_FORAGER_BROWSER_CDP),
    },
  };
}

const METHODS = { describe, goto, snapshot, click, scroll, screenshot, tabs, url: currentUrl, observe };

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

async function run() {
  let buffer = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) {
    buffer += chunk;
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      newline = buffer.indexOf("\n");
      if (!line) continue;
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        send({ jsonrpc: "2.0", id: null, error: { code: "protocol", message: "parse error" } });
        continue;
      }
      const handler = METHODS[message.method];
      if (!handler) {
        send({ jsonrpc: "2.0", id: message.id, error: { code: "protocol", message: `unknown method: ${message.method}` } });
        continue;
      }
      try {
        const result = await handler(message.params || {});
        send({ jsonrpc: "2.0", id: message.id, result });
      } catch (error) {
        send({ jsonrpc: "2.0", id: message.id, error: { code: "navigation", message: error.message } });
      }
    }
  }
  if (context) await context.close();
  if (browser) await browser.close();
}

run().catch((error) => {
  process.stderr.write(`playwright-bridge: ${error.stack || error.message}\n`);
  process.exit(1);
});

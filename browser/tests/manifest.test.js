"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { playbooks } = require("../lib/playbooks");

const BROWSER_ROOT = path.join(__dirname, "..");
const PLUGIN_ROOT = path.join(BROWSER_ROOT, "..");

function read(...parts) {
  return fs.readFileSync(path.join(...parts), "utf8");
}

test("the plugin manifest declares the browser block", () => {
  const manifest = JSON.parse(read(PLUGIN_ROOT, "manifest.json"));
  assert.equal(manifest.name, "web-forager");
  assert.equal(manifest.version, "1.2.1");
  assert.equal(manifest.browser.entrypoint, "browser/run.js");
  assert.equal(manifest.browser.runtime, "node >= 18");
  assert.equal(manifest.browser.mcp.entrypoint, "browser/mcp_server.js");
  assert.equal(manifest.browser.mcp.server, "web-forager-browser");
  assert.deepEqual(manifest.browser.playbooks.slice().sort(), Object.keys(playbooks).sort());
  assert.deepEqual(manifest.browser.backends, ["iab", "extension", "cdp"]);
});

test("the browser package carries the plugin version and name", () => {
  const pkg = JSON.parse(read(BROWSER_ROOT, "package.json"));
  assert.equal(pkg.name, "web-forager-browser");
  assert.equal(pkg.version, "1.2.1");
  assert.equal(pkg.engines.node, ">=18");
});

test(".mcp.json registers the HTTP and browser servers", () => {
  const config = JSON.parse(read(PLUGIN_ROOT, ".mcp.json"));
  const http = config.mcpServers["web-forager"];
  const browser = config.mcpServers["web-forager-browser"];
  assert.ok(http.args[0].endsWith("/mcp_server.py"));
  assert.ok(browser.args[0].endsWith("/browser/mcp_server.js"));
  assert.equal(browser.command, "node");
});

test("the browser layer no longer carries the old product name", () => {
  const files = ["run.js", "mcp_server.js", "lib/backend.js", "lib/session.js", "lib/record.js"];
  for (const file of files) {
    const text = read(BROWSER_ROOT, file);
    assert.equal(/web-actor/i.test(text), false, file);
  }
});

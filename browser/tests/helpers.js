"use strict";

// Playbook tests run against fixtures; never reach the Bilibili search API.
process.env.WEB_FORAGER_BILI_API = "off";

const { freshSession } = require("../lib/session");
const { makeRecord } = require("../lib/record");
const { makeContext } = require("../lib/context");

class FakeBackend {
  constructor(snapshots) {
    this.name = "fake";
    this.available = true;
    this.snapshots = snapshots.slice();
    this.last = snapshots[0] || { url: "", title: "", nodes: [] };
    this.actions = [];
  }

  capabilities() {
    return { loginState: false, screenshot: false, cua: false, observe: typeof this.observe === "function" };
  }

  async goto(url) {
    this.actions.push({ action: "goto", url });
    this.last = { ...this.last, url };
  }

  async snapshot() {
    if (this.snapshots.length) this.last = this.snapshots.shift();
    return this.last;
  }

  async click(locator) {
    this.actions.push({ action: "click", locator });
  }

  async scroll(dy) {
    this.actions.push({ action: "scroll", dy });
  }

  async screenshot() {
    return null;
  }

  async observe(topic, ms) {
    this.actions.push({ action: "observe", topic, ms });
    if (this.observed) return this.observed;
    throw new Error("observe is not supported by this backend");
  }

  async close() {}
}

function contextFor(backend, options = {}) {
  const session = freshSession("test", "test");
  const sleeps = [];
  const ctx = makeContext({
    backend,
    session,
    options: { minInterval: 0, ...options },
    makeRecord,
    sleep: async (ms) => sleeps.push(ms),
    log: () => {},
  });
  ctx.sleeps = sleeps;
  return ctx;
}

module.exports = { FakeBackend, contextFor };

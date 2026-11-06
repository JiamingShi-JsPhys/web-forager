"use strict";

const { spawn } = require("node:child_process");
const { ActorError } = require("./errors");

const BACKENDS = {
  iab: "in-app browser session driven by a bridge process",
  extension: "the user's logged-in browser through an extension bridge",
  cdp: "a Chrome DevTools Protocol endpoint you already control",
};

class UnavailableBackend {
  constructor(reason = "no browser bridge configured", backend = "unavailable") {
    this.name = backend;
    this.available = false;
    this.reason = reason;
  }

  capabilities() {
    return { backend: this.name, loginState: false, screenshot: false, cua: false, observe: false };
  }

  async goto() {
    throw new ActorError(
      "backend_unavailable",
      this.reason,
      "Set WEB_FORAGER_BRIDGE to a bridge command (for example `node bridge.js`) or pass --bridge.",
    );
  }

  async snapshot() {
    return this.goto();
  }

  async click() {
    return this.goto();
  }

  async scroll() {
    return this.goto();
  }

  async screenshot() {
    return this.goto();
  }

  async tabs() {
    return this.goto();
  }

  async observe() {
    return this.goto();
  }

  async close() {}
}

class BridgeBackend {
  constructor(command, options = {}) {
    this.name = options.name || "iab";
    this.available = true;
    this.command = command;
    this.timeout = options.timeout || 30000;
    this.child = null;
    this.buffer = "";
    this.nextId = 1;
    this.pending = new Map();
  }

  capabilities() {
    return { backend: this.name, loginState: true, screenshot: true, cua: true, observe: true };
  }

  start() {
    if (this.child) return;
    this.child = spawn(this.command, { shell: true, stdio: ["pipe", "pipe", "pipe"] });
    this.child.stdout.setEncoding("utf8");
    this.child.stdout.on("data", (chunk) => this.onData(chunk));
    this.child.stderr.on("data", () => {});
    this.child.on("exit", (code) => {
      this.failAll(new ActorError("backend_unavailable", `browser bridge exited with code ${code}`));
      this.child = null;
    });
  }

  onData(chunk) {
    this.buffer += chunk;
    let newline = this.buffer.indexOf("\n");
    while (newline >= 0) {
      const line = this.buffer.slice(0, newline).trim();
      this.buffer = this.buffer.slice(newline + 1);
      if (line) this.onLine(line);
      newline = this.buffer.indexOf("\n");
    }
  }

  onLine(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      return;
    }
    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);
    clearTimeout(pending.timer);
    if (message.error) {
      pending.reject(new ActorError(message.error.code || "navigation", message.error.message || "bridge error"));
    } else {
      pending.resolve(message.result);
    }
  }

  failAll(error) {
    for (const [, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
  }

  request(method, params = {}) {
    this.start();
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new ActorError("navigation", `bridge request timed out: ${method}`));
      }, this.timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  }

  async goto(url) {
    await this.request("goto", { url });
  }

  async snapshot() {
    return this.request("snapshot");
  }

  async click(locator) {
    await this.request("click", { locator });
  }

  async scroll(dy) {
    await this.request("scroll", { dy });
  }

  async screenshot() {
    return this.request("screenshot");
  }

  async tabs() {
    return this.request("tabs");
  }

  async observe(topic, ms) {
    return this.request("observe", { topic, ms });
  }

  async close() {
    if (!this.child) return;
    this.child.kill();
    this.child = null;
  }
}

function createBackend(options = {}) {
  const backend = options.backend || "iab";
  if (!BACKENDS[backend]) {
    throw new ActorError(
      "argument",
      `unknown backend: ${backend}`,
      `Use one of: ${Object.keys(BACKENDS).join(", ")}.`,
    );
  }
  const command = options.bridge || process.env.WEB_FORAGER_BRIDGE;
  if (command) return new BridgeBackend(command, { ...options, name: backend });
  return new UnavailableBackend(
    options.reason || `no bridge command for backend "${backend}"`,
    backend,
  );
}

module.exports = { BACKENDS, UnavailableBackend, BridgeBackend, createBackend };

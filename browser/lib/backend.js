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
    return {
      backend: this.name,
      source: "unavailable",
      declared: false,
      loginState: false,
      screenshot: false,
      cua: false,
      observe: false,
    };
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

  async currentUrl() {
    const result = await this.request("url", {}, 3000);
    return (result && result.url) || "";
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
    this.declared = null;
    this.describeError = "";
    this.closed = false;
    this.stderr = "";
    this.stderrLines = [];
  }

  // Capabilities are reported by the bridge itself through an optional
  // `describe` call. A bridge that does not implement it gets the conservative
  // answer instead of an optimistic one: every capability is false, so the
  // playbooks never assume a call the bridge cannot serve.
  async capabilities() {
    if (this.declared) return { backend: this.name, source: "declared", declared: true, ...this.declared };
    if (this.closed) {
      return {
        backend: this.name,
        source: "undeclared",
        declared: false,
        reason: "the bridge was already closed",
        loginState: false,
        screenshot: false,
        cua: false,
        observe: false,
      };
    }
    if (this.describeError) {
      return {
        backend: this.name,
        source: "undeclared",
        declared: false,
        reason: this.describeError,
        loginState: false,
        screenshot: false,
        cua: false,
        observe: false,
      };
    }
    try {
      const described = await this.request("describe", {}, 2000);
      const declared = (described && (described.capabilities || described)) || {};
      this.declared = {
        loginState: declared.loginState === true,
        screenshot: declared.screenshot === true,
        cua: declared.cua === true,
        observe: declared.observe === true,
      };
      return { backend: this.name, source: "declared", declared: true, ...this.declared };
    } catch (error) {
      this.describeError = error && error.message ? error.message : String(error);
      return {
        backend: this.name,
        source: "undeclared",
        declared: false,
        reason: this.describeError,
        loginState: false,
        screenshot: false,
        cua: false,
        observe: false,
      };
    }
  }

  start() {
    if (this.child) return;
    const child = spawn(this.command, { shell: true, stdio: ["pipe", "pipe", "pipe"] });
    this.child = child;
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => this.onData(chunk));
    // Keep the tail of stderr: when a bridge dies on startup its message is the
    // only explanation the caller gets.
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => {
      for (const line of String(chunk).split(/\r?\n/)) {
        if (!line.trim()) continue;
        this.stderrLines.push(line);
        if (this.stderrLines.length > 50) this.stderrLines.shift();
      }
      this.stderr = this.stderrLines.join("\n").slice(-4000);
    });
    child.on("exit", (code) => {
      // Only clear the handle if this is still the current process: a restarted
      // bridge must not be detached by the previous one's exit event.
      if (this.child === child) {
        this.child = null;
        this.failAll(
          new ActorError(
            "backend_unavailable",
            `browser bridge exited with code ${code}${this.stderr ? `: ${this.stderr.trim().slice(-500)}` : ""}`,
            "Run the bridge command by hand to see its full output.",
          ),
        );
      }
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

  request(method, params = {}, timeoutMs) {
    if (this.closed) {
      return Promise.reject(new ActorError("backend_unavailable", "the browser bridge was closed"));
    }
    this.start();
    const id = this.nextId++;
    const budget = Number(timeoutMs) > 0 ? Number(timeoutMs) : this.timeout;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        const tail = this.stderrLines.length
          ? ` (bridge stderr: ${this.stderrLines.slice(-3).join(" | ")})`
          : "";
        reject(new ActorError("navigation", `bridge request timed out: ${method}${tail}`));
      }, budget);
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
    this.closed = true;
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

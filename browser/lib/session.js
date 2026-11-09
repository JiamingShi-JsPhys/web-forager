"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

function nowIso() {
  return new Date().toISOString();
}

function rootDir() {
  if (process.env.WEB_FORAGER_BROWSER_HOME) return path.resolve(process.env.WEB_FORAGER_BROWSER_HOME);
  return path.join(os.homedir(), ".web-forager/browser");
}

function cleanName(name) {
  const value = String(name || "default").trim();
  if (!/^[A-Za-z0-9._-]{1,64}$/.test(value)) {
    throw new Error("invalid session name: use letters, digits, dot, dash or underscore");
  }
  return value;
}

function sessionPath(name) {
  return path.join(rootDir(), "sessions", `${cleanName(name)}.json`);
}

function freshSession(name, playbook = null) {
  const at = nowIso();
  return {
    schema_version: "1",
    name: cleanName(name),
    playbook,
    created_at: at,
    updated_at: at,
    visited: [],
    captured: [],
    chain: [],
    cursor: {},
    counters: {},
  };
}

function loadSession(name, options = {}) {
  const file = sessionPath(name);
  try {
    const data = JSON.parse(fs.readFileSync(file, "utf8"));
    return normalize(data, name, options.playbook);
  } catch (error) {
    if (error.code === "ENOENT") return freshSession(name, options.playbook);
    throw error;
  }
}

function normalize(data, name, playbook) {
  const base = freshSession(name, playbook);
  return {
    ...base,
    ...data,
    name: base.name,
    playbook: data.playbook || playbook || null,
    visited: Array.isArray(data.visited) ? data.visited : [],
    captured: Array.isArray(data.captured) ? data.captured : [],
    chain: Array.isArray(data.chain) ? data.chain : [],
    cursor: data.cursor && typeof data.cursor === "object" ? data.cursor : {},
    counters: data.counters && typeof data.counters === "object" ? data.counters : {},
  };
}

function saveSession(session) {
  const file = sessionPath(session.name);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  session.updated_at = nowIso();
  const temp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temp, `${JSON.stringify(session, null, 2)}\n`, "utf8");
  fs.renameSync(temp, file);
  return session;
}

function hasCaptured(session, id) {
  if (!id) return false;
  return session.captured.some((item) => item.id === id || item.url === id);
}

function markVisited(session, url) {
  if (url && !session.visited.includes(url)) session.visited.push(url);
}

function markCaptured(session, item) {
  if (!item || !item.id || hasCaptured(session, item.id)) return false;
  session.captured.push({
    id: item.id,
    url: item.url || "",
    title: item.title || "",
    playbook: item.playbook || session.playbook || "",
    at: nowIso(),
  });
  return true;
}

function pushChain(session, value) {
  if (value && !session.chain.includes(value)) session.chain.push(value);
}

module.exports = {
  nowIso,
  rootDir,
  sessionPath,
  freshSession,
  loadSession,
  saveSession,
  hasCaptured,
  markVisited,
  markCaptured,
  pushChain,
};

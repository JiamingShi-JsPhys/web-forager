"use strict";

// A small, dependency-free robots.txt reader for browser mode.
//
// Browser mode is read-only but it still navigates real sites, so the record
// has to be able to say whether robots.txt was consulted. It is consulted only
// with --strict-robots; without it the record states robots_checked: false and
// no network request is made. The parsing rules mirror the Python engine
// (RFC 9309 subset): longest matching pattern wins, ties go to Allow, an
// unreachable or 5xx robots.txt is denied conservatively.

const http = require("node:http");
const https = require("node:https");
const { URL } = require("node:url");

const USER_AGENT = "WebForager-Browser (Information Gathering; +https://github.com/JiamingShi-JsPhys/web-forager)";
const MAX_BYTES = 512_000;
const TIMEOUT_MS = 8000;
const MAX_REDIRECTS = 3;

function originOf(url) {
  const parsed = new URL(url);
  return `${parsed.protocol}//${parsed.host}`;
}

function robotsPath(url) {
  const parsed = new URL(url);
  return `${parsed.pathname || "/"}${parsed.search || ""}`;
}

function parseRobots(text, userAgent = USER_AGENT) {
  const groups = [];
  let current = null;

  for (const rawLine of String(text || "").split(/\r?\n/)) {
    const line = rawLine.split("#", 1)[0].trim();
    if (!line || !line.includes(":")) continue;
    const index = line.indexOf(":");
    const key = line.slice(0, index).trim().toLowerCase();
    const value = line.slice(index + 1).trim();

    if (key === "user-agent") {
      if (current === null || current.rules.length) {
        current = { agents: [], rules: [] };
        groups.push(current);
      }
      current.agents.push(value.toLowerCase());
    } else if (key === "allow" || key === "disallow") {
      if (current === null) continue;
      if (key === "disallow" && value === "") continue; // empty Disallow = no restriction
      current.rules.push({ allow: key === "allow", pattern: value });
    }
  }

  const score = (agent) => {
    const token = agent.trim().toLowerCase();
    if (!token) return -1;
    if (token === "*") return 0;
    const product = token.split("/", 1)[0].trim();
    return product && userAgent.toLowerCase().includes(product) ? product.length : -1;
  };

  let best = -1;
  let selected = [];
  for (const group of groups) {
    const value = group.agents.reduce((top, agent) => Math.max(top, score(agent)), -1);
    if (value < 0) continue;
    if (value > best) {
      best = value;
      selected = [group];
    } else if (value === best) {
      selected.push(group);
    }
  }

  const rules = [];
  for (const group of selected) {
    for (const rule of group.rules) rules.push({ ...rule, regex: compileRule(rule.pattern), specificity: rule.pattern.replace(/\*/g, "").length });
  }
  return { rules, source: "", note: selected.length ? "" : "no matching user-agent group", allowAll: false, denyAll: false };
}

function compileRule(pattern) {
  const anchored = pattern.endsWith("$");
  let core = anchored ? pattern.slice(0, -1) : pattern;
  if (!core.startsWith("/") && !core.startsWith("*")) core = `/${core}`;
  const escaped = core.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
  return new RegExp(`^${escaped}${anchored ? "$" : ""}`, "s");
}

function robotsAllows(policy, url) {
  if (policy.denyAll) return false;
  if (policy.allowAll || !policy.rules.length) return true;
  const path = robotsPath(url);
  let winner = null;
  for (const rule of policy.rules) {
    if (!rule.regex.test(path)) continue;
    if (winner === null || rule.specificity > winner.specificity) winner = rule;
    else if (rule.specificity === winner.specificity && rule.allow && !winner.allow) winner = rule;
  }
  return winner === null ? true : winner.allow;
}

function fetchText(url, redirects = 0) {
  return new Promise((resolve, reject) => {
    let parsed;
    try {
      parsed = new URL(url);
    } catch (error) {
      reject(error);
      return;
    }
    const client = parsed.protocol === "http:" ? http : https;
    const request = client.get(
      parsed,
      { headers: { "User-Agent": USER_AGENT, Accept: "text/plain,*/*;q=0.5" } },
      (response) => {
        const status = response.statusCode || 0;
        if (status >= 300 && status < 400 && response.headers.location) {
          response.resume();
          if (redirects >= MAX_REDIRECTS) {
            reject(new Error("too many robots.txt redirects"));
            return;
          }
          resolve(fetchText(new URL(response.headers.location, parsed).toString(), redirects + 1));
          return;
        }
        let body = "";
        let size = 0;
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          size += chunk.length;
          if (size > MAX_BYTES) {
            response.destroy();
            return;
          }
          body += chunk;
        });
        response.on("end", () => resolve({ status, body }));
        response.on("error", reject);
      },
    );
    request.setTimeout(TIMEOUT_MS, () => {
      request.destroy(new Error("robots.txt request timed out"));
    });
    request.on("error", reject);
  });
}

const cache = new Map();

async function checkRobots(url, options = {}) {
  const origin = originOf(url);
  const robotsUrl = `${origin}/robots.txt`;
  const agent = options.userAgent || USER_AGENT;
  const cached = cache.get(origin);
  if (cached) return { ...cached, allowed: robotsAllows(cached.policy, url), url };

  let status = 0;
  let note = "";
  let policy;
  try {
    const response = await fetchText(robotsUrl);
    status = response.status;
    if (status === 200) {
      policy = parseRobots(response.body, agent);
      note = policy.note || `robots.txt read (${policy.rules.length} rule(s))`;
    } else if (status === 401 || status === 403 || (status >= 500 && status < 600)) {
      policy = { rules: [], allowAll: false, denyAll: true, note: `HTTP ${status} on robots.txt` };
      note = policy.note;
    } else {
      policy = { rules: [], allowAll: true, denyAll: false, note: `HTTP ${status} on robots.txt` };
      note = policy.note;
    }
  } catch (error) {
    policy = {
      rules: [],
      allowAll: false,
      denyAll: true,
      note: `robots.txt unreachable (${error.message}); denied conservatively`,
    };
    note = policy.note;
  }

  const entry = { robots_url: robotsUrl, status, note, policy };
  cache.set(origin, entry);
  return { ...entry, url, allowed: robotsAllows(policy, url) };
}

function clearCache() {
  cache.clear();
}

module.exports = { USER_AGENT, parseRobots, robotsAllows, checkRobots, clearCache, originOf };

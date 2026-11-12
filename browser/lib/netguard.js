"use strict";

// Refuse browser navigation to this machine, the LAN or a cloud metadata
// service. The HTTP side has the same guard (scripts/engine.py); this one is
// used for page navigations and for every subresource Chromium asks for, so a
// hostile page cannot probe http://127.0.0.1:... from inside the browser.
//
// A host that does not resolve is left alone: the navigation fails on its own,
// and offline runs (and the test fixtures) must keep working.

const dns = require("node:dns").promises;
const net = require("node:net");

const { ActorError } = require("./errors");

const V4_RANGES = [
  "0.0.0.0/8",
  "10.0.0.0/8",
  "100.64.0.0/10",
  "127.0.0.0/8",
  "169.254.0.0/16",
  "172.16.0.0/12",
  "192.0.0.0/24",
  "192.0.2.0/24",
  "192.168.0.0/16",
  "198.18.0.0/15",
  "198.51.100.0/24",
  "203.0.113.0/24",
  "224.0.0.0/4",
  "240.0.0.0/4",
  "255.255.255.255/32",
].map((cidr) => {
  const [base, bits] = cidr.split("/");
  return { base: v4ToInt(base), mask: bitsToMask(Number(bits)) };
});

const DNS_TTL_MS = 60_000;
const dnsCache = new Map();

function v4ToInt(ip) {
  const parts = ip.split(".").map(Number);
  return (((parts[0] << 24) >>> 0) + (parts[1] << 16) + (parts[2] << 8) + parts[3]) >>> 0;
}

function bitsToMask(bits) {
  return bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
}

function isBlockedIpv4(ip) {
  const value = v4ToInt(ip);
  return V4_RANGES.some((range) => ((value & range.mask) >>> 0) === ((range.base & range.mask) >>> 0));
}

function isBlockedIpv6(raw) {
  let ip = raw.toLowerCase().split("%")[0];
  if (ip === "::1" || ip === "::") return true;
  const mapped = ip.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
  if (mapped) return isBlockedIpv4(mapped[1]);
  if (/^fe[89ab][0-9a-f]:/.test(ip)) return true; // fe80::/10
  if (/^f[cd][0-9a-f]{2}:/.test(ip)) return true; // fc00::/7
  if (/^ff[0-9a-f]{2}:/.test(ip)) return true; // ff00::/8
  if (ip.startsWith("2001:db8")) return true;
  if (ip.startsWith("64:ff9b")) return true;
  return false;
}

function isBlockedIp(ip) {
  if (net.isIPv4(ip)) return isBlockedIpv4(ip);
  if (net.isIPv6(ip)) return isBlockedIpv6(ip);
  return false;
}

function isLocalName(host) {
  const name = host.replace(/\.$/, "").toLowerCase();
  return (
    name === "localhost" ||
    name.endsWith(".localhost") ||
    name.endsWith(".local") ||
    name.endsWith(".internal") ||
    name === "metadata.google.internal"
  );
}

async function resolveHost(host) {
  const now = Date.now();
  const hit = dnsCache.get(host);
  if (hit && hit.until > now) return hit.addresses;
  const addresses = [];
  try {
    for (const entry of await dns.lookup(host, { all: true })) addresses.push(entry.address);
  } catch (error) {
    return []; // unresolvable: the request fails on its own
  }
  dnsCache.set(host, { addresses, until: now + DNS_TTL_MS });
  return addresses;
}

function allowPrivate() {
  return ["1", "true", "yes", "on"].includes(
    String(process.env.WEB_FORAGER_ALLOW_PRIVATE || "").trim().toLowerCase(),
  );
}

/** True when the URL is http(s) and points at a public address. */
async function isPublicRequestUrl(rawUrl, options = {}) {
  const allow = options.allowPrivate === undefined ? allowPrivate() : Boolean(options.allowPrivate);
  if (allow) return true;
  let parsed;
  try {
    parsed = new URL(String(rawUrl));
  } catch (error) {
    return false;
  }
  if (!/^https?:$/.test(parsed.protocol)) return true; // data:, blob:, about:
  const host = parsed.hostname.replace(/^\[|\]$/g, "");
  if (!host) return false;
  if (isLocalName(host)) return false;
  if (net.isIP(host)) return !isBlockedIp(host);
  const addresses = await resolveHost(host);
  return !addresses.some((address) => isBlockedIp(address));
}

/** Navigation entry point: throws an ActorError instead of returning a boolean. */
async function assertPublicUrl(rawUrl, options = {}) {
  let parsed;
  try {
    parsed = new URL(String(rawUrl));
  } catch (error) {
    throw new ActorError("unsafe_url", `invalid URL: ${rawUrl}`, "pass an absolute http(s) URL");
  }
  if (!/^https?:$/.test(parsed.protocol)) {
    throw new ActorError(
      "unsafe_url",
      `refusing non-http(s) URL: ${parsed.protocol}`,
      "only http and https pages are opened",
    );
  }
  const allow = options.allowPrivate === undefined ? allowPrivate() : Boolean(options.allowPrivate);
  if (allow) return;
  if (!(await isPublicRequestUrl(rawUrl, { allowPrivate: false }))) {
    throw new ActorError(
      "unsafe_url",
      `refusing ${parsed.hostname}: loopback, private, link-local and metadata addresses are blocked`,
      "use --allow-private only for a target you control; it is off by default",
    );
  }
}

module.exports = { assertPublicUrl, isPublicRequestUrl, isBlockedIp, isLocalName };

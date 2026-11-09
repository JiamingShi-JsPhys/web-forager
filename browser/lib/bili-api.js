"use strict";

// Bilibili's own search JSON, used before the result page is scraped.
//
// The page is a React app whose card markup changes without notice, and a
// screenshot-free snapshot of it yields "views + duration" instead of titles
// whenever the selectors drift. The public endpoint returns the same videos
// with stable fields, and it needs no login — only the `buvid3` cookie that any
// visit to the home page sets. Without that cookie the endpoint answers 412.

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
const HOME = "https://www.bilibili.com/";
const SEARCH = "https://api.bilibili.com/x/web-interface/search/type";

function disabled() {
  return String(process.env.WEB_FORAGER_BILI_API || "").toLowerCase() === "off";
}

function stripTags(value) {
  return String(value || "")
    .replace(/<[^>]*>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

async function collectCookies() {
  const jar = [];
  try {
    const response = await fetch(HOME, { headers: { "user-agent": UA }, redirect: "follow" });
    const raw =
      typeof response.headers.getSetCookie === "function"
        ? response.headers.getSetCookie()
        : String(response.headers.get("set-cookie") || "").split(/,(?=[^ ;]+=)/);
    for (const entry of raw) {
      const pair = String(entry).split(";")[0];
      if (pair.includes("=")) jar.push(pair.trim());
    }
  } catch (error) {
    // The search call still works without a cookie on some networks; if it does
    // not, the caller falls back to the page.
  }
  return jar.join("; ");
}

async function searchVideos(query, limit = 20) {
  if (disabled()) throw new Error("disabled");
  const cookie = await collectCookies();
  const url = `${SEARCH}?search_type=video&keyword=${encodeURIComponent(query)}&page=1`;
  const response = await fetch(url, {
    headers: {
      "user-agent": UA,
      referer: HOME,
      accept: "application/json",
      ...(cookie ? { cookie } : {}),
    },
  });
  if (!response.ok) throw new Error(`search API returned HTTP ${response.status}`);
  const payload = await response.json();
  if (payload.code !== 0) {
    throw new Error(`search API code ${payload.code}: ${payload.message || "no message"}`);
  }
  const items = (payload.data && payload.data.result) || [];
  return items.slice(0, limit).map((item) => ({
    title: stripTags(item.title),
    url: item.arcurl || `https://www.bilibili.com/video/${item.bvid}/`,
    bvid: item.bvid || "",
    author: item.author || "",
    play: item.play,
    duration: item.duration || "",
    description: stripTags(item.description),
    source: "bilibili-api",
  }));
}

module.exports = { searchVideos, stripTags, disabled };

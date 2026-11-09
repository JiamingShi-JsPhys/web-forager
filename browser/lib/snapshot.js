"use strict";

const {
  BILIBILI,
  LOGIN_WALL,
  BLOCKED,
  MIN_BODY_CHARS,
  DANMAKU,
} = require("./selectors");

function textOf(node) {
  if (!node) return "";
  return [node.name, node.text, node.label, node.title].filter(Boolean).join(" ").trim();
}

function allText(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  return [snapshot && snapshot.title, ...nodes.map(textOf)].filter(Boolean).join("\n");
}

function bvidFrom(value) {
  const text = String(value || "");
  const match = text.match(BILIBILI.videoPath) || text.match(BILIBILI.videoId);
  return match ? match[1] : "";
}

// A card links to the same video twice: once from the overlay that shows
// "views danmaku duration" and once from the title. Keep the readable one.
function isStatLine(text) {
  return /^[\d.]+[万亿]?\s+[\d.]+[万亿]?\s+\d{1,2}:\d{2}(?::\d{2})?$/.test(String(text || "").trim());
}

function findVideoCards(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const cards = new Map();
  for (const node of nodes) {
    const bvid = bvidFrom(node.href) || bvidFrom(textOf(node));
    if (!bvid) continue;
    const title = (node.name || node.text || bvid).replace(/\s+/g, " ").trim().slice(0, 160);
    const existing = cards.get(bvid);
    if (!existing) {
      cards.set(bvid, {
        bvid,
        title,
        url: `${BILIBILI.homeUrl}video/${bvid}`,
        locator: node.locator || node.href || node.name || bvid,
      });
      continue;
    }
    if (isStatLine(existing.title) && !isStatLine(title)) {
      existing.title = title;
      existing.locator = node.locator || node.href || node.name || bvid;
    }
  }
  return [...cards.values()];
}

function extractVideoMeta(snapshot) {
  const text = allText(snapshot);
  const url = (snapshot && snapshot.url) || "";
  const bvid = bvidFrom(url) || (findVideoCards(snapshot)[0] || {}).bvid || "";
  const heading = (snapshot && snapshot.nodes ? snapshot.nodes : []).find(
    (node) => /heading/i.test(node.role || "") && textOf(node).length > 2,
  );
  const title = (heading ? (heading.name || heading.text) : "") || (snapshot && snapshot.title) || bvid;
  const stats = {};
  const statPattern = new RegExp(BILIBILI.statLabels.source, BILIBILI.statLabels.flags);
  let match;
  while ((match = statPattern.exec(text)) !== null) {
    stats[match[2]] = match[1].replace(/\s+/g, "");
  }
  return { bvid, title: title.trim(), url, stats };
}

function findNextEpisode(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  return nodes.find((node) => BILIBILI.nextEpisode.test(textOf(node).trim())) || null;
}

function rankByQuery(cards, query) {
  const tokens = String(query || "")
    .toLowerCase()
    .split(/[\s,，、]+/)
    .filter((token) => token.length > 0);
  if (!tokens.length) return cards.slice();
  return cards
    .map((card) => {
      const title = card.title.toLowerCase();
      const score = tokens.reduce((sum, token) => sum + (title.includes(token) ? 1 : 0), 0);
      return { card, score };
    })
    .sort((left, right) => right.score - left.score)
    .map((entry) => entry.card);
}

function findLinks(snapshot, pattern) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const seen = new Set();
  const links = [];
  for (const node of nodes) {
    const href = String(node.href || "");
    if (!pattern.test(href) || seen.has(href)) continue;
    seen.add(href);
    const title = (node.name || node.text || href).replace(/\s+/g, " ").trim().slice(0, 160);
    links.push({ title, url: href, locator: node.locator || href || title });
  }
  return links;
}

function pageTitle(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const heading = nodes.find((node) => /heading/i.test(node.role || "") && (node.name || node.text));
  return ((heading && (heading.name || heading.text)) || (snapshot && snapshot.title) || "").trim();
}

function bodyText(snapshot, limit = 8000) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const parts = [];
  for (const node of nodes) {
    const text = textOf(node).replace(/\s+/g, " ").trim();
    if (text.length < 8 || BILIBILI.navWords.test(text)) continue;
    if (/^https?:\/\//.test(text)) continue;
    parts.push(text);
    if (parts.join("\n\n").length >= limit) break;
  }
  return parts.join("\n\n").slice(0, limit);
}

function hasLoginWall(snapshot) {
  return LOGIN_WALL.test(allText(snapshot));
}

function hasBlockedPage(snapshot) {
  return BLOCKED.test(allText(snapshot));
}

function isBlankPage(snapshot) {
  return bodyText(snapshot).trim().length < MIN_BODY_CHARS;
}

// Explain why a playbook found nothing: "login", "blocked" or "empty". The
// playbooks use this to choose between an error and a degraded run instead of
// returning a silent empty success.
function diagnoseEmpty(snapshot) {
  if (hasLoginWall(snapshot)) return "login";
  if (hasBlockedPage(snapshot)) return "blocked";
  if (isBlankPage(snapshot)) return "empty";
  return "no-match";
}

function findDanmaku(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const entries = [];
  const seen = new Set();
  const push = (time, text) => {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    const stamp = String(time || "").trim();
    if (!clean) return;
    const key = `${stamp} ${clean}`;
    if (seen.has(key)) return;
    seen.add(key);
    entries.push({ time: stamp, text: clean.slice(0, 200) });
  };

  for (const node of nodes) {
    // Preferred: a bridge that already structured the entry.
    if (node && (node.time !== undefined || node.timestamp !== undefined)) {
      push(node.time !== undefined ? node.time : node.timestamp, node.text !== undefined ? node.text : node.name);
      continue;
    }
    if (node && DANMAKU.roles.test(String(node.role || ""))) {
      push(node.time || "", node.name || node.text);
      continue;
    }
    // Fallback: a visible "mm:ss text" line.
    const text = textOf(node).replace(/\s+/g, " ").trim();
    if (!text) continue;
    for (const pattern of DANMAKU.textPatterns) {
      const match = text.match(pattern);
      if (match) {
        push(match[1], match[2]);
        break;
      }
    }
  }
  return entries;
}

function commentCandidates(snapshot) {
  const nodes = Array.isArray(snapshot && snapshot.nodes) ? snapshot.nodes : [];
  const seen = new Set();
  const comments = [];
  for (const node of nodes) {
    if (node.href) continue;
    const text = textOf(node).replace(/\s+/g, " ").trim();
    if (text.length < 2 || text.length > 500) continue;
    if (BILIBILI.chromeLines.test(text)) continue;
    if (seen.has(text)) continue;
    seen.add(text);
    comments.push(text);
  }
  return comments.slice(0, 60);
}

module.exports = {
  bvidFrom,
  textOf,
  allText,
  findVideoCards,
  extractVideoMeta,
  findNextEpisode,
  rankByQuery,
  commentCandidates,
  findLinks,
  pageTitle,
  bodyText,
  hasLoginWall,
  hasBlockedPage,
  isBlankPage,
  diagnoseEmpty,
  findDanmaku,
};

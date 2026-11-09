"use strict";

const { ActorError } = require("../lib/errors");
const { guardedGoto, guardedScroll } = require("../lib/safety");
const { extractVideoMeta, commentCandidates, pageTitle, bodyText, hasLoginWall, diagnoseEmpty } = require("../lib/snapshot");
const { markCaptured, markVisited } = require("../lib/session");

// A page can swap its document after goto (login walls and verification pages
// do exactly that), which kills the evaluate that reads it. Classify the failure
// by where the page actually is, instead of surfacing a bare navigation error.
const LOGIN_URL = /(account\/unhuman|website-login|need_login|passport|signin|sign_in|\/login)/i;
const BLOCK_URL = /(captcha|verify|antispider|antibot|unhuman|security-check|\/412)/i;

async function currentUrlOf(ctx) {
  try {
    if (ctx && ctx.backend && typeof ctx.backend.currentUrl === "function") {
      return await ctx.backend.currentUrl();
    }
  } catch (error) {
    // The bridge may already be gone; the caller still gets a classified error.
  }
  return "";
}

async function snapshotSafe(ctx, where) {
  try {
    return await ctx.backend.snapshot();
  } catch (error) {
    const url = await currentUrlOf(ctx);
    if (url && LOGIN_URL.test(url)) {
      throw new ActorError(
        "login_required",
        `${where} redirected to a login wall (${url})`,
        "Use a logged-in bridge (CDP or a persistent profile), or open a public URL directly.",
      );
    }
    if (url && BLOCK_URL.test(url)) {
      throw new ActorError(
        "blocked",
        `${where} redirected to a verification page (${url})`,
        "Wait and retry later, or reuse a logged-in profile. web-forager does not solve challenges.",
      );
    }
    throw new ActorError(
      "navigation",
      `the page changed while reading ${where}${url ? ` (now at ${url})` : ""}: ${error.message}`,
      "Retry the playbook; the site redirected during the snapshot.",
    );
  }
}

function videoMarkdown(meta, comments) {
  const lines = [`# ${meta.title}`, ""];
  if (meta.bvid) lines.push(`- BV: ${meta.bvid}`);
  if (meta.url) lines.push(`- URL: ${meta.url}`);
  for (const [key, value] of Object.entries(meta.stats || {})) lines.push(`- ${key}: ${value}`);
  if (comments.length) {
    lines.push("", "## Visible comments", "");
    for (const comment of comments) lines.push(`- ${comment}`);
  }
  return lines.join("\n");
}

async function captureCurrent(ctx, options = {}) {
  const scrolls = Number(options.commentScrolls === undefined ? 3 : options.commentScrolls);
  let snapshot = await ctx.backend.snapshot();
  const meta = extractVideoMeta(snapshot);
  if (!meta.bvid && hasLoginWall(snapshot)) {
    throw new ActorError(
      "login_required",
      "the video page asked for credentials before the player loaded",
      "Use a logged-in extension bridge, or open a public URL with the HTTP mode adapter.",
    );
  }
  const comments = [];
  const seen = new Set();
  for (let index = 0; index <= scrolls; index += 1) {
    for (const comment of commentCandidates(snapshot)) {
      if (!seen.has(comment)) {
        seen.add(comment);
        comments.push(comment);
      }
    }
    if (index < scrolls) {
      await guardedScroll(ctx, 700);
      snapshot = await ctx.backend.snapshot();
    }
  }

  const record = ctx.capture({
    playbook: options.playbook || "bili-video",
    url: meta.url || (snapshot && snapshot.url) || "",
    metadata: { bvid: meta.bvid, title: meta.title, stats: meta.stats },
    markdown: videoMarkdown(meta, comments),
    warnings: meta.bvid ? [] : ["no BV id found on the page"],
  });
  if (meta.bvid) markCaptured(ctx.session, { id: meta.bvid, url: meta.url, title: meta.title, playbook: options.playbook });

  return { record, meta, snapshot, comments };
}

async function openAndCapture(ctx, url, options = {}) {
  await guardedGoto(ctx, url);
  markVisited(ctx.session, url);
  return captureCurrent(ctx, options);
}

async function capturePage(ctx, options = {}) {
  const snapshot = await ctx.backend.snapshot();
  const title = pageTitle(snapshot) || options.url || "page";
  const body = bodyText(snapshot);
  if (!body && hasLoginWall(snapshot)) {
    throw new ActorError(
      "login_required",
      `${options.site || "the site"} asked for credentials before showing the page`,
      "Use a logged-in extension bridge, or open a public URL directly.",
    );
  }
  const reason = body ? "" : diagnoseEmpty(snapshot);
  const record = ctx.capture({
    playbook: options.playbook || "page",
    url: (snapshot && snapshot.url) || options.url || "",
    metadata: { site: options.site || "", title },
    markdown: body || "(no readable text extracted from the snapshot)",
    warnings: body ? [] : [`no readable text extracted from the snapshot (${reason})`],
  });
  markCaptured(ctx.session, {
    id: options.url || (snapshot && snapshot.url) || title,
    url: options.url || (snapshot && snapshot.url) || "",
    title,
    playbook: options.playbook,
  });
  return { record, snapshot, title, body, status: body ? "ok" : "degraded", reason };
}

module.exports = { captureCurrent, openAndCapture, capturePage, videoMarkdown };

module.exports.snapshotSafe = snapshotSafe;

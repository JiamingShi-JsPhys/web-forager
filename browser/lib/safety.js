"use strict";

const { ActorError } = require("./errors");

const WRITE_PATTERNS = [
  /点赞/,
  /投币/,
  /收藏/,
  /关注/,
  /分享/,
  /转发/,
  /评论/,
  /弹幕/,
  /发布/,
  /三连/,
  /\blike\b/i,
  /\bcoin\b/i,
  /\bfavorite\b/i,
  /\bfollow\b/i,
  /\bshare\b/i,
  /\bcomment\b/i,
  /\bdanmaku\b/i,
  /\bpublish\b/i,
];

function actionText(node) {
  if (!node) return "";
  return [node.name, node.text, node.label, node.title, node.href]
    .filter(Boolean)
    .join(" ")
    .trim();
}

function isWriteAction(node) {
  const text = actionText(node);
  return WRITE_PATTERNS.some((pattern) => pattern.test(text));
}

async function rateLimit(ctx) {
  const minimum = ctx.options.minInterval === undefined ? 1000 : Number(ctx.options.minInterval);
  if (!Number.isFinite(minimum) || minimum <= 0) {
    ctx.lastActionAt = Date.now();
    return;
  }
  const last = ctx.lastActionAt || 0;
  const wait = last + minimum - Date.now();
  if (wait > 0) await ctx.sleep(wait);
  ctx.lastActionAt = Date.now();
}

async function guardedClick(ctx, node, options = {}) {
  if (!node) throw new ActorError("capture", "click target not found");
  if (isWriteAction(node) && !ctx.options.allowWrite && !options.confirm) {
    throw new ActorError(
      "confirmation_required",
      `refusing write-like action: ${actionText(node).slice(0, 120)}`,
      "M1 is read-only by default. Re-run with --allow-write only after the user explicitly authorises this action.",
    );
  }
  await rateLimit(ctx);
  ctx.trace.push({ action: "click", target: actionText(node).slice(0, 200), at: new Date().toISOString() });
  const locator = node.locator || node.id || node.name;
  return ctx.backend.click(locator);
}

async function guardedGoto(ctx, url) {
  if (ctx.options && ctx.options.strictRobots) {
    const { checkRobots } = require("./robots");
    const decision = await checkRobots(url);
    const entry = {
      url,
      robots_url: decision.robots_url,
      status: decision.status,
      allowed: decision.allowed,
      note: decision.note || "",
    };
    ctx.compliance.checks.push(entry);
    ctx.compliance.robots_checked = true;
    if (!decision.allowed) {
      throw new ActorError(
        "robots_denied",
        `robots.txt disallows ${url}`,
        `${decision.robots_url}: ${decision.note || "matched a Disallow rule"}. Drop --strict-robots to browse without the check, or choose another target.`,
      );
    }
  }
  await rateLimit(ctx);
  ctx.trace.push({ action: "goto", url, at: new Date().toISOString() });
  return ctx.backend.goto(url);
}

async function guardedScroll(ctx, dy) {
  await rateLimit(ctx);
  ctx.trace.push({ action: "scroll", dy, at: new Date().toISOString() });
  return ctx.backend.scroll(dy);
}

module.exports = {
  WRITE_PATTERNS,
  actionText,
  isWriteAction,
  rateLimit,
  guardedClick,
  guardedGoto,
  guardedScroll,
};

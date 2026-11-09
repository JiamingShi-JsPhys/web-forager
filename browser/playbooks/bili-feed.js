"use strict";

const { ActorError } = require("../lib/errors");
const { guardedGoto, guardedScroll } = require("../lib/safety");
const { findVideoCards, isBlankPage, hasBlockedPage, hasLoginWall } = require("../lib/snapshot");
const { BILIBILI } = require("../lib/selectors");
const { hasCaptured, markCaptured, markVisited } = require("../lib/session");

const NAME = "bili-feed";

module.exports = {
  name: NAME,
  description: "Open the Bilibili home feed, scroll screen by screen, and capture each unseen video card.",
  requires: [],

  async run(ctx) {
    const url = ctx.options.url || BILIBILI.homeUrl;
    const maxItems = Number(ctx.options.maxItems || 10);
    const maxScreens = Number(ctx.options.maxScreens || 3);

    await guardedGoto(ctx, url);
    markVisited(ctx.session, url);

    let captured = 0;
    let screens = 0;
    let lastSnapshot = null;
    for (let screen = 0; screen < maxScreens && captured < maxItems; screen += 1) {
      const snapshot = await ctx.backend.snapshot();
      lastSnapshot = snapshot;
      screens += 1;
      for (const card of findVideoCards(snapshot)) {
        if (captured >= maxItems) break;
        if (hasCaptured(ctx.session, card.bvid)) continue;
        ctx.capture({
          playbook: NAME,
          url: card.url,
          metadata: { bvid: card.bvid, title: card.title },
          markdown: `- ${card.title}\n- ${card.url}`,
        });
        markCaptured(ctx.session, {
          id: card.bvid,
          url: card.url,
          title: card.title,
          playbook: NAME,
        });
        captured += 1;
      }
      if (screen + 1 < maxScreens && captured < maxItems) await guardedScroll(ctx, 900);
    }

    if (captured === 0 && lastSnapshot) {
      if (hasLoginWall(lastSnapshot)) {
        throw new ActorError(
          "login_required",
          "Bilibili home feed showed a login wall instead of video cards",
          "Use a logged-in extension bridge, or rely on the HTTP mode adapter which reads public pages.",
        );
      }
      const reason = hasBlockedPage(lastSnapshot) ? "blocked" : isBlankPage(lastSnapshot) ? "empty" : "no-match";
      ctx.warn(`degraded: no video cards found after ${screens} screen(s) (${reason})`);
      return { summary: { captured: 0, screens, max_items: maxItems, status: "degraded", reason } };
    }

    return { summary: { captured, screens, max_items: maxItems, status: "ok" } };
  },
};

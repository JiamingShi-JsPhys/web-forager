"use strict";

const { ActorError } = require("../lib/errors");
const { guardedGoto } = require("../lib/safety");
const { WECHAT, MIN_BODY_CHARS } = require("../lib/selectors");
const { pageTitle, bodyText, diagnoseEmpty } = require("../lib/snapshot");
const { markVisited } = require("../lib/session");
const { capturePage, snapshotSafe } = require("./shared");

const NAME = "wechat-dig";

module.exports = {
  name: NAME,
  description:
    "Open one WeChat article link, report its environment-check wall instead of recycling it, and capture the article text.",
  requires: ["url"],

  async run(ctx) {
    const url = String(ctx.options.url || "").trim();
    if (!url) {
      throw new ActorError("argument", "wechat-dig needs --url with a WeChat article link");
    }
    let host = "";
    try {
      host = new URL(url).hostname;
    } catch (error) {
      throw new ActorError("argument", `not a URL: ${url}`);
    }
    if (!WECHAT.host.test(host)) {
      throw new ActorError(
        "argument",
        "wechat-dig only opens weixin.qq.com links; use the HTTP fetch action for other sites",
      );
    }

    await guardedGoto(ctx, url);
    markVisited(ctx.session, url);
    const snapshot = await snapshotSafe(ctx, "the WeChat article");

    const title = pageTitle(snapshot) || "";
    const text = bodyText(snapshot);
    const finalUrl = (snapshot && snapshot.url) || url;
    if (WECHAT.captchaUrl.test(finalUrl) || WECHAT.verification.test(`${title}\n${text}`)) {
      throw new ActorError(
        "blocked",
        "WeChat returned its environment-check page instead of the article",
        "Open the article once in the profile started by browser/launch_chrome.py and complete the check yourself, then rerun. web-forager does not solve challenges.",
      );
    }

    const reason = text.trim().length < MIN_BODY_CHARS ? diagnoseEmpty(snapshot) : "";
    if (reason === "login") {
      throw new ActorError(
        "login_required",
        "WeChat asked for credentials before showing the article",
        "Use a profile that is already signed in, or open the article in the WeChat client.",
      );
    }
    if (reason === "blocked") {
      throw new ActorError(
        "blocked",
        "WeChat showed an anti-bot or error page instead of the article",
        "Wait and retry later, or reuse a profile that has passed the check. web-forager does not solve challenges.",
      );
    }

    const page = await capturePage(ctx, { url, site: "wechat", playbook: NAME });
    return {
      summary: {
        url: page.record.url,
        title: page.title,
        chars: page.body.length,
        status: page.status,
        reason: page.reason || "",
      },
    };
  },
};

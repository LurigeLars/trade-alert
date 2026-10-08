/* Read a fixed public account URL inside an already open first-party tab.
 * No login automation, proxy rotation, Cloudflare bypass, cookies extraction,
 * Chrome debugging protocol, or off-origin requests. Background tabs may be
 * throttled/suspended: 30 seconds is a desired interval, not a guarantee.
 */
(() => {
  "use strict";
  const ACCOUNT_ID = "107780257626128497";
  const API = "https://truthsocial.com/api/v1/accounts/" + ACCOUNT_ID +
              "/statuses?exclude_replies=true&limit=25";
  const path = location.pathname;
  if (location.hostname !== "truthsocial.com" ||
      (path !== "/@realDonaldTrump" &&
       path !== "/api/v1/accounts/" + ACCOUNT_ID + "/statuses")) {
    return;
  }
  // Exclude nested re-execution from pages that dynamically load scripts.
  if (window.__tradeAlertPublicFeedReaderStarted) return;
  window.__tradeAlertPublicFeedReaderStarted = true;
  const MAX_ITEMS = 25;
  const INTERVAL_MS = 30000;
  let failures = 0;
  let stopped = false;

  const report = (type, payload) => window.postMessage({
    channel: "trade-alert-public-feed-v1",
    type,
    ...payload
  }, location.origin);

  async function poll() {
    if (stopped || location.origin !== "https://truthsocial.com") return;
    try {
      const start = performance.now();
      const response = await fetch(API, {
        credentials: "same-origin",
        cache: "no-store",
        headers: {Accept: "application/json"}
      });
      if (!response.ok) {
        report("health", {status: "HTTP_" + response.status});
        if ([401, 403, 429].includes(response.status)) {
          stopped = true; // Stop at refusal, do not change identity or retry.
        } else {
          failures = Math.min(failures + 1, 4);
        }
      } else {
        const rows = await response.json();
        if (!Array.isArray(rows) || rows.length === 0) {
          throw Error("empty or non-array account response");
        }
        const posts = rows.slice(0, MAX_ITEMS).map(row => ({
          id: row?.id,
          created_at: row?.created_at,
          visibility: row?.visibility,
          account: {
            id: row?.account?.id,
            acct: row?.account?.acct,
            username: row?.account?.username
          },
          content: row?.content,
          media_attachments: Array.isArray(row?.media_attachments)
            ? row.media_attachments.slice(0, 1).map(media => ({type: media.type}))
            : []
        }));
        report("posts", {posts});
        report("health", {
          status: "HTTP_200",
          count: posts.length,
          elapsed_ms: Math.round(performance.now() - start)
        });
        failures = 0;
      }
    } catch {
      report("health", {status: "ERROR"});
      failures = Math.min(failures + 1, 4);
    }
    if (!stopped) {
      setTimeout(poll, Math.min(600000, INTERVAL_MS * 2 ** failures));
    }
  }

  poll();
})();
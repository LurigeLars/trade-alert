/* Isolated-world forwarding only. No direct filesystem or credential reads. */
(() => {
  "use strict";
  if (location.origin !== "https://truthsocial.com") return;
  const ch = "trade-alert-public-feed-v1";
  // Reloading an unpacked extension invalidates content scripts in already
  // open tabs. Detach this stale listener if Chrome rejects runtime access.
  const forward = event => {
    if (event.source !== window || event.origin !== location.origin) return;
    const msg = event.data;
    if (!msg || msg.channel !== ch) return;
    if (msg.type === "monitor-mode-query") {
      const requestId = msg.requestId;
      if (!Number.isSafeInteger(requestId) || requestId < 1) return;
      // Only the isolated content script can query the extension's state.
      // The page receives a boolean, never cookies or extension storage.
      void (async () => {
        let allowed = false;
        try {
          const response = await chrome.runtime.sendMessage({kind: "monitor_mode"});
          allowed = response?.tabAllowed === true;
        } catch {
          // Old content-script contexts can become invalid after reload.
          // Fail closed: never add a second browser poller.
        }
        window.postMessage({
          channel: ch, type: "monitor-mode-response",
          requestId, tabAllowed: allowed
        }, location.origin);
      })();
      return;
    }
    if (msg.type !== "posts" && msg.type !== "health") return;
    if (msg.type === "posts" &&
        (!Array.isArray(msg.posts) || msg.posts.length > 25)) return;
    const safe = msg.type === "health"
      ? {kind: "health", status: String(msg.status || "").slice(0, 20),
         count: Number(msg.count || 0)}
      : {kind: "posts", posts: msg.posts};
    try {
      const pending = chrome.runtime.sendMessage(safe);
      // A live extension can transiently reject a message. An invalidated
      // context is permanent: detach until the page is loaded again.
      if (pending && typeof pending.catch === "function") {
        pending.catch(error => {
          if (String(error?.message || "").includes("Extension context invalidated")) {
            window.removeEventListener("message", forward);
          }
        });
      }
    } catch {
      // After an extension reload the old isolated world can still receive
      // page events, but cannot message the new extension service worker.
      // Do not flood chrome://extensions with uncaught errors.
      window.removeEventListener("message", forward);
    }
  };
  window.addEventListener("message", forward);
})();
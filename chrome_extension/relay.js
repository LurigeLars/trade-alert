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
    if (!msg || msg.channel !== ch ||
        (msg.type !== "posts" && msg.type !== "health")) return;
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
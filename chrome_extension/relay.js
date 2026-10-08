/* Isolated-world forwarding only. No direct filesystem or credential reads. */
(() => {
  "use strict";
  if (location.origin !== "https://truthsocial.com") return;
  const ch = "trade-alert-public-feed-v1";
  window.addEventListener("message", event => {
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
    chrome.runtime.sendMessage(safe).catch(() => {});
  });
})();
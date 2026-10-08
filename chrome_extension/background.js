/* Transfer only new, public account posts to Chrome's Downloads/TradeAlertChrome.
 * Data is untrusted on both sides. No browser cookies or tokens leave Chrome.
 */
"use strict";

const ID = "107780257626128497";
const NAME = "realDonaldTrump";
const POST_ID = /^[0-9]{10,24}$/;
const MAX_SEEN = 400;
let sequence = Promise.resolve();

function verified(post) {
  const name = post?.account?.acct || post?.account?.username;
  return post && POST_ID.test(String(post.id || "")) &&
    String(post.account?.id) === ID &&
    typeof name === "string" && name.toLowerCase() === NAME.toLowerCase() &&
    post.visibility === "public" &&
    typeof post.content === "string" &&
    typeof post.created_at === "string" &&
    Number.isFinite(Date.parse(post.created_at));
}

function validSender(sender) {
  try {
    const url = new URL(sender.url);
    return url.origin === "https://truthsocial.com" &&
      (url.pathname === "/@realDonaldTrump" ||
       url.pathname === "/api/v1/accounts/" + ID + "/statuses");
  } catch {
    return false;
  }
}

async function health(status) {
  let badge = "?";
  let color = "#777777";
  if (status === "HTTP_200") { badge = "ON"; color = "#228b22"; }
  else if (["HTTP_401","HTTP_403","HTTP_429"].includes(status)) {
    badge = "403"; color = "#b00020";
  } else if (status === "ERROR") { badge = "ERR"; color = "#b00020"; }
  await chrome.action.setBadgeText({text: badge});
  await chrome.action.setBadgeBackgroundColor({color});
  await chrome.action.setTitle({
    title: "Trade Alert Chrome: " + status +
      " (Chrome page must remain open; background timers can be delayed)"
  });
}

async function ingest(posts) {
  const values = await chrome.storage.local.get(["truthSeenIds"]);
  const initialized = Array.isArray(values.truthSeenIds);
  const seen = initialized ? values.truthSeenIds : [];
  const known = new Set(seen);
  const eligible = [];
  const rows = posts.filter(verified);
  if (!initialized) {
    await chrome.storage.local.set({
      truthSeenIds: rows.map(p => String(p.id)).slice(0, MAX_SEEN)
    });
    // First collection establishes a cursor; no old-news notifications.
    return {status: "BASELINED", count: rows.length};
  }
  const now = Date.now();
  for (const p of rows) {
    const pid = String(p.id);
    if (known.has(pid)) continue;
    const age = now - Date.parse(p.created_at);
    // Skip old/future content, keeping a bounded post-ID cursor.
    if (age >= -120000 && age <= 300000) {
      eligible.push({
        id: pid,
        created_at: p.created_at,
        visibility: "public",
        account: {id: ID, username: NAME, acct: NAME},
        content: p.content.slice(0, 10000),
        media_attachments: Array.isArray(p.media_attachments)
          ? p.media_attachments.slice(0, 1).map(x => ({type: x.type}))
          : []
      });
    }
    known.add(pid);
  }
  const downloaded = [];
  for (const post of eligible.slice(0, 12)) {
    const json = JSON.stringify(post);
    if (json.length > 12000) continue;
    try {
      await chrome.downloads.download({
        url: "data:application/json;charset=utf-8," + encodeURIComponent(json),
        filename: "TradeAlertChrome/post-" + post.id + ".json",
        conflictAction: "overwrite",
        saveAs: false
      });
      downloaded.push(post.id);
    } catch (err) {
      // Do not record unseen messages as handled after failed transfer.
      known.delete(post.id);
      console.warn("Trade Alert Chrome transfer failed:", err?.message || "unknown");
    }
  }
  // Even skipped old/irrelevant posts get a cursor so they cannot replay.
  await chrome.storage.local.set({
    truthSeenIds: [...known].slice(-MAX_SEEN)
  });
  return {status: "TRANSFERRED", count: downloaded.length};
}

async function handle(msg, sender) {
  if (!validSender(sender) || !msg || typeof msg !== "object") {
    return {status: "IGNORED"};
  }
  if (msg.kind === "health") {
    const status = String(msg.status || "").slice(0, 20);
    await health(status);
    return {status};
  }
  if (msg.kind !== "posts" || !Array.isArray(msg.posts) ||
      msg.posts.length > 25) return {status: "INVALID"};
  return ingest(msg.posts);
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  sequence = sequence.catch(() => {}).then(() => handle(msg, sender));
  sequence.then(sendResponse).catch(err => {
    console.warn("Trade Alert Chrome: message failed:", err?.message || "unknown");
    sendResponse({status: "ERROR"});
  });
  return true;
});

chrome.action.onClicked.addListener(() => {
  chrome.tabs.create({url: "https://truthsocial.com/@realDonaldTrump"});
});
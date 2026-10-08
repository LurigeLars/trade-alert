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
      known.add(post.id);
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
  if (!msg || typeof msg !== "object") return {status: "IGNORED"};
  if (sender.id === chrome.runtime.id &&
      sender.url === chrome.runtime.getURL("popup.html")) {
    if (msg.kind === "background_status") return backgroundStatus();
    if (msg.kind === "background_test") return runBackgroundFetch({enableOnSuccess: true});
    if (msg.kind === "background_off") return setBackgroundEnabled(false);
    if (msg.kind === "open_tab") {
      await chrome.tabs.create({url: "https://truthsocial.com/@realDonaldTrump"});
      return {status: "TAB_OPENED"};
    }
    return {status: "IGNORED"};
  }
  if (!validSender(sender)) return {status: "IGNORED"};
  if (msg.kind === "health") {
    const status = String(msg.status || "").slice(0, 20);
    const prefs = await chrome.storage.local.get(["truthBackgroundEnabled"]);
    // A success from a visible page is NOT evidence the tab-free source works.
    if (!prefs.truthBackgroundEnabled) await health(status);
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


/* Chrome 120+ MV3 alarms can wake a service worker every 0.5 minutes. This
 * experiment MUST be enabled explicitly via the popup. A successful tab
 * request does not authorize us to assume background fetch will work.
 */
const BACKGROUND_ALARM = "truth-social-public-posts";
const BACKGROUND_ENDPOINT = "https://truthsocial.com/api/v1/accounts/" + ID +
                            "/statuses?exclude_replies=true&limit=25";
let inFlight = false;

async function backgroundStatus() {
  const values = await chrome.storage.local.get([
    "truthBackgroundEnabled", "truthBackgroundLastStatus",
    "truthBackgroundLastChecked"
  ]);
  return {
    enabled: values.truthBackgroundEnabled === true,
    status: values.truthBackgroundLastStatus || "NOT_TESTED",
    checked: values.truthBackgroundLastChecked || null
  };
}

async function paintBackground(status) {
  const denied = ["HTTP_401", "HTTP_403", "HTTP_429"].includes(status);
  await chrome.action.setBadgeText({
    text: status === "HTTP_200" ? "BG" : denied ? "403" : "ERR"
  });
  await chrome.action.setBadgeBackgroundColor({
    color: status === "HTTP_200" ? "#228b22" : "#b00020"
  });
  await chrome.action.setTitle({
    title: status === "HTTP_200"
      ? "Trade Alert: bakgrundsläge aktivt (Chrome måste vara igång)"
      : "Trade Alert: bakgrundshämtning " + status + " – kontrollera tillägget"
  });
}

async function setBackgroundEnabled(enabled) {
  if (enabled) {
    await chrome.storage.local.set({truthBackgroundEnabled: true});
    await chrome.alarms.create(BACKGROUND_ALARM, {periodInMinutes: 0.5});
    return {status: "ENABLED", enabled: true};
  }
  await chrome.storage.local.set({truthBackgroundEnabled: false});
  await chrome.alarms.clear(BACKGROUND_ALARM);
  await chrome.action.setBadgeText({text: "TAB"});
  await chrome.action.setBadgeBackgroundColor({color: "#777777"});
  return {status: "DISABLED", enabled: false};
}

async function runBackgroundFetch({enableOnSuccess = false} = {}) {
  if (inFlight) return {status: "BUSY", enabled: (await backgroundStatus()).enabled};
  inFlight = true;
  let status = "ERROR";
  let count = 0;
  try {
    // Deliberately no cookies, tokens, proxy rotation, or session spoofing.
    const response = await fetch(BACKGROUND_ENDPOINT, {
      credentials: "omit",
      cache: "no-store",
      headers: {"Accept": "application/json"},
      signal: AbortSignal.timeout(8000)
    });
    status = "HTTP_" + response.status;
    if (!response.ok) {
      if ([401, 403, 429].includes(response.status)) {
        await setBackgroundEnabled(false);
      }
    } else {
      const length = Number(response.headers.get("content-length") || 0);
      if (length > 524288) throw Error("oversized response");
      const body = await response.text();
      if (body.length > 524288) throw Error("oversized response");
      const posts = JSON.parse(body);
      if (!Array.isArray(posts) || !posts.length || posts.length > 25) {
        throw Error("invalid response shape");
      }
      count = posts.filter(verified).length;
      if (!count) throw Error("no verified public account records");
      await ingest(posts);
      if (enableOnSuccess) await setBackgroundEnabled(true);
    }
  } catch {
    status = "ERROR";
  } finally {
    inFlight = false;
  }
  await chrome.storage.local.set({
    truthBackgroundLastStatus: status,
    truthBackgroundLastChecked: new Date().toISOString()
  });
  await paintBackground(status);
  return {status, count, enabled: (await backgroundStatus()).enabled};
}

chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name !== BACKGROUND_ALARM) return;
  sequence = sequence.catch(() => {}).then(async () => {
    const state = await backgroundStatus();
    if (state.enabled) await runBackgroundFetch();
  });
});

async function restoreBackgroundAlarm() {
  const state = await backgroundStatus();
  if (state.enabled) {
    await chrome.alarms.create(BACKGROUND_ALARM, {periodInMinutes: 0.5});
  }
}

chrome.runtime.onInstalled.addListener(() => {
  restoreBackgroundAlarm().catch(() => {});
});
chrome.runtime.onStartup.addListener(() => {
  restoreBackgroundAlarm().catch(() => {});
});

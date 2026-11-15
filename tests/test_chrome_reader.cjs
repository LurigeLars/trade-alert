"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const reader = fs.readFileSync(path.join(__dirname, "../chrome_extension/reader.js"), "utf8");

function rig(initialAllowed, {pendingFetch = false, status = 200, modeError, pendingMode = false} = {}) {
  const timers = new Map(), messages = [], pageListeners = new Map();
  let permitted = initialAllowed, fetches = 0, timerId = 0, abortFetch, error = modeError;
  const window = {
    addEventListener(name, fn) {pageListeners.set(name, fn);},
    postMessage(data) {pageListeners.get("message")?.({source: window, origin: "https://truthsocial.com", data});}
  };
  vm.runInNewContext(reader, {
    window, location: {origin: "https://truthsocial.com", hostname: "truthsocial.com", pathname: "/@realDonaldTrump"},
    chrome: {runtime: {sendMessage(message) {
      messages.push(message);
      if (message.kind === "reader_mode") {
        if (error === "sync") throw Error("Extension context invalidated.");
        if (error) return Promise.reject(Error(error));
        if (pendingMode) return new Promise(() => {});
        return Promise.resolve({tabAllowed: permitted});
      }
      return Promise.resolve({status: "RECEIVED"});
    }}},
    fetch: async (url, options) => {
      fetches++;
      assert.equal(options.credentials, "same-origin");
      assert.equal(url, "https://truthsocial.com/api/v1/accounts/107780257626128497/statuses?exclude_replies=true&limit=25");
      if (pendingFetch) return new Promise((resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(Error("timed out")), {once: true});
      });
      return {ok: status === 200, status, async json() {return [{id: "117406186276133332",
        account: {id: "107780257626128497", acct: "realDonaldTrump"}, visibility: "public",
        content: "<p>Public test record</p>", created_at: new Date().toISOString()}];}};
    },
    AbortSignal: {timeout(ms) {
      assert.equal(ms, 8000);
      const controller = new AbortController(); abortFetch = () => controller.abort(); return controller.signal;
    }},
    setTimeout(fn, ms) {timers.set(++timerId, {fn, ms}); return timerId;},
    clearTimeout(id) {timers.delete(id);}, performance: {now() {return 250;}}
  });
  return {window, timers, messages, get fetches() {return fetches;},
    permit(value) {permitted = value;}, modeError(value) {error = value;},
    abortFetch() {assert.ok(abortFetch); abortFetch();},
    runTimer(ms) {
      const entry = [...timers].find(([, timer]) => timer.ms === ms);
      assert.ok(entry, `Missing ${ms}ms timer`); timers.delete(entry[0]); entry[1].fn();
    }};
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test("Active background monitoring denies tab fetching, then disabling resumes backup", async () => {
  const h = rig(false);
  await flush(); assert.equal(h.fetches, 0);
  h.permit(true); h.runTimer(30000); await flush();
  assert.equal(h.fetches, 1);
  assert.ok(h.messages.some(m => m.kind === "reader_posts"));
});

test("Repeated background-active polls never duplicate network requests", async () => {
  const h = rig(false); await flush();
  for (let i = 0; i < 3; i++) {h.runTimer(30000); await flush();}
  assert.equal(h.fetches, 0);
  assert.equal(h.messages.filter(m => m.kind === "reader_mode").length, 4);
});

test("Stalled backup request aborts, reports failure and schedules backoff", async () => {
  const h = rig(true, {pendingFetch: true}); await flush();
  assert.equal(h.fetches, 1); h.abortFetch(); await flush();
  assert.ok(h.messages.some(m => m.kind === "reader_health" && m.status === "ERROR"));
  assert.ok([...h.timers.values()].some(t => t.ms === 60000));
});

test("Unanswered mode request times out closed without fetching", async () => {
  const h = rig(true, {pendingMode: true}); await flush();
  h.runTimer(2500); await flush();
  assert.equal(h.fetches, 0);
  assert.ok([...h.timers.values()].some(t => t.ms === 30000));
});

test("Transient worker rejection fails closed and recovers on the next interval", async () => {
  const h = rig(true, {modeError: "No receiving end"}); await flush();
  assert.equal(h.fetches, 0); h.modeError(null); h.runTimer(30000); await flush();
  assert.equal(h.fetches, 1);
});

test("Synchronous and asynchronous invalidated contexts stop polling without uncaught errors", async () => {
  for (const modeError of ["sync", "Extension context invalidated."]) {
    const h = rig(true, {modeError}); await flush();
    assert.equal(h.fetches, 0); h.runTimer(30000); await flush();
    assert.equal(h.messages.length, 1);
  }
});

test("Real source refusals report directly and stop tab retries", async () => {
  for (const status of [401, 403, 429]) {
    const h = rig(true, {status}); await flush();
    assert.ok(h.messages.some(m => m.kind === "reader_health" && m.status === `HTTP_${status}`));
    assert.equal(h.timers.size, 0);
  }
});

test("Public page messages have no listener or route to the runtime", async () => {
  const h = rig(false); await flush();
  const before = h.messages.length;
  for (const data of [
    {channel: "trade-alert-public-feed-v1", type: "health", status: "HTTP_429"},
    {channel: "trade-alert-public-feed-v1", type: "posts", posts: [{id: "117406186276133333"}]},
    {kind: "reader_health", status: "HTTP_429"}, {kind: "reader_posts", posts: []}
  ]) h.window.postMessage(data);
  await flush(); assert.equal(h.messages.length, before); assert.equal(h.fetches, 0);
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, "../chrome_extension/manifest.json"), "utf8"));
  assert.ok(manifest.content_scripts.every(s => (s.world ?? "ISOLATED") === "ISOLATED"));
  assert.ok(manifest.content_scripts.every(s => !s.js.includes("relay.js")));
});

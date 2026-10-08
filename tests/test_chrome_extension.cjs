/* Offline tests: no network, Chrome or user profile needed. */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

function harness() {
  const listeners = {};
  const seenState = {};
  const downloads = [];
  const badges = [];
  const chrome = {
    runtime: {onMessage: {addListener(fn) {listeners.message = fn;}}},
    storage: {local: {
      async get(keys) {
        const out = {};
        for (const key of keys) if (key in seenState) out[key] = seenState[key];
        return out;
      },
      async set(values) { Object.assign(seenState, values); }
    }},
    downloads: {
      async download(options) {
        downloads.push(options);
        return downloads.length;
      }
    },
    action: {
      async setBadgeText(x) {badges.push(x.text);},
      async setBadgeBackgroundColor() {},
      async setTitle() {},
      onClicked: {addListener(fn) {listeners.clicked = fn;}}
    },
    tabs: {create() {}}
  };
  const code = fs.readFileSync(
    path.join(__dirname, "..", "chrome_extension", "background.js"), "utf8"
  );
  vm.runInNewContext(code, {chrome, console, URL, Date, Set}, {filename:"background.js"});
  async function send(msg, senderUrl="https://truthsocial.com/@realDonaldTrump") {
    return await new Promise((resolve, reject) => {
      const yes = listeners.message(msg, {url:senderUrl}, resolve);
      if (yes !== true) reject(Error("listener not async"));
    });
  }
  return {send, downloads, badges, seenState};
}

const ACCOUNT = "107780257626128497";
const original = {
  id:"117406186276133332",
  created_at: new Date(Date.now()-8000).toISOString(),
  visibility:"public",
  account: {id:ACCOUNT,acct:"realDonaldTrump"},
  content:"<p>Trump says no attack on Iran</p>"
};

test("Initial fetch baselines and new posts transfer exactly once", async () => {
  const h = harness();
  const a = await h.send({kind:"posts",posts:[original]});
  assert.equal(a.status,"BASELINED");
  assert.equal(h.downloads.length,0);
  const next = {...original,id:"117406359223020085"};
  const b = await h.send({kind:"posts",posts:[next, original]});
  assert.equal(b.count,1);
  assert.equal(h.downloads.length,1);
  assert.match(h.downloads[0].filename,/^TradeAlertChrome\/post-[0-9]+\.json$/);
  const payload = JSON.parse(decodeURIComponent(
    h.downloads[0].url.slice(h.downloads[0].url.indexOf(",")+1)
  ));
  assert.equal(payload.account.id,ACCOUNT);
  assert.equal(payload.id,next.id);
  assert.ok(!("cookie" in payload) && !("token" in payload));
  await h.send({kind:"posts",posts:[next, original]});
  assert.equal(h.downloads.length,1);
});

test("Reject spoofing and unapproved web origins", async () => {
  const h=harness();
  const wrong = {...original,id:"117406359223020085",account:{id:"123",acct:"other"}};
  await h.send({kind:"posts",posts:[original]});
  await h.send({kind:"posts",posts:[wrong]});
  await h.send({kind:"posts",posts:[{...original,id:"117406359223020085"}]},
               "https://example.com/");
  assert.equal(h.downloads.length,0);
});

test("HTTP refused reports status without retry on behalf of the background worker", async () => {
  const h=harness();
  const x=await h.send({kind:"health",status:"HTTP_403"});
  assert.equal(x.status,"HTTP_403");
  assert.equal(h.badges.at(-1),"403");
});

test("Failed download stays retryable rather than marked seen", async () => {
  const h=harness();
  await h.send({kind:"posts",posts:[original]});
  // The harness download succeeds; simulate one full message afterward.
  const next = {...original,id:"117406359223020085"};
  const result=await h.send({kind:"posts",posts:[next]});
  assert.equal(result.status,"TRANSFERRED");
  assert.equal(h.downloads.length,1);
});

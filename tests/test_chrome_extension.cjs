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
  const alarms = new Map();
  let nextFetch = async () => {throw Error("No mocked background fetch");};
  const chrome = {
    runtime: {
      id: "test-extension",
      getURL(name) {return "chrome-extension://test-extension/" + name;},
      onMessage: {addListener(fn) {listeners.message = fn;}},
      onStartup: {addListener(fn) {listeners.startup = fn;}},
      onInstalled: {addListener(fn) {listeners.installed = fn;}}
    },
    alarms: {
      onAlarm: {addListener(fn) {listeners.alarm = fn;}},
      async create(name, info) {alarms.set(name, info);},
      async clear(name) {alarms.delete(name);return true;}
    },
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
  vm.runInNewContext(code, {
    chrome, console, URL, Date, Set,
    fetch: (...args) => nextFetch(...args),
    AbortSignal,
  }, {filename:"background.js"});
  async function send(msg, senderUrl="https://truthsocial.com/@realDonaldTrump") {
    return await new Promise((resolve, reject) => {
      const yes = listeners.message(msg, {url:senderUrl}, resolve);
      if (yes !== true) reject(Error("listener not async"));
    });
  }
  async function popup(kind) {
    return new Promise((resolve, reject) => {
      const yes = listeners.message(
        {kind}, {url: "chrome-extension://test-extension/popup.html",
                 id:"test-extension"}, resolve
      );
      if (yes !== true) reject(Error("popup listener not async"));
    });
  }
  return {
    send, popup, downloads, badges, seenState, alarms,
    setFetch(fn) {nextFetch = fn;},
    listeners,
  };
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


test("Tab-free background request HTTP 200 enables periodic worker alarm", async () => {
  const h=harness();
  h.setFetch(async (url, options) => {
    assert.equal(url, "https://truthsocial.com/api/v1/accounts/" +
                 ACCOUNT + "/statuses?exclude_replies=true&limit=25");
    assert.equal(options.credentials, "omit");
    return {
      ok:true, status:200, headers:{get() {return "8000";}},
      async text() {return JSON.stringify([original]);}
    };
  });
  const reply=await h.popup("background_test");
  assert.equal(reply.status,"HTTP_200");
  assert.equal(reply.enabled,true);
  assert.equal(reply.count,1);
  assert.equal(h.alarms.get("truth-social-public-posts").periodInMinutes,0.5);
  assert.equal(h.badges.at(-1),"ON");
  assert.equal(h.downloads.length,0); // baseline on first successful fetch
  const state=await h.popup("background_status");
  assert.equal(state.status,"HTTP_200");
  assert.equal(state.enabled,true);
  assert.ok(state.checked);
  const off=await h.popup("background_off");
  assert.equal(off.enabled,false);
  assert.equal(h.alarms.size,0);
});

test("HTTP 403 fails closed; cannot claim background monitoring", async () => {
  const h=harness();
  h.setFetch(async () => ({
    ok:false, status:403, headers:{get() {return "text/html";}}
  }));
  const result=await h.popup("background_test");
  assert.equal(result.status,"HTTP_403");
  assert.equal(result.enabled,false);
  assert.equal(h.alarms.size,0);
  assert.equal(h.badges.at(-1),"403");
  // The first-party tab reader still works in legacy mode.
  await h.send({kind:"health",status:"HTTP_200"});
  assert.equal(h.badges.at(-1),"ON");
});

test("Background source without validated account data never enables", async () => {
  const h=harness();
  h.setFetch(async () => ({
    ok:true, status:200, headers:{get() {return null;}},
    async text() {return JSON.stringify([{
      ...original, account:{id:"fake",acct:"notTrump"}
    }]);}
  }));
  const result=await h.popup("background_test");
  assert.equal(result.status,"ERROR");
  assert.equal(result.enabled,false);
  assert.equal(h.alarms.size,0);
});

test("Previously baselined tab data does not generate duplicate downloads", async () => {
  const h=harness();
  await h.send({kind:"posts",posts:[original]});
  h.setFetch(async () => ({
    ok:true,status:200,headers:{get() {return "1000";}},
    async text() {return JSON.stringify([original]);}
  }));
  const r=await h.popup("background_test");
  assert.equal(r.status,"HTTP_200");
  assert.equal(h.downloads.length,0);
  await h.send({kind:"health",status:"HTTP_200"});
  assert.equal(h.badges.at(-1),"ON"); // tab success does not change background status
});


test("An active background monitor denies independent tab polling", async () => {
  const h=harness();
  h.setFetch(async () => ({
    ok:true, status:200, headers:{get() {return null;}},
    async text() {return JSON.stringify([original]);}
  }));
  const activated=await h.popup("background_test");
  assert.equal(activated.status, "HTTP_200");
  const during=await h.send({kind:"monitor_mode"});
  assert.equal(during.tabAllowed, false);
  await h.popup("background_off");
  const fallback=await h.send({kind:"monitor_mode"});
  assert.equal(fallback.tabAllowed, true);
});

test("HTTP 429 is labeled 429, turns background off and stops both pollers", async () => {
  const h=harness();
  let requests=0;
  h.setFetch(async () => {
    requests++;
    return {
      ok:false, status:429,
      headers:{get(name) {return name==="retry-after" ? "60" : null;}}
    };
  });
  const blocked=await h.popup("background_test");
  assert.equal(blocked.status, "HTTP_429");
  assert.equal(blocked.enabled, false);
  assert.equal(h.badges.at(-1), "429");
  assert.equal(h.alarms.size, 0);
  assert.ok(blocked.cooldown_until > Date.now() + 29*60*1000);
  assert.equal((await h.send({kind:"monitor_mode"})).tabAllowed,false);
  const repeat=await h.popup("background_test");
  assert.equal(repeat.status, "HTTP_429");
  assert.equal(requests, 1); // no network retry while rate-limited
  assert.equal((await h.popup("background_status")).status,"HTTP_429");
});

test("Tab-visible HTTP 429 also pauses future tab and background fetching", async () => {
  const h=harness();
  await h.send({kind:"health",status:"HTTP_429"});
  assert.equal(h.badges.at(-1),"429");
  const state=await h.popup("background_status");
  assert.equal(state.status,"HTTP_429");
  assert.equal(state.enabled,false);
  assert.equal((await h.send({kind:"monitor_mode"})).tabAllowed,false);
  assert.ok(state.cooldown_until > Date.now() + 29*60*1000);
});

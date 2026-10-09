"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const reader = fs.readFileSync(
  path.join(__dirname, "..", "chrome_extension", "reader.js"), "utf8"
);
const relay = fs.readFileSync(
  path.join(__dirname, "..", "chrome_extension", "relay.js"), "utf8"
);

function rig(initialAllowed) {
  const origin = "https://truthsocial.com";
  const listeners = new Map();
  const timers = [];
  const events = [];
  let permitted = initialAllowed;
  let fetches = 0;
  let modeChecks = 0;
  const location = {origin, hostname:"truthsocial.com", pathname:"/@realDonaldTrump"};
  const window = {
    addEventListener(name, fn) {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name).add(fn);
    },
    removeEventListener(name, fn) {
      listeners.get(name)?.delete(fn);
    },
    postMessage(data, target) {
      assert.equal(target,origin);
      events.push(data);
      if (data.type==="monitor-mode-query") {
        modeChecks++;
        queueMicrotask(() => window.postMessage({
          channel:"trade-alert-public-feed-v1",
          type:"monitor-mode-response",
          requestId:data.requestId,
          tabAllowed:permitted
        },origin));
      }
      for (const fn of (listeners.get("message")||[])) {
        fn({source:window,origin,data});
      }
    }
  };
  const fetch = async () => {
    fetches++;
    return {
      ok:true, status:200,
      async json() {
        return [{
          id:"117406186276133332",
          account:{id:"107780257626128497",acct:"realDonaldTrump"},
          visibility:"public",content:"<p>Iran announcement</p>",
          created_at:new Date().toISOString()
        }];
      }
    };
  };
  vm.runInNewContext(reader, {
    window, location, console, fetch,
    setTimeout(fn, ms) {timers.push({fn,ms});return timers.length;},
    clearTimeout() {},
    performance:{now(){return 250;}},
  }, {filename:"reader.js"});
  return {
    timers, events, get fetches(){return fetches;},
    get modeChecks(){return modeChecks;},
    permit(value){permitted=value;}
  };
}

async function flush() {
  await new Promise(resolve=>setImmediate(resolve));
}

test("The page skips API fetch when BG owns the poller", async () => {
  const h=rig(false);
  await flush();
  assert.equal(h.fetches,0);
  assert.equal(h.modeChecks,1);
  assert.ok(h.timers.some(t=>t.ms===30000));
  const next=h.timers.find(t=>t.ms===30000);
  h.permit(true);
  next.fn(); // after BG disabled, tab mode can now acquire
  await flush();
  assert.equal(h.fetches,1);
  assert.equal(h.modeChecks,2);
  assert.ok(h.events.some(e=>e.type==="posts"));
});

test("Repeated BG-active page polls never duplicate the background network requests", async () => {
  const h=rig(false);
  await flush();
  for(let i=0;i<3;i++){
    const t=h.timers.pop();
    assert.equal(t.ms,30000);
    t.fn();
    await flush();
  }
  assert.equal(h.fetches,0);
  assert.equal(h.modeChecks,4);
});

test("Relay reports service-worker mode without leaking extension settings", async () => {
  const origin="https://truthsocial.com";
  const callbacks=new Set();
  const outbound=[];
  const window={
    addEventListener(name,fn) {callbacks.add(fn);},
    removeEventListener(name,fn) {callbacks.delete(fn);},
    postMessage(data,target) {outbound.push({data,target});}
  };
  const location={origin};
  const chrome={runtime:{
    async sendMessage(message) {
      assert.equal(message.kind,"monitor_mode");
      return {tabAllowed:false, sensitiveToken:"must-not-forward"};
    }
  }};
  vm.runInNewContext(relay,{window,location,chrome,console},{filename:"relay.js"});
  for(const callback of callbacks) {
    callback({source:window,origin,data:{
      channel:"trade-alert-public-feed-v1",
      type:"monitor-mode-query",
      requestId:7
    }});
  }
  await flush();
  assert.equal(outbound.length,1);
  assert.equal(outbound[0].data.tabAllowed,false);
  assert.equal(outbound[0].data.requestId,7);
  assert.equal(outbound[0].target,origin);
  assert.equal(JSON.stringify(outbound).includes("sensitiveToken"),false);
});

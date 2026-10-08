"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

const relaySource = fs.readFileSync(
  path.join(__dirname, "..", "chrome_extension", "relay.js"), "utf8"
);

function setup(sendMessage) {
  const listeners = new Map();
  let calls = 0;
  const origin = "https://truthsocial.com";
  const window = {
    addEventListener(name, handler) {listeners.set(name, handler);},
    removeEventListener(name, handler) {
      if (listeners.get(name) === handler) listeners.delete(name);
    }
  };
  const location = {origin};
  const chrome = {runtime:{sendMessage(message) {
    calls++;
    return sendMessage(message);
  }}};
  vm.runInNewContext(relaySource, {window, location, chrome, console});
  const send = msg => {
    const handler = listeners.get("message");
    if (handler) handler({
      source:window, origin,
      data: {channel:"trade-alert-public-feed-v1", ...msg}
    });
  };
  return {send, listeners, get calls() {return calls;}};
}

test("stale extension context synchronous failure does not surface and detaches once", () => {
  const h=setup(() => {throw Error("Extension context invalidated.");});
  assert.doesNotThrow(() => h.send({type:"health",status:"HTTP_200"}));
  assert.equal(h.calls,1);
  assert.equal(h.listeners.has("message"),false);
  h.send({type:"health",status:"HTTP_200"});
  assert.equal(h.calls,1);
});

test("valid relay still forwards normal health and post messages", async () => {
  const messages=[];
  const h=setup(msg => {messages.push(msg);return Promise.resolve();});
  h.send({type:"health",status:"HTTP_200",count:20});
  h.send({type:"posts",posts:[{id:"117406186276133332"}]});
  await Promise.resolve();
  assert.equal(h.calls,2);
  assert.equal(messages[0].status,"HTTP_200");
  assert.equal(messages[1].posts.length,1);
  assert.equal(h.listeners.has("message"),true);
});

test("asynchronous invalidated-context rejection unregisters obsolete listener", async () => {
  const h=setup(() => Promise.reject(Error("Extension context invalidated.")));
  h.send({type:"health",status:"HTTP_200"});
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(h.listeners.has("message"),false);
});

test("transient async service worker refusal does not remove a live relay", async () => {
  const h=setup(() => Promise.reject(Error("No receiving end")));
  h.send({type:"health",status:"HTTP_200"});
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(h.listeners.has("message"),true);
});

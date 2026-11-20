"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const extension = path.resolve(__dirname, "../chrome_extension");
const source = fs.readFileSync(path.join(extension, "popup.js"), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));
async function popup(overrides = {}, options = {}) {
  const state = {enabled: true, status: "HTTP_200", checked: new Date().toISOString(),
    local_paired: true, tab_status: "NOT_TESTED", delivery_status: "QUEUED", ...overrides};
  const nodes = Object.fromEntries(["status", "power", "power-label", "open", "pair", "pair-code", "pair-feedback", "feedback", "pairing", "notice", "pair-status", "pairing-summary", "background-status", "checked", "tab-status", "delivery-status", "pair-form"].map(id => [id, {
    textContent: "", value: "", disabled: true, hidden: true, open: false, dataset: {}, attrs: {}, listeners: {},
    setAttribute(k,v) {this.attrs[k] = v;}, addEventListener(k,v) {this.listeners[k] = v;}, focus() {}
  }]));
  const calls = []; let closed = false;
  vm.runInNewContext(source, {
    document: {getElementById: id => nodes[id]}, window: {close() {closed = true;}},
    chrome: {runtime: {sendMessage: async message => {
      calls.push(message);
      if (message.kind === options.fail) throw Error("Synthetic worker failure");
      if (message.kind === "background_test") {
        state.status = options.activationStatus || "HTTP_200";
        state.checked = new Date().toISOString(); state.enabled = state.status === "HTTP_200";
      }
      if (message.kind === "background_off") state.enabled = false;
      if (message.kind === "pair_local") {
        if (options.pairStatus) return {status: options.pairStatus};
        state.local_paired = true; return {status: "PAIRED"};
      }
      if (message.kind === "open_tab") return {status: options.openStatus || "TAB_OPENED"};
      return {...state};
    }}}
  });
  await flush();
  return {nodes, calls, closed: () => closed};
}

test("paired popup has one accessible ON/OFF control and collapses setup", async () => {
  const {nodes, calls} = await popup();
  assert.equal(nodes.power.attrs["aria-checked"], "true");
  assert.equal(nodes["power-label"].textContent, "ON");
  assert.equal(nodes.pairing.open, false);
  assert.equal(nodes["pair-status"].textContent, "Paired");
  assert.equal(nodes.status.textContent, "Receiving public posts");
  assert.equal(nodes.notice.hidden, true);
  assert.deepEqual(calls.map(c => c.kind), ["background_status"]);
  await nodes.power.listeners.click();
  assert.equal(nodes["power-label"].textContent, "OFF");
  assert.equal(calls.at(-2).kind, "background_off");
  await nodes.power.listeners.click();
  assert.equal(calls.at(-2).kind, "background_test");
  assert.equal(nodes.power.attrs["aria-checked"], "true");
});

test("failed activation remains OFF and exposes the source failure", async () => {
  const {nodes} = await popup({enabled: false}, {activationStatus: "HTTP_403"});
  await nodes.power.listeners.click();
  assert.equal(nodes["power-label"].textContent, "OFF");
  assert.equal(nodes.status.dataset.tone, "error");
  assert.match(nodes.status.textContent, /Access denied/);
});

test("enabled setting does not claim source health when stale, failed or rate limited", async () => {
  for (const [state, expected] of [
    [{checked: new Date(Date.now()-121000).toISOString()}, "Waiting for a fresh check"],
    [{status: "ERROR"}, "Background source unavailable"],
    [{status: "HTTP_500"}, "Background source unavailable"],
    [{status: "HTTP_429", cooldown_until: Date.now()+1800000}, "Rate limited until"]
  ]) {
    const {nodes} = await popup(state);
    assert.ok(nodes.status.textContent.startsWith(expected));
    assert.notEqual(nodes.status.dataset.tone, "ok");
    assert.ok(!nodes.status.textContent.includes("—"));
  }
});

test("local delivery failures remain visible beside a healthy source", async () => {
  for (const delivery_status of ["BRIDGE_OFFLINE", "PAIR_REQUIRED"]) {
    const {nodes} = await popup({delivery_status});
    assert.equal(nodes.notice.hidden, false);
    assert.match(nodes.notice.textContent, /local delivery|Local delivery/);
  }
});

test("only a recent successful backup observation is called active", async () => {
  const {nodes} = await popup({enabled: false, tab_status: "HTTP_200", tab_checked: new Date().toISOString()});
  assert.equal(nodes.status.textContent, "Backup tab is active");
  const old = await popup({enabled: false, tab_status: "HTTP_200", tab_checked: new Date(Date.now()-121000).toISOString()});
  assert.equal(old.nodes.status.textContent, "Background monitoring is off");
});

test("missing pairing opens setup, and successful pairing clears the code and collapses it", async () => {
  const {nodes, calls} = await popup({local_paired: false});
  assert.equal(nodes.pairing.open, true);
  assert.equal(nodes.notice.hidden, false);
  nodes["pair-code"].value = "a".repeat(20);
  await nodes["pair-form"].listeners.submit({preventDefault() {}});
  assert.equal(nodes["pair-code"].value, "");
  assert.equal(calls.find(c => c.kind === "pair_local").code, "A".repeat(20));
  assert.equal(nodes.pairing.open, false);
  assert.equal(nodes.notice.hidden, true);
});

test("invalid and rejected pairing attempts leave setup available without retaining codes", async () => {
  const invalid = await popup({local_paired: false});
  invalid.nodes["pair-code"].value = "invalid";
  await invalid.nodes["pair-form"].listeners.submit({preventDefault() {}});
  assert.ok(!invalid.calls.some(c => c.kind === "pair_local"));
  assert.equal(invalid.nodes["pair-code"].value, "");
  for (const pairStatus of ["PAIR_LIMITED", "PAIR_FAILED"]) {
    const {nodes} = await popup({local_paired: false}, {pairStatus});
    nodes["pair-code"].value = "a".repeat(20);
    await nodes["pair-form"].listeners.submit({preventDefault() {}});
    assert.equal(nodes.pairing.open, true);
    assert.equal(nodes["pair-code"].value, "");
    assert.match(nodes["pair-feedback"].textContent, /Too many attempts|Pairing failed/);
  }
});

test("successful re-pairing collapses a manually opened setup panel", async () => {
  const {nodes} = await popup();
  nodes.pairing.open = true;
  nodes["pair-code"].value = "a".repeat(20);
  await nodes["pair-form"].listeners.submit({preventDefault() {}});
  assert.equal(nodes.pairing.open, false);
});

test("unknown state leaves the switch disabled, with no false ON claim", async () => {
  for (const options of [{fail: "background_status"}, {}]) {
    const {nodes} = await popup({enabled: undefined}, options);
    assert.equal(nodes.power.disabled, true);
    assert.equal(nodes.status.dataset.tone, "error");
    assert.notEqual(nodes["power-label"].textContent, "ON");
  }
});

test("backup closes the popup only after the worker confirms opening a tab", async () => {
  const good = await popup();
  await good.nodes.open.listeners.click();
  assert.equal(good.closed(), true);
  const bad = await popup({}, {openStatus: "ERROR"});
  await bad.nodes.open.listeners.click();
  assert.equal(bad.closed(), false);
  assert.match(bad.nodes.feedback.textContent, /Could not communicate/);
});

test("portrait, permissions and background delivery safeguards are preserved", () => {
  const css = fs.readFileSync(path.join(extension, "popup.css"), "utf8");
  const worker = fs.readFileSync(path.join(extension, "background.js"), "utf8");
  const manifest = JSON.parse(fs.readFileSync(path.join(extension, "manifest.json"), "utf8"));
  assert.match(css, /original\/454286ac07a6f6e6\.jpeg/);
  assert.match(css, /background-color:\s*#111a29/);
  assert.match(css, /linear-gradient/);
  assert.match(css, /:focus-visible/);
  for (const badge of ["ON", "TAB", "429", "OFF"]) assert.ok(worker.includes(`badge = "${badge}"`));
  assert.equal(manifest.version, "0.5.2");
  assert.deepEqual(manifest.permissions, ["storage", "alarms"]);
  assert.ok(worker.includes("TRUSTED_CONTEXTS"));
  assert.ok(worker.includes("X-Trade-Alert-Token"));
  assert.ok(!worker.includes("chrome.downloads.download"));
});

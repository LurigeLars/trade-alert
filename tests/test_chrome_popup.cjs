"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const extension = path.resolve(__dirname,"../chrome_extension");
const html = fs.readFileSync(path.join(extension,"popup.html"),"utf8");
const popup = fs.readFileSync(path.join(extension,"popup.js"),"utf8");
const worker = fs.readFileSync(path.join(extension,"background.js"),"utf8");
const manifest = JSON.parse(fs.readFileSync(path.join(extension,"manifest.json"),"utf8"));

test("English popup with required controls and explanatory copy", () => {
  assert.match(html, /<html lang="en">/);
  for (const label of [
    "Trade Alert · Trump Monitor",
    "Activate Trump Monitor",
    "Disable Trump Monitor",
    "Backup Monitor",
    "Keep Chrome running"
  ]) assert.ok(html.includes(label),"Missing: "+label);
  for(const swedish of [
    "Trump-flöde", "Testa och aktivera", "Stäng av",
    "Öppna kontoflik", "Kontrollerar tillägget",
    "Bakgrundsläge", "Senaste status", "Verifierade inlägg",
    "Senast kontrollerad", "Gör ett direkt test"
  ]) assert.ok(![html,popup].some(s=>s.includes(swedish)),"Found Swedish: "+swedish);
  assert.ok(popup.includes('"Background monitor: "'));
  assert.ok(popup.includes('Last background status: '));
  assert.ok(popup.includes('Verified posts: '));
  assert.ok(popup.includes('Background checked: '));
  assert.ok(popup.includes('Tab backup: '));
  assert.ok(popup.includes('Last tab status: '));
  assert.ok(popup.includes('toLocaleTimeString("en-GB")'));
});

test("Portrait background and opacity-based contrast have fallback", () => {
  assert.match(html, /original\/454286ac07a6f6e6\.jpeg/);
  assert.match(html, /background-color:\s*#111a29/);
  assert.match(html, /linear-gradient/);
  assert.match(html, /background:\s*rgba\(10,\s*21,\s*36,\s*\.88\)/);
  assert.match(html, /background:\s*rgba\(28,\s*48,\s*72,\s*\.89\)/);
  assert.match(html, /button:focus-visible/);
});

test("Healthy monitor uses ON rather than BG, and errors retain honest badges", () => {
  assert.ok(worker.includes('badge = "ON"'));
  assert.ok(!worker.includes('text: status === "HTTP_200" ? "BG"'));
  assert.ok(worker.includes('badge = "TAB"'));
  assert.ok(worker.includes('badge = "429"'));
  assert.ok(worker.includes('badge = "OFF"'));
  assert.ok(worker.includes("Trump Monitor ON"));
  assert.equal(manifest.name,"Trade Alert - Trump Monitor");
  assert.equal(manifest.version,"0.5.0");
  assert.ok(worker.includes("safePublicImageUrl"));
  assert.ok(worker.includes("sanitizedMedia"));
  assert.ok(!manifest.permissions.includes("downloads"));
  assert.ok(worker.includes("X-Trade-Alert-Token"));
  assert.ok(worker.includes("TRUSTED_CONTEXTS"));
  assert.ok(popup.includes("Local pairing: "));
  assert.ok(manifest.host_permissions.includes("http://127.0.0.1/*"));
  assert.ok(!manifest.permissions.includes("downloads"));
  assert.ok(worker.includes("LOCAL_INGEST"));
  assert.ok(!worker.includes("chrome.downloads.download"));
  assert.ok(popup.includes("Local delivery: "));
});

"use strict";
const status = document.getElementById("status");
const power = document.getElementById("power");
const pairCode = document.getElementById("pair-code");
const pairFeedback = document.getElementById("pair-feedback");
const feedback = document.getElementById("feedback");
const pairing = document.getElementById("pairing");
const notice = document.getElementById("notice");
const controls = [power, document.getElementById("open"), document.getElementById("pair")];
let enabled = null, paired;
const call = (kind, extra = {}) => chrome.runtime.sendMessage({kind, ...extra});
function busy(value) {
  controls.forEach(button => { button.disabled = value; });
  power.disabled = value || enabled === null;
}
function recent(value) {
  const age = Date.now() - Date.parse(value || "");
  return Number.isFinite(age) && age >= 0 && age <= 120000;
}
function time(value) {
  const date = value ? new Date(value) : null;
  return date && Number.isFinite(date.getTime()) ? date.toLocaleTimeString("en-GB") : "—";
}
function show(response) {
  if (typeof response?.enabled !== "boolean" || typeof response.local_paired !== "boolean") throw Error("Missing monitor state");
  enabled = response.enabled;
  power.setAttribute("aria-checked", String(enabled));
  document.getElementById("power-label").textContent = enabled ? "ON" : "OFF";
  const pairStatus = document.getElementById("pair-status");
  pairStatus.textContent = response.local_paired ? "Paired" : "Not paired";
  pairStatus.dataset.paired = String(response.local_paired);
  pairing.hidden = false;
  if (paired !== response.local_paired) pairing.open = !response.local_paired;
  paired = response.local_paired;
  document.getElementById("pairing-summary").textContent = paired ? "Pair again" : "Pair with Trade Alert";
  const cooldown = Number(response.cooldown_until || 0) > Date.now();
  const tabActive = !enabled && !cooldown && response.tab_status === "HTTP_200" && recent(response.tab_checked);
  let text = "Background monitoring is off", tone = "muted";
  if (cooldown) {
    text = "Rate limited until " + time(response.cooldown_until); tone = "warning";
  } else if (enabled && response.status === "HTTP_200" && recent(response.checked)) {
    text = "Receiving public posts"; tone = "ok";
  } else if (tabActive) {
    text = "Backup tab is active"; tone = "ok";
  } else if (recent(response.checked) && ["HTTP_401", "HTTP_403"].includes(response.status)) {
    text = "Access denied · try Backup Monitor"; tone = "error";
  } else if (recent(response.checked) && !["HTTP_200", "NOT_TESTED"].includes(response.status)) {
    text = "Background source unavailable"; tone = "error";
  } else if (!enabled && recent(response.tab_checked) && ["HTTP_401", "HTTP_403", "ERROR"].includes(response.tab_status)) {
    text = "Backup tab unavailable"; tone = "error";
  } else if (enabled) {
    text = "Waiting for a fresh check"; tone = "warning";
  }
  status.textContent = text; status.dataset.tone = tone;
  notice.textContent = !paired ? "Pair with Trade Alert to deliver alerts."
    : response.delivery_status === "BRIDGE_OFFLINE" ? "Last local delivery failed. Check that Trade Alert is running."
    : response.delivery_status === "PAIR_REQUIRED" ? "Local delivery needs pairing again." : "";
  notice.hidden = !notice.textContent;
}
async function action(kind) {
  const focused = document.activeElement;
  busy(true); feedback.textContent = "";
  if (kind === "background_test") { status.textContent = "Checking background access…"; status.dataset.tone = "muted"; }
  try {
    if (kind !== "background_status") {
      const result = await call(kind);
      if (kind === "open_tab") {
        if (result?.status !== "TAB_OPENED") throw Error("Tab not opened");
        window.close(); return;
      }
      if (result?.status === "BUSY") feedback.textContent = "A check is already running. Try again shortly.";
    }
    show(await call("background_status"));
  } catch {
    enabled = null; status.textContent = "Monitor status unavailable"; status.dataset.tone = "error";
    feedback.textContent = "Could not communicate with the extension. Reopen this popup to retry.";
  } finally {
    busy(false);
    if (focused === power && document.activeElement === document.body) power.focus();
  }
}
power.addEventListener("click", () => action(enabled ? "background_off" : "background_test"));
document.getElementById("open").addEventListener("click", () => action("open_tab"));
document.getElementById("pair-form").addEventListener("submit", async event => {
  event.preventDefault();
  const code = pairCode.value.trim().toUpperCase(); pairCode.value = "";
  if (!/^[A-F0-9]{20}$/.test(code)) { pairFeedback.textContent = "Enter the 20-character code from Windows."; return; }
  busy(true); pairFeedback.textContent = "Pairing…";
  try {
    const result = await call("pair_local", {code});
    pairFeedback.textContent = result?.status === "PAIRED" ? ""
      : result?.status === "PAIR_LIMITED" ? "Too many attempts. Wait before trying again."
      : "Pairing failed. Check the code and that Trade Alert is running.";
    show(await call("background_status"));
    if (result?.status === "PAIRED") pairing.open = false;
  } catch { pairFeedback.textContent = "Could not reach the local application."; }
  finally { busy(false); }
});
action("background_status");

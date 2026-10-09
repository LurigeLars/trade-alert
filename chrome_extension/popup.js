"use strict";

const el = document.getElementById("status");
const buttons = ["test", "off", "open", "pair"].map(
  id => document.getElementById(id)
);
const pairCode = document.getElementById("pair-code");
const pairFeedback = document.getElementById("pair-feedback");
async function call(kind, extra = {}) {
  return chrome.runtime.sendMessage({kind, ...extra});
}
function show(response) {
  if (!response) {
    el.textContent = "No response from the extension.";
    return;
  }
  const label = response.status || "NOT_TESTED";
  const enabled = response.enabled === true;
  const cooldown = Number(response.cooldown_until || 0) > Date.now();
  const tabAge = Date.now() - Date.parse(response.tab_checked || "");
  const tabActive = !enabled && !cooldown &&
    response.tab_status === "HTTP_200" &&
    Number.isFinite(tabAge) && tabAge >= 0 && tabAge <= 120000;
  el.textContent =
    "Background monitor: " + (enabled ? "ON" : "OFF") +
    "\nLast background status: " + label +
    (response.checked ? "\nBackground checked: " +
      new Date(response.checked).toLocaleTimeString("en-GB") : "") +
    "\nTab backup: " + (enabled ? "STANDBY" : tabActive ? "ACTIVE" : "INACTIVE") +
    (response.tab_checked ? "\nLast tab status: " + response.tab_status +
      " (" + new Date(response.tab_checked).toLocaleTimeString("en-GB") + ")" : "") +
    (Number.isFinite(response.count) ? "\nVerified posts: " + response.count : "") +
    "\nLocal pairing: " + (response.local_paired ? "PAIRED" : "REQUIRED") +
    "\nLocal delivery: " + (response.delivery_status || "NOT_TESTED") +
    (response.delivery_checked ? " (" +
      new Date(response.delivery_checked).toLocaleTimeString("en-GB") + ")" : "") +
    (cooldown ? "\nRate limited: paused until " +
        new Date(response.cooldown_until).toLocaleTimeString("en-GB")
      : "");
}
async function action(kind) {
  buttons.forEach(b => {b.disabled = true;});
  el.textContent = kind === "background_test"
    ? "Testing background access…"
    : "Updating…";
  try {
    const response = await call(kind);
    if (kind === "open_tab") window.close();
    else if (kind === "background_status") show(response);
    else show(await call("background_status"));
  } catch {
    el.textContent = "Could not communicate with the extension.";
  } finally {
    buttons.forEach(b => {b.disabled = false;});
  }
}
buttons[0].addEventListener("click", () => action("background_test"));
buttons[1].addEventListener("click", () => action("background_off"));
buttons[2].addEventListener("click", () => action("open_tab"));
buttons[3].addEventListener("click", async () => {
  const code = pairCode.value.trim().toUpperCase();
  if (!/^[A-F0-9]{20}$/.test(code)) {
    pairFeedback.textContent = "Enter the 20-character code from Windows.";
    return;
  }
  buttons.forEach(button => {button.disabled = true;});
  pairFeedback.textContent = "Pairing with Windows application…";
  try {
    const result = await call("pair_local", {code});
    if (result?.status === "PAIRED") {
      pairCode.value = "";
      pairFeedback.textContent = "Paired. Authenticated local delivery enabled.";
    } else {
      pairFeedback.textContent = result?.status === "PAIR_LIMITED"
        ? "Too many attempts. Wait before trying again."
        : "Pairing failed. Check the code and that Trade Alert is running.";
    }
    show(await call("background_status"));
  } catch {
    pairFeedback.textContent = "Could not reach the local application.";
  } finally {
    buttons.forEach(button => {button.disabled = false;});
  }
});
action("background_status");

"use strict";

const el = document.getElementById("status");
const buttons = ["test", "off", "open"].map(id => document.getElementById(id));
async function call(kind) {
  return chrome.runtime.sendMessage({kind});
}
function show(response) {
  if (!response) {
    el.textContent = "No response from the extension.";
    return;
  }
  const label = response.status || "NOT_TESTED";
  const enabled = response.enabled === true;
  el.textContent =
    "Background monitor: " + (enabled ? "ON" : "OFF") +
    "\nLast status: " + label +
    (Number.isFinite(response.count) ? "\nVerified posts: " + response.count : "") +
    (response.checked ? "\nLast checked: " +
      new Date(response.checked).toLocaleTimeString("en-GB") : "");
}
async function action(kind) {
  buttons.forEach(b => {b.disabled = true;});
  el.textContent = kind === "background_test"
    ? "Testing background access…"
    : "Updating…";
  try {
    const response = await call(kind);
    if (kind === "open_tab") window.close();
    else show(response);
  } catch {
    el.textContent = "Could not communicate with the extension.";
  } finally {
    buttons.forEach(b => {b.disabled = false;});
  }
}
buttons[0].addEventListener("click", () => action("background_test"));
buttons[1].addEventListener("click", () => action("background_off"));
buttons[2].addEventListener("click", () => action("open_tab"));
action("background_status");

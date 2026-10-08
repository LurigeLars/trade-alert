"use strict";

const el = document.getElementById("status");
const buttons = ["test", "off", "open"].map(id => document.getElementById(id));
async function call(kind) {
  return chrome.runtime.sendMessage({kind});
}
function show(response) {
  if (!response) {
    el.textContent = "Inget svar från tillägget.";
    return;
  }
  const label = response.status || "NOT_TESTED";
  const enabled = response.enabled === true;
  el.textContent =
    "Bakgrundsläge: " + (enabled ? "PÅ" : "AV") +
    "\nSenaste status: " + label +
    (Number.isFinite(response.count) ? "\nVerifierade inlägg: " + response.count : "") +
    (response.checked ? "\nSenast kontrollerad: " +
      new Date(response.checked).toLocaleTimeString("sv-SE") : "");
}
async function action(kind) {
  buttons.forEach(b => {b.disabled = true;});
  el.textContent = kind === "background_test"
    ? "Gör ett direkt test utan kontoflik…"
    : "Uppdaterar…";
  try {
    const response = await call(kind);
    if (kind === "open_tab") window.close();
    else show(response);
  } catch {
    el.textContent = "Kunde inte kommunicera med tillägget.";
  } finally {
    buttons.forEach(b => {b.disabled = false;});
  }
}
buttons[0].addEventListener("click", () => action("background_test"));
buttons[1].addEventListener("click", () => action("background_off"));
buttons[2].addEventListener("click", () => action("open_tab"));
action("background_status");

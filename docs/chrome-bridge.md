# Chrome public-account bridge (prototype)

The user verified that a normal Chrome tab can fetch the public Truth Social
account JSON with HTTP 200, three times consecutively, while standalone Python
and a separate automated Chromium session receive 403. This only proves that
the request succeeded **inside that Chrome tab**. An installed extension needs
a separate end-to-end test and might still fail. This component does not copy
cookies, tokens or browser profiles and does not change IP addresses.

## Architecture

1. A voluntary Chrome Manifest V3 extension runs only when
   https://truthsocial.com/@realDonaldTrump (or the fixed JSON endpoint)
   is open in a normal Chrome tab. It requests only the fixed public JSON
   endpoint with a same-origin browser fetch approximately every 30 seconds.
2. The extension validates public-account identity and post ID and stores a
   bounded cursor in chrome.storage.local. Its **first successful fetch
   establishes the baseline without any downloads or alerts**.
3. Later new posts (up to five minutes old) are downloaded as JSON under the
   browser's default Downloads/TradeAlertChrome directory. No local HTTP
   listener, PowerShell execution, secret exchange or native messaging.
4. Trade Alert reads downloaded files approximately once per second, validates
   account ID, handle, public visibility, post ID and timestamp again, then
   applies existing relevance scoring and deduplication to its local SQLite
   alert history and Windows notifications.

This is an **opt-in prototype**. There is no way to claim it is always-on or
reliable when Chrome or the relevant tab is closed. Background tabs can be
throttled and suspended, exceeding the nominal 30-second interval.
A Chrome download folder outside the standard user Downloads path will require
a future explicit folder configuration or moving the files.

## Installing on Windows after merging

1. Update Trade Alert to the merged commit and install with the existing
   scripts/install-windows-startup.ps1, as usual.
2. Open %LOCALAPPDATA%/TradeAlert/config.json and set:
   "chrome_bridge_enabled": true
   Do not change source allowlists or claim LICENSED/AUTHORIZED_RELAY.
   Restart the tray application to load the updated config.
3. Open chrome://extensions; enable Developer mode; click "Load unpacked".
   Select C:\ClaudeCode\trade-alert\chrome_extension.
4. Click the extension icon to open https://truthsocial.com/@realDonaldTrump.
   Leave the account tab open and confirm the extension badge shows ON
   after a successful first-party fetch. A 403/ERR badge means no live data.
5. Chrome downloads files into its configured default Downloads directory.
   With default Chrome settings, the directory is
   C:\Users\<user>\Downloads\TradeAlertChrome.
   If Chrome prompts to choose a location, select the normal Downloads folder.
6. A fresh new market-relevant post should create an unread alert in the
   Trade Alert window and a Windows toast. Nonmarket posts may be transferred
   but must not cause a market alert. Verify publication, Chrome observation
   and Trade Alert receipt latencies using an actual future post.

Do not test by manipulating public source timestamps or sending fake live
posts into production alert history. Python unit tests exercise ingestion
with synthetic data in temporary databases.

## Trump Monitor popup design (version 0.2.1)

The popup interface is in English and uses the public portrait avatar from
Truth Social as a visual backdrop, layered beneath dark translucent panels
for readable status, buttons and help text. Its host is
`static-assets-1.truthsocial.com`. The portrait is referenced as a public
image URL, **not bundled into the extension**, so if the CDN cannot be
reached the popup retains a dark background fallback. No additional
permissions, remote scripts or tracking calls are introduced.

The controls are **Activate Trump Monitor**, **Disable Trump Monitor**,
and **Backup Monitor**. The latter still opens the same first-party
account tab. A successful background poll shows badge **ON** (previously
**BG**); denied and failed requests continue to display **403** and
**ERR**. These are UI-only changes: account verification, polling,
local notifications and existing source cursors remain unchanged.

## Optional tab-free test (Chrome MV3 background service worker)

Starting with extension version 0.2.0, click the extension icon to open its
small control panel. Click **Testa och aktivera utan flik**. The service worker
then tries the same FIXED public account endpoint in its *own* network context.
No existing web-tab session, cookies, login tokens, IP changes or proxies are
used. Chrome's `host_permissions` enable the request, but Cloudflare may
still block it.

- **HTTP_200 / BG badge:** the background request returned a verified public
  account list. Chrome creates a 30-second repeating `chrome.alarms` task,
  independent of any Truth Social tab. You may close the account tab, but Chrome
  itself must stay running. This result is a current connectivity check, not a
  tested continuous-latency SLA.
- **HTTP_403 / 403 badge:** the background fetch was blocked. It remains
  disabled, no automatic retry of the denied request is attempted, and you
  should continue using the existing tab reader and RSS fallback.
- **ERROR / ERR badge:** request, JSON or account verification failed. Do not
  interpret it as a working background feed.
- **Stäng av bakgrundsläge** stops the alarm and returns to legacy tab mode.
  **Öppna kontoflik (reserv)** still opens the working original page.

If Chrome's extensions page reports `Uncaught Error: Extension context invalidated`
from `relay.js` after reloading an unpacked extension, the old open
Truth Social tab may still contain a content-script listener belonging to the
previous extension instance. That old script cannot contact the new instance.
Close the unnecessary account tab while BG is running (or reload the tab if
using the tab fallback). The error listing is historical and can be cleared
in `chrome://extensions`. The relay guards synchronous and asynchronous
invalidated-context errors and detaches a stale listener. This error does not
by itself indicate that the independently probed BG feed has failed.

The extension intentionally does not use headless Playwright, launch another
Chromium browser, connect Chrome via an exposed debugging port, or work around
Cloudflare access controls. A separate automated Chromium was previously
observed to receive an HTTP 403; Chrome's background worker may likewise be
refused. A real user-machine test is mandatory.

## Security and reliability limits

- The extension can read the fixed public JSON endpoint only from its listed
  host permission; it never exports cookies or account credentials.
- Chrome MAIN-world messages must be considered **untrusted**. The receiving
  Python process validates fixed account identity, fresh publication and
  post IDs again; this is not a cryptographically authenticated feed.
- The downloaded JSON folder is writable by local applications and is not
  a security boundary. Treat alerts as source observations, not verified facts.
- Blocked 401/403/429 responses stop the in-tab reader, without attempting
  to bypass them. Resume only after the user reloads an allowed page.
- Full RSS monitoring remains enabled as fallback. Different source IDs may
  still cause duplicate coverage when both sources publish the same statement;
  evaluate live behavior before considering this production-ready.
- Only text posts are classified. Media-only posts are recorded as seen and
  skipped until separate image/video processing is developed.
- Trade Alert never submits orders or credentials.
- Truth Social's contractual restrictions on automated collection still apply.
  Technical access does not imply provider permission. Use of this component
  requires the user's own assessment of those terms and applicable law.
- Nominal fetch/poll intervals do **not** establish a measured 60-second
  publication-to-alert service level.

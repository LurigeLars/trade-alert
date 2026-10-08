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

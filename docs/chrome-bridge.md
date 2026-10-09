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
3. Later new posts (up to five minutes old) are transferred by a POST to
   **127.0.0.1:18761/chrome-post**. There is no use of Chrome's downloads API,
   no Save As prompt and no public inbound network listener.
4. Trade Alert's Windows process listens only on IPv4 loopback and accepts
   the POST only with an extension Origin, exact path, JSON content type,
   fixed header, paired extension Origin, bearer token and bounded body. It validates public account identity,
   atomically writes the post into the existing internal Chrome inbox and
   acknowledges the exact post ID. The same one-second file scanner then
   independently validates, scores and deduplicates posts before saving
   unread alerts and delivering Windows notifications.
5. If the local app is offline, the extension records BRIDGE_OFFLINE and
   **does not mark the post as delivered**. It retries on subsequent fetches
   while the post remains fresh. It never falls back to user-visible downloads.

This is an **opt-in prototype**. There is no way to claim it is always-on or
reliable when Chrome or the relevant tab is closed. Background tabs can be
throttled and suspended, exceeding the nominal 30-second interval.
The loopback server still uses the existing internal
\`~/Downloads/TradeAlertChrome\` directory to hand records to the scanner,
but files are created by the Windows app, never downloaded by Chrome.
Chrome's default download directory and "Ask where to save" settings no
longer matter. The folder is not a long-term archive: the scanner deletes
files after handling them. Legacy files from the old extension may still
be consumed after upgrade if they remain in the normal directory.

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
5. Restart the Windows Trade Alert tray process so its loopback receiver
   starts. Check its log for "Chrome loopback inbox listening at
   127.0.0.1:18761". The receiver starts only when the existing
   chrome_bridge_enabled flag is true; no LAN or firewall port is opened.
6. Reload the unpacked Chrome extension at chrome://extensions after
   updating this code to version 0.3.0. Chrome may ask you once to approve
   new local host permissions. No per-post download approval is required.
7. Open the extension popup. "Local delivery: NOT_TESTED" is expected until
   a new post is handed off; "QUEUED" means a validated post was accepted
   into the local inbox; "BRIDGE_OFFLINE" means the Windows app is not
   reachable and the extension will retry while the post remains fresh.
8. A fresh new market-relevant post should create an unread alert in the
   Trade Alert window and a Windows toast. Nonmarket posts may be transferred
   but must not cause a market alert. Verify actual end-to-end latency with
   a real new post rather than a mocked historical event.

Do not test by manipulating public source timestamps or sending fake live
posts into production alert history. Python unit tests exercise ingestion
with synthetic data in temporary databases.

## Trump Monitor popup design (from version 0.2.1)

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

## Single source poller and HTTP 429 cooldown

When the Chrome background monitor is enabled, the normal account tab's
content script asks the extension for permission before **every** API read.
The background alarm is the only active extension poller. If background
monitoring is disabled, the account-tab reader can act as the backup.

If **either** reader receives HTTP 429, both readers pause new extension API
requests for at least 30 minutes. A larger server-specified `Retry-After`
is respected, capped at 24 hours. The background alarm is stopped; the
popup shows the exact **HTTP_429** response and the earliest time for a
manual reactivation attempt. **429** is displayed as `429`, not as `403`.
The user must manually select **Activate Trump Monitor** after the cooldown
expires; the extension does not continuously retry a denied endpoint.

HTTP 401/403 still disable background mode without proxy rotation,
session replay or access-control bypass. Opening the Truth Social website
may itself issue requests outside the extension's control; avoiding double
extension polling does not guarantee that the site never rate-limits.

The tab's permission handshake never shares cookies, authorization
headers or the extension's local state with the page, only a boolean
permitting or denying a tab read. If service-worker communication fails,
the tab does **not** fetch: it tries the lightweight permission check again
at its next interval. The existing third-party RSS fallback is independent.

## Badge versus actual monitor mode

The toolbar badge is derived centrally from the service worker's persisted
settings and fresh source observations, not directly from an account-tab
HTTP response. This prevents the former bug where opening Truth Social
changed the toolbar badge to ON even though the popup said
`Background monitor: OFF`.

- `ON`: independent background monitor enabled, with a successful
  background HTTP 200 within the preceding two minutes
- `TAB`: background monitor OFF, fresh tab-based backup HTTP 200
- `OFF`: no enabled background monitor and no fresh working tab source
- `WAIT`: background monitor enabled but no recent successful result yet
- `429`: shared API rate-limit cooldown still in force
- `403` / `401`: relevant recent source denied access
- `ERR`: enabled background source reported a recent error

The popup separately shows **Background monitor**, **Last background
status/checked**, and **Tab backup / Last tab status**. A historical
background HTTP 429 remains visible as historical context even when the
cooldown has elapsed and a working account tab is shown as TAB.
Opening the popup re-renders the badge from persisted state so stale
previous badges cannot persist indefinitely.

The 120-second source freshness heuristic describes the latest observed
poll, not end-to-end Windows alert delivery. The latter still requires a
real new post for end-to-end verification.


## Silent loopback delivery (version 0.3.0)

The old Chrome downloads bridge is deprecated. The Chrome browser's
per-file Save As setting may override the historical saveAs:false flag, so
it cannot reliably support unattended monitoring. We now deliver
verified public posts to a **loopback-only local server** started by the
Windows Trade Alert process when chrome_bridge_enabled is true.

- URL: http://127.0.0.1:18761/chrome-post (fixed).
- Permission: only http://127.0.0.1/* is added; the downloads permission is
  removed. Do not change this to a LAN or public bind.
- Origin: an installed Chrome extension
  (chrome-extension://<32-letter-Chrome-ID>).
- Method: POST, Content-Type: application/json,
  X-Trade-Alert-Bridge: 1; body capped at 16,384 bytes.
- Response: {"status":"QUEUED","id":"<validated-post-id>"}; the client
  marks the post seen only on a matching acknowledgement.
- The existing Python inbox validation and Windows notification logic are
  unchanged. This is *not* a cryptographically authenticated sender; post
  contents remain untrusted, and the fixed account identity is checked by
  both the HTTP handler and the file scanner. Local software could still
  impersonate this data, as with the previous Downloads folder.
- A source HTTP 200 indicates the feed works, not that Windows received a
  post. The popup exposes independent **Local delivery** status.
- When the Windows app is stopped or the socket cannot be opened, the
  extension never silently discards the current new post and never opens a
  Chrome save dialog; it may stop retrying after the five-minute freshness
  window expires.

Never ask users to disable Chrome's global download safety preferences just
to run Trade Alert.

## Authenticated Chrome-to-Windows pairing (extension v0.4.0)

**The v0.3.0 unpaired POST endpoint is disabled.** Local Windows
ingress on 127.0.0.1:18761 requires the exact paired Chrome extension
Origin **and** a random 256-bit bearer token. Another extension's
Origin alone is not sufficient. This protects against unauthorized
webpages/extensions but cannot defeat same-user Windows malware.

One-time setup (repeat when extension ID changes or credentials rotate):

1. Update the local repo and restart the tray application using
   scripts/install-windows-startup.ps1. Check that
   chrome_bridge_enabled=true in %LOCALAPPDATA%/TradeAlert/config.json.
2. Generate a one-time code locally in PowerShell; keep its output private:

       Set-Location 'C:\ClaudeCode\trade-alert'
       .\.venv\Scripts\python.exe -m trade_alert.chrome_pairing pair

3. Within 10 minutes, reload the unpacked Chrome extension at
   chrome://extensions and paste the displayed 20-character code into
   the popup's "One-time local pairing code" field. Click
   "Pair with Windows Trade Alert".
4. Confirm "Local pairing: PAIRED". The service worker stores the
   credential in chrome.storage.local with access restricted to
   TRUSTED_CONTEXTS. No credentials go to Truth Social.
5. For the next genuine new post, "Local delivery: QUEUED" means Windows
   accepted the post. Existing deduplication and relevance filters still
   determine which Windows alerts are generated. PAIR_REQUIRED means
   generate a new one-time code; BRIDGE_OFFLINE means restart the app.

Server-side controls:
- 127.0.0.1 IPv4 binding only, exact /chrome-pair and /chrome-post routes,
  fixed headers, bounded JSON length and content-type checks.
- Cryptographically random 80-bit pairing code expires after ten minutes
  and is valid for one exchange. The server writes only its hash to disk.
- The 256-bit bearer token is returned once to the extension; Windows
  stores only its SHA-256 hash, pinned extension Origin and pairing time.
  The token is never logged or committed.
- A new successful pairing revokes the preceding token and extension ID.
- Maximum five pairing requests in ten minutes, a separate unauthorized
  request limit, bounded post rate, three-second socket timeout and
  eight concurrent connections.
- Fail closed if pairing is missing or the token is rejected. No
  fallback to Chrome downloads or unauthenticated HTTP POSTs.

A local program with access to the same Windows user profile may be able
to read extension credentials or forge requests. Local pairing is not a
defense against a compromised Windows account. Treat public post content
as untrusted regardless of source authentication.

## Local public-image OCR (extension v0.5.0)

Chrome and the verified direct public-account source can now extract **text inside
image attachments**, not just the post caption. Example: a political caption
with a chart reading "DAYS WITH CRUDE OIL ABOVE $100" is classified as
**STANDARD / ENERGY** because "CRUDE OIL" appears in the image.

This is **optional on-device OCR via Tesseract**, not a cloud AI service.
No images are uploaded to an AI API. The Windows app fetches the original
public attachment from a strict allowlist of
`https://static-assets-[1-9].truthsocial.com` domains. It sends no
cookies/authorization, rejects redirects, and permits only bounded JPEG,
PNG and WebP content (up to 2 MiB and 16 million pixels).
At most one approved image per post is scanned. No arbitrary post links,
private files, videos or GIFs are fetched.

**Install once on Windows if needed:** Tesseract OCR is a separate local
application, not bundled in the Python project. Use a trusted installer,
for example the Windows package:

    winget install -e --id UB-Mannheim.TesseractOCR

Then verify in the local repo (no network request):

    .\.venv\Scripts\python.exe -m trade_alert.media_ocr

The check must print `Local image OCR: READY`. Restart Trade Alert
using `scripts/install-windows-startup.ps1`. Update/reload the unpacked
Chrome extension at `chrome://extensions` to **version 0.5.0**; existing
bridge pairing survives when the extension ID is unchanged.

OCR text and the original caption are labelled separately in Windows alerts,
with `[Bildtext via lokal OCR]`. OCR is *heuristic*: it can misread stylized
graphics and a historical screenshot does not establish current price truth.
A simple mention of oil in an image is STANDARD, not automatically HIGH.
No trades are executed.

**Fail/degraded behavior:** If local Tesseract is not installed, the
image cannot be reached, the format is invalid, or OCR times out, logs
record `OCR_UNAVAILABLE`/`OCR_FAILED`; the monitor continues analyzing
any normal text. Image contents are not guessed, and an unscanned image is
not reported as irrelevant with certainty. Media without an approved
image URL remains unscanned. Old posts are not backfilled: the existing
five-minute freshness and post-ID cursor still apply. This is not
video understanding or guaranteed semantic analysis of photos with no text.

## Security and reliability limits

- The extension can read the fixed public JSON endpoint only from its listed
  host permission; it never exports Truth Social cookies or account credentials. Its local bridge token stays in trusted extension storage.
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
- Text in approved public image attachments is classified only when local OCR
  is available. Video and unsupported media are not analyzed. A failure to
  read an image is explicitly logged and must not be interpreted as no risk.
- Trade Alert never submits orders or credentials.
- Truth Social's contractual restrictions on automated collection still apply.
  Technical access does not imply provider permission. Use of this component
  requires the user's own assessment of those terms and applicable law.
- Nominal fetch/poll intervals do **not** establish a measured 60-second
  publication-to-alert service level.

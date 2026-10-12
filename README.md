# Trade Alert

[![Tests](https://github.com/LurigeLars/trade-alert/actions/workflows/tests.yml/badge.svg)](https://github.com/LurigeLars/trade-alert/actions/workflows/tests.yml)
[![Static analysis](https://github.com/LurigeLars/trade-alert/actions/workflows/static-analysis.yml/badge.svg)](https://github.com/LurigeLars/trade-alert/actions/workflows/static-analysis.yml)
[![CodeQL](https://github.com/LurigeLars/trade-alert/actions/workflows/codeql.yml/badge.svg)](https://github.com/LurigeLars/trade-alert/actions/workflows/codeql.yml)
![License](https://img.shields.io/badge/license-MIT-green)

Trade Alert is a small Windows tray application for **low-latency market-news alerts around an active trade context**.

It continuously reads bounded news feeds, applies deterministic relevance rules, shows Windows notifications, and keeps an unread local alert history so a missed toast is still visible later.

A [direct public Truth Social reader](docs/truth-direct.md) checks the anonymous public JSON endpoint for the verified Trump account every 15 seconds when reachable, with failure backoff and RSS as a fallback. Availability must be verified from the Windows host; it never logs in or evades access restrictions.

**Image-text reliability:** Local OCR includes a bounded second pass over
the poster header and other image regions if the whole-image Tesseract
layout misses market terms. An offline reproducible test runs
`python -m trade_alert.media_ocr PATH_TO_IMAGE.png`, printing the OCR
text and deterministic classification; it does not generate any alerts.

**Historical OCR benchmark:** An unlabelled set of public Trump image URL references and a non-alerting, local 50-unique-image Tesseract diagnostic are available in [the real-image benchmark guide](docs/truth-ocr-benchmark.md). It does not measure accuracy until manually verified labels are added.

**Claim novelty and evidence triage:** All Truth Social/direct, Chrome and
archive alert candidates now pass through a deterministic, no-network evidence
step after topic scoring. It distinguishes direct policy action claims, quoted
historical recaps, background statistical context, counterfactual policy
reports and unknown claims. It never claims independent corroboration and does
not delay immediate policy-action alerts. A narrowly matched hypothetical
report inside an image alone no longer creates a weak policy alert unless
the original account caption is itself market-relevant. Existing oil/chart
STANDARD coverage remains intact. Offline comparison of the prior OCR report:
`python scripts/replay_truth_evidence.py --input <local-report.json>`.
This archived report contains no captions and is not a live pipeline replay.
[Evidence rules and limits](docs/trump-market-impact-filter.md#separate-evidence-and-novelty-triage).

**Public image OCR (optional):** Extension v0.5.0 forwards bounded,
allowlisted image attachment metadata for on-device Tesseract text recognition.
A chart or meme containing terms like `CRUDE OIL` can now trigger an
ENERGY alert even if the caption has no market terms. Install Tesseract on
Windows and verify `python -m trade_alert.media_ocr` reports READY.
The app fetches images only from approved Truth Social public static-asset
hosts, sends no image to an AI provider, and labels OCR-derived evidence.
[Setup and limits](docs/chrome-bridge.md#local-public-image-ocr-extension-v050).

An optional [local Chrome bridge](docs/chrome-bridge.md) transfers newly
observed posts from Chrome to the Windows app via a **silent localhost
HTTP POST** on 127.0.0.1:18761. Extension v0.4.0 requires one-time user-approved pairing and a bearer token pinned to the exact Chrome extension Origin. The [pairing instructions](docs/chrome-bridge.md#authenticated-chrome-to-windows-pairing-extension-v040) explain how to obtain the short-lived code locally. Extension v0.3.0 and later no longer use Chrome
downloads, so new posts cannot trigger repetitive Save As prompts.
Its receiver binds only to 127.0.0.1, validates public account identity,
and atomically queues posts for the existing local alert scanner.
The bridge is opt-in (chrome_bridge_enabled) and runs only when the Windows
tray application is active. The optional tab-free Chrome MV3 fetch probes
Truth Social every ~30 seconds when enabled. This source may still receive
HTTP 403 or 429; the silent local relay does not alter source access,
timeouts or rate limits. No browser cookies, credentials, proxy rotation
or debugging-port access are involved.
The Chrome popup is English-only, shows **ON** for a successful background
poll, and uses the public portrait avatar with dark readable overlays and a
dark fallback if the image CDN is unavailable.

Trump-account messages across the Chrome bridge, direct API and RSS archive
now use one [source-scoped multi-asset impact filter](docs/trump-market-impact-filter.md)
covering Fed/rates, tariffs, budgets/debt ceiling, NATO/defense, geopolitics,
energy and semiconductors/export controls. HIGH and STANDARD priorities appear
in Windows alert titles. Broad TradingView oil-news scoring is unchanged.

An independent [Trump's Truth RSS monitor](docs/trump-truth-rss.md) provides a public, third-party source for presidential statements. Its own provider generally updates every few minutes: it is not an institutional breaking wire or a direct Truth Social API.

It is deliberately **not** an execution system. It has no broker login, order placement, order modification, or order-cancellation capability.

## Current deployment and security posture

- local Windows tray process, started per-user with `pythonw.exe`.
- no PowerShell or console window during normal operation.
- TradingView Desktop News Flow is the primary broad discovery source.
- ticker-specific Official TradingView news is targeted corroboration/fallback through Trade Spine.
- no LLM is used in the hot notification path.
- user-specific watchlist IDs are discovered/pinned only in local state and are not committed.
- credentials, OAuth material, account identifiers, machine-specific paths and personal position state do not belong in Git.
- external headlines/provider payloads are untrusted data, never instructions.
- the project is notifier-only and cannot execute trades.

## Why this project exists

A slower portfolio process can be appropriate for thesis review and broad opportunity discovery, but it is not ideal for a live trade where a material headline should surface within seconds.

Trade Alert fills that narrower gap. An independent 1-second local policy
event inbox is available for **licensed/authorized upstream relays** (no new
provider enabled by default). It does not wait for Trade Spine or DTV network
calls. See [Fast policy alerts](docs/fast-policy-alerts.md).

Trade Alert fills that narrower gap:

```text
TradingView Desktop News Flow
       |  primary broad discovery
       v
Trade Alert
       |
       +--> deterministic oil/news relevance
       +--> dedupe + local unread history
       +--> Windows toast
       |
       +--> Official TradingView via Trade Spine
            targeted corroboration / fallback
```

Keeping this in a separate repository also isolates desktop UI, Windows lifecycle and notification failures from Trade Spine's durable portfolio/thesis state.

## News routing

The default example profile is a generic **Oil / Brent** context.

Primary source:

- DTV TradingView News Flow.
- polled every 20 seconds by default.
- up to 200 headlines per fetch.
- each successful cursor poll replays a 60-minute publication-time overlap so provider backfills with older `published_at` timestamps are still discovered promptly.
- cross-source provider item IDs are deduplicated locally, so the replay window and Official TradingView corroboration cannot create duplicate alerts for the same story.
- active TradingView watchlist is auto-resolved when no explicit local watchlist ID is configured.
- auto-resolution requires a verified oil routing anchor before the numeric ID is accepted.

Secondary source:

- Official TradingView symbol news through Trade Spine.
- default corroboration symbols: `ICEEUR:BRN1!` and `NYMEX:RB1!`.
- polled every 30 seconds by default.
- up to 25 headlines per symbol.

The source split is intentional. Broad News Flow is used for discovery because commodity contract/ticker news feeds can be sparsely tagged. Ticker-specific news remains useful as corroboration and fallback.

## Deterministic relevance

Broad feeds need a stricter filter than symbol-specific feeds. Trade Alert therefore uses a small reproducible score instead of an LLM in the hot path.

The current oil profile uses these principles:

- explicit oil/core term in the headline: +2.
- geopolitical/supply impact term: +2 **only when oil context already exists**.
- `Hormuz`: +4 even without an explicit oil ticker/core term, because the strait is itself a material oil/product supply route.
- provider-related oil symbol: +1 routing evidence.
- TradingView `urgency=1`: +1 only when oil context exists.
- a related symbol by itself cannot reach the alert threshold.

This avoids obvious false positives such as unrelated headlines containing generic words like `deal` or `increase`.

On the first News Flow activation, older headlines are baselined so an upgrade does not produce a burst of stale notifications.

Truth Social image OCR also recognizes tightly scoped geopolitical naval phrases such as `IRANIAN SHIPS`, even when the demonym occurs without the literal place name `Iran`. An account-posted comparison graphic (for example `Other Presidents / Trump`) is a **STANDARD contextual alert**, not verified evidence of a newly sunk vessel. On OCR failures, fresh image-dependent direct/Chrome posts are deferred for 60 seconds instead of being permanently marked seen; relevant caption-only actions are still delivered immediately. Retries stop at the configured source freshness limit (typically 300 seconds). This cannot recover a post already marked seen by an older running process or a post never received from its source.

## Tray UI

The tray menu exposes:

- current source health.
- **Latest alerts** / unread count; left-clicking the tray icon opens this view directly.
- **What is monitored?** for the effective routing/profile configuration.
- pause/resume.
- test notification.
- log-folder shortcut.
- light/dark/system theme.
- exit.

Unread real alerts are stored in local SQLite. **Latest alerts** initially shows the 10 newest entries. When more than 10 are available, **Show all N** (up to 30) expands the same window and reveals the rest. Each entry uses two lines: `[OLÄST] HH:MM DD/MM` (local publication time; **okänd** if unavailable), then `Provider · Headline`. Only the headline is a clickable hyperlink; relevance scores, source identifiers and raw URLs are hidden. Read entries use `[läst]`. Registration and DTV first-seen timestamps remain in SQLite and latency diagnostics. Only entries actually displayed are marked as read, after the window is mapped: opening the first 10 leaves older unread alerts counted until expansion. The tray icon keeps its unread badge while unread entries remain. The SQLite alert-history table retains only the 30 newest entries, automatically discarding older alert records both on new alerts and when opening an older database; headline/source deduplication evidence is not removed by this cap.

For news-latency diagnostics, Trade Alert also persists the first time a provider item is observed in DTV News Flow. Publication, first observation and registration timestamps remain available in SQLite and `news-latency` log diagnostics. A legacy alert's later observation must not be interpreted as its original first-seen time. The compact history view shows only publication time.

The information windows support selection, `Ctrl+A`, `Ctrl+C`, **Copy all**, scrolling, system-aware light/dark mode, and Per-Monitor DPI Awareness V2 on Windows. The button toolbar (including **Show all N** and **Close**) is pinned to a non-expanding bottom row so Windows display scaling and long histories cannot push it below the window. Only the main text pane scrolls and resizes. Headlines in **Latest alerts** are rendered as clickable hyperlinks; TradingView-relative `/news/...` paths are resolved to `https://www.tradingview.com`, while invalid or non-HTTPS links remain plain text. Repeated headlines retain their own article URLs, including after expanding the history. Copying the text preserves the compact layout without exposing hidden URLs.


Clicking a new real alert's Windows toast opens its exact persisted HTTPS article URL and marks only that alert as read after the browser reaches the local click handler and receives the article redirect. A DTV `/news/...` path is resolved against `https://www.tradingview.com`, retaining the provider's article path; Trade Alert never constructs a publisher URL from a provider ID. HTTPS links supplied by other feeds are preserved. Relative non-news paths, HTTP, credentials, malformed ports, backslashes and control/whitespace characters are rejected. Without a valid link, clicking opens **Senaste alerts** with just the matching entry and acknowledges it only when the window is shown. Expired entries do nothing; failed browser launches leave entries unread and retryable. Successful repeated clicks on the same toast are ignored and the tray unread badge updates immediately.

The backend remains **windows-toasts 1.3.1 / WinRT WindowsToaster**; pystray handles the tray icon. Trade Alert registers only its per-user notification display identity. Windows opens an ordinary HTTP link to a small **loopback-only listener inside the existing notifier process**, on a dynamically allocated port. A random, single-use path resolves to the saved alert key, never a URL from the request. The listener validates the exact Host/path, returns a non-cacheable HTTP 303 redirect to the validated HTTPS article, then acknowledges only that row. Concurrent/repeated requests cannot launch the same action twice. Missing URLs instead display the matching history window. Tokens stay in memory, bounded to 30 pending alerts. No new dependency, separate process, custom URI scheme or database migration is used.

**Why the listener:** native WinRT in-process activation was evaluated on the actual Windows pythonw installation. One isolated click worked, but a subsequent production-code click failed to deliver its callback. A custom URI scheme also produced a missing-app/Store prompt. Neither is relied on for acknowledgement. Standard HTTP activation uses the existing browser association and provides a request that can be tested directly. A human clicked the production-code web-activation probe on Windows: the real article opened, its separate test row became read, the control row stayed unread and the badge callback reported one remaining unread entry.

**Limits:** the listener requires the sending Trade Alert process to remain running. Notifications retained across a restart have expired local links; use the tray history instead. Windows notification policy / Do Not Disturb can suppress a toast even when submission succeeds. Sending the redirect confirms the browser reached the listener, not that the external article loaded or was read. Frozen/MSIX packaging has not been certified; the existing unpackaged pythonw installation is the target. Successful article clicks update the unread badge immediately. The listener opens only after an actionable toast is sent and never binds to LAN.

To check on Windows, use a fresh qualifying alert, note its unread state and another unread entry, then click its banner or Notification Center entry while the sender is running. Confirm the exact article opens, only the clicked entry becomes read, and the badge decreases. Also check missing URLs (single-entry history, acknowledged on display), a rejected/failed redirect (still unread), and repeated clicks (no duplicate article). Synthetic probes must use a separate state database so real cursors and dedupe remain untouched. `--test-notification` is only a submission smoke test; it has no article/read action.

Trade Alert sets a stable Windows AppUserModelID and uses a **fixed, green, badge-free application icon** for Tk information windows and the Windows taskbar. Only the live **notification-area (tray) icon** displays changing health colors or a red unread badge. Windows can cache a taskbar icon across status changes, so window/taskbar icons must not encode transient health or unread state.

## Quick start

### Requirements

- Windows 10/11.
- Python 3.12+.
- [uv](https://docs.astral.sh/uv/).
- TradingView Desktop MCP for the primary News Flow path.
- Trade Spine only for the Official TradingView corroboration/fallback path.

Clone and install:

```powershell
git clone https://github.com/LurigeLars/trade-alert.git
Set-Location .\trade-alert

uv venv --python 3.12 .venv
uv pip install --python .\.venv\Scripts\python.exe --editable .
```

Smoke tests:

```powershell
uv run --python 3.12 python -m unittest discover -s tests -p "test_*.py"
uv run --python 3.12 python -m trade_alert --test-notification
uv run --python 3.12 python -m trade_alert --once
uv run --python 3.12 python -m trade_alert --rss-once   # direct source connectivity smoke
uv run --python 3.12 python -m trade_alert --direct-once  # anonymous direct-access smoke
uv run --python 3.12 python -m trade_alert --diagnose-direct # read-only bounded HTTP 403 diagnostics
```

Install the per-user tray startup:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows-startup.ps1
```

The startup shortcut points directly to `.venv\Scripts\pythonw.exe`, so normal operation does not leave a terminal window open. The installer generates a local multi-size `%LOCALAPPDATA%\TradeAlert\trade-alert.ico` from the same artwork as the live tray icon and assigns it to the Startup shortcut (and matching pinned taskbar shortcuts when accessible). The static shortcut uses the healthy green motif without a stale unread badge. A Windows taskbar pin can cache its old icon, so unpin/repin if needed.

To update **only the shortcut icon** without reinstalling or restarting live monitoring:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\set-windows-shortcut-icon.ps1
```


## Configuration and local state

On first run Trade Alert creates local state under:

```text
%LOCALAPPDATA%\TradeAlert
```

The Git-tracked `config.example.json` documents the available settings. Local configuration contains operational preferences only and must not be used to commit credentials or personal position state.

Important settings include:

| Setting | Purpose |
|---|---|
| `profile_name` | Human-readable local monitoring label |
| `theme_mode` | `system`, `light`, or `dark` |
| `dtv_watchlist_id` | Optional explicit numeric TradingView watchlist ID; otherwise auto-resolved locally |
| `official_symbols` | Targeted Official TradingView corroboration symbols |
| `poll_seconds` | Primary News Flow cadence |
| `official_poll_seconds` | Corroboration cadence |
| `dtv_max_headlines` | Broad News Flow fetch bound |
| `dtv_replay_overlap_seconds` | Publication-time replay overlap used to catch late/backfilled News Flow stories (default 3600 s) |
| `official_max_headlines` | Per-symbol corroboration bound |
| `notification_min_score` | Deterministic alert threshold |
| `breaking_inbox_enabled` | Start separate local breaking-event intake task (does not enable an upstream provider) |
| `breaking_poll_seconds` | Consumer cadence (1 second by default) |
| `breaking_max_age_seconds` | Maximum age of policy events eligible for alert |
| `breaking_authorized_sources` | Locally approved source identifiers; empty until a permitted provider is integrated |
| `truth_rss_enabled` | Enable independent third-party public RSS source |
| `truth_rss_poll_seconds` | RSS check cadence (default 30 s, with failure backoff) |
| `truth_rss_max_age_seconds` | Maximum age of RSS items eligible for a new Windows alert |
| `truth_direct_enabled` | Attempt anonymous public Truth Social account reading (may be blocked) |
| `truth_direct_poll_seconds` | Direct source cadence, with strict backoff for 401/403/429 |
| `truth_direct_max_age_seconds` | Maximum age for a new direct-post alert |
| `chrome_bridge_enabled` | Enable local Chrome download-file reader (off by default) |
| `chrome_bridge_poll_seconds` | Local file scan cadence (default 1 second) |
| `chrome_bridge_max_age_seconds` | Maximum age for new Chrome relay alerts |

Local SQLite stores seen-headline dedupe, source cursors, locally resolved watchlist metadata and unread alert history.

## Security model

Trade Alert intentionally keeps a narrow capability boundary:

- no brokerage authentication.
- no account or portfolio API.
- no order execution.
- no arbitrary shell exposed to the application.
- no committed OAuth material or credentials.
- no personal position state in repository fixtures/defaults.
- no trust in headline text as instructions.
- verified provider identifiers before live use.

The Windows host-maintenance path used in the local development stack is separately allowlisted; it is not part of the Trade Alert application API.

For vulnerability reporting, see [SECURITY.md](SECURITY.md).

## Development and repository policy

The repository runs:

- tests on Python 3.12 and 3.13.
- PowerShell syntax checks.
- actionlint and immutable GitHub Action pin enforcement.
- PSScriptAnalyzer.
- exact runtime dependency-pin policy.
- CodeQL.
- Dependabot for Python dependencies and GitHub Actions.

The public-repository policy keeps `main` PR-only with zero mandatory approvals for a single-maintainer repository, strict/up-to-date required checks, no force-push or default-branch deletion, and CodeQL thresholds that block quality errors and High/Critical security findings.

No CODEOWNERS or mandatory review ceremony is required.

Repository owners can apply or repair the GitHub-side baseline with the idempotent maintenance script below. It requires an authenticated GitHub CLI session with repository administration permission; no token is stored by the script.

```powershell
.\\scripts\\configure-github-repo.ps1
```

The script enables the reviewed security settings, creates or updates the default-branch ruleset, and deletes only stale branches that can be proven to belong to a merged PR into the current default branch. Open or unmerged branches are left untouched.

## Independence and data limitations

Trade Alert is an independent project and is not affiliated with TradingView, Avanza, Microsoft, Yahoo, or the publishers surfaced by upstream news feeds.

News availability, tagging, timestamps and latency are controlled by upstream providers. A notification is discovery evidence, not an execution instruction or a guarantee that a market claim is correct.

## License

MIT. See [LICENSE](LICENSE).

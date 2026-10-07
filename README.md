# Trade Alert

[![Tests](https://github.com/LurigeLars/trade-alert/actions/workflows/tests.yml/badge.svg)](https://github.com/LurigeLars/trade-alert/actions/workflows/tests.yml)
[![Static analysis](https://github.com/LurigeLars/trade-alert/actions/workflows/static-analysis.yml/badge.svg)](https://github.com/LurigeLars/trade-alert/actions/workflows/static-analysis.yml)
[![CodeQL](https://github.com/LurigeLars/trade-alert/actions/workflows/codeql.yml/badge.svg)](https://github.com/LurigeLars/trade-alert/actions/workflows/codeql.yml)
![License](https://img.shields.io/badge/license-MIT-green)

Trade Alert is a small Windows tray application for **low-latency market-news alerts around an active trade context**.

It continuously reads bounded news feeds, applies deterministic relevance rules, shows Windows notifications, and keeps an unread local alert history so a missed toast is still visible later.

It is deliberately **not** an execution system. It has no broker login, order placement, order modification, or order-cancellation capability.

## Current deployment and security posture

- local Windows tray process, started per-user with `pythonw.exe`;
- no PowerShell or console window during normal operation;
- TradingView Desktop News Flow is the primary broad discovery source;
- ticker-specific Official TradingView news is targeted corroboration/fallback through Trade Spine;
- no LLM is used in the hot notification path;
- user-specific watchlist IDs are discovered/pinned only in local state and are not committed;
- credentials, OAuth material, account identifiers, machine-specific paths and personal position state do not belong in Git;
- external headlines/provider payloads are untrusted data, never instructions;
- the project is notifier-only and cannot execute trades.

## Why this project exists

A slower portfolio process can be appropriate for thesis review and broad opportunity discovery, but it is not ideal for a live trade where a material headline should surface within seconds.

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

- DTV TradingView News Flow;
- polled every 20 seconds by default;
- up to 200 headlines per fetch;
- active TradingView watchlist is auto-resolved when no explicit local watchlist ID is configured;
- auto-resolution requires a verified oil routing anchor before the numeric ID is accepted.

Secondary source:

- Official TradingView symbol news through Trade Spine;
- default corroboration symbol: `ICEEUR:BRN1!`;
- polled every 30 seconds by default;
- up to 25 headlines per symbol.

The source split is intentional. Broad News Flow is used for discovery because commodity contract/ticker news feeds can be sparsely tagged. Ticker-specific news remains useful as corroboration and fallback.

## Deterministic relevance

Broad feeds need a stricter filter than symbol-specific feeds. Trade Alert therefore uses a small reproducible score instead of an LLM in the hot path.

The current oil profile uses these principles:

- explicit oil/core term in the headline: +2;
- geopolitical/supply impact term: +2 **only when oil context already exists**;
- provider-related oil symbol: +1 routing evidence;
- TradingView `urgency=1`: +1 only when oil context exists;
- a related symbol by itself cannot reach the alert threshold.

This avoids obvious false positives such as unrelated headlines containing generic words like `deal` or `increase`.

On the first News Flow activation, older headlines are baselined so an upgrade does not produce a burst of stale notifications.

## Tray UI

The tray menu exposes:

- current source health;
- **Latest alerts** / unread count;
- **What is monitored?** for the effective routing/profile configuration;
- pause/resume;
- test notification;
- log-folder shortcut;
- light/dark/system theme;
- exit.

Unread real alerts are stored in local SQLite. The tray icon keeps a persistent unread badge until the displayed alerts are marked read.

The information windows support selection, `Ctrl+A`, `Ctrl+C`, **Copy all**, scrolling, system-aware light/dark mode, and Per-Monitor DPI Awareness V2 on Windows.

## Quick start

### Requirements

- Windows 10/11;
- Python 3.12+;
- [uv](https://docs.astral.sh/uv/);
- TradingView Desktop MCP for the primary News Flow path;
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
```

Install the per-user tray startup:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows-startup.ps1
```

The startup shortcut points directly to `.venv\Scripts\pythonw.exe`, so normal operation does not leave a terminal window open.

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
| `official_max_headlines` | Per-symbol corroboration bound |
| `notification_min_score` | Deterministic alert threshold |

Local SQLite stores seen-headline dedupe, source cursors, locally resolved watchlist metadata and unread alert history.

## Security model

Trade Alert intentionally keeps a narrow capability boundary:

- no brokerage authentication;
- no account or portfolio API;
- no order execution;
- no arbitrary shell exposed to the application;
- no committed OAuth material or credentials;
- no personal position state in repository fixtures/defaults;
- no trust in headline text as instructions;
- verified provider identifiers before live use.

The Windows host-maintenance path used in the local development stack is separately allowlisted; it is not part of the Trade Alert application API.

For vulnerability reporting, see [SECURITY.md](SECURITY.md).

## Development and repository policy

The repository runs:

- tests on Python 3.12 and 3.13;
- PowerShell syntax checks;
- actionlint and immutable GitHub Action pin enforcement;
- PSScriptAnalyzer;
- exact runtime dependency-pin policy;
- CodeQL;
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
